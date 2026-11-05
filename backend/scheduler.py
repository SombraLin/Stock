import asyncio
from datetime import datetime, time
import logging
from typing import Dict, Any, List
import pandas as pd

from backend.fetcher import sync_symbol_5m_data
from backend.database import query_klines, is_signal_notified, record_signal_notification, get_push_settings
from backend.strategy import generate_signals
from backend.notifier import send_signal_alert
from backend.recommendations import closed_bars, china_now, record, evaluate

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)

SYNC_SYMBOLS = [
    ("sh600036", "招商银行"),
    ("sz000001", "平安银行"),
    ("sh601012", "隆基绿能"),
    ("sh000001", "上证指数"),
    ("sh510050", "上证50ETF")
]

MONITOR_TARGETS = [
    ("sh600036", "招商银行"),
    ("sz000001", "平安银行"),
    ("sh601012", "隆基绿能")
]

# 调度器运行状态
scheduler_state: Dict[str, Any] = {
    "running": False,
    "last_sync_time": None,
    "last_status": "initialized",
    "last_details": {},
    "is_trading_time": False,
    "sync_count": 0,
    "interval_seconds": 60,
    "error_msg": None,
    "last_alerts": []
}

def is_china_trading_time(now: datetime = None) -> bool:
    """
    判断当前时间是否处于 A 股交易时间段：
    周一至周五：
      上午：09:25 ~ 11:32
      下午：12:58 ~ 15:05
    """
    if now is None:
        now = datetime.now()
    
    # 0 = Monday, 6 = Sunday
    if now.weekday() > 4:
        return False

    t = now.time()
    morning = time(9, 25) <= t <= time(11, 32)
    afternoon = time(12, 58) <= t <= time(15, 5)
    return morning or afternoon

def check_and_notify_signals() -> List[Dict[str, Any]]:
    """
    扫描监控标的最新生成的买卖点信号，并在满足条件时推送飞书卡片（带数据库幂等去重与用户个性化推送配置过滤）
    """
    # 获取用户自定义推送配置
    push_settings = get_push_settings()
    if not push_settings.get("global_enabled", True):
        # 全局推送已关闭
        return []

    stock_configs = {s["symbol"]: s for s in push_settings.get("stocks", [])}

    alerts_triggered = []
    # 获取基准
    now = china_now()
    idx_rows = closed_bars(query_klines("sh510050", limit=200), now)
    if not idx_rows:
        idx_rows = closed_bars(query_klines("sh000001", limit=200), now)
    idx_df = pd.DataFrame(idx_rows) if idx_rows else None

    for sym, stock_name in MONITOR_TARGETS:
        try:
            # 检查该股票是否开启推送
            cfg = stock_configs.get(sym, {"enabled": True, "signal_filter": "ALL"})
            if not cfg.get("enabled", True):
                continue

            stock_rows = closed_bars(query_klines(sym, limit=200), now)
            if not stock_rows or len(stock_rows) < 30:
                continue
            
            stock_df = pd.DataFrame(stock_rows)
            # 使用经过大样本检验的旗舰策略：日线共振与大盘联动波段
            strat_key = "regime_confluence"
            res = generate_signals(stock_df, idx_df, strategy_name=strat_key, symbol=sym)
            signals = res.get("signals", [])
            if not signals:
                continue

            # 获取最新生成的信号
            latest_sig = signals[-1]
            sig_time = latest_sig.get("datetime")
            sig_type = latest_sig.get("type")
            sig_price = float(latest_sig.get("price", 0.0))
            reason = latest_sig.get("reason", "量化因子共振触发")
            plan = latest_sig.get("trade_plan") or latest_sig.get("plan", {})
            strat_name = res.get("strategy_meta", {}).get("name", "布林带极值均值回归")

            # 信号类型过滤 (ALL | BUY_ONLY | SELL_ONLY)
            sig_filter = cfg.get("signal_filter", "ALL")
            if sig_filter == "BUY_ONLY" and sig_type != "BUY":
                continue
            if sig_filter == "SELL_ONLY" and sig_type != "SELL":
                continue

            # 检查是否属于最近走完的 3 根K线内（避免冷启动重推很久以前的历史旧信号）
            recent_times = [r["datetime"] for r in stock_rows[-3:]]
            if sig_time not in recent_times:
                continue
            if (now - datetime.fromisoformat(str(sig_time))).total_seconds() > 20 * 60:
                continue

            # 数据库幂等排重检测
            if not is_signal_notified(sym, sig_type, sig_time):
                print(f"[Scheduler Alert] 发现新信号: {stock_name} {sig_type} at {sig_time} (¥{sig_price})，正在推送飞书...")
                ok = send_signal_alert(
                    symbol=sym,
                    stock_name=stock_name,
                    signal_type=sig_type,
                    price=sig_price,
                    signal_time=sig_time,
                    strategy_name=strat_key,
                    reason=reason,
                    plan=plan
                )
                if ok:
                    record_signal_notification(sym, sig_type, sig_time, sig_price, strat_name)
                    item = {
                        "symbol": sym,
                        "name": stock_name,
                        "type": sig_type,
                        "time": sig_time,
                        "price": sig_price,
                        "notified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    alerts_triggered.append(item)
                    scheduler_state["last_alerts"].append(item)
                    # 保留最近20条
                    if len(scheduler_state["last_alerts"]) > 20:
                        scheduler_state["last_alerts"] = scheduler_state["last_alerts"][-20:]
                    print(f"[Scheduler Alert ✓] 飞书推送成功: {stock_name} {sig_type}")
                else:
                    print(f"[Scheduler Alert ✗] 飞书推送失败")
            else:
                pass # 已经推送过，静默忽略
        except Exception as e:
            print(f"[Scheduler Signal Error] 处理 {sym} 信号检测失败: {e}")

    return alerts_triggered


def track_recommendations():
    """Always journal recommendations, even when push is disabled or delivery fails."""
    now = china_now()
    idx_rows = closed_bars(query_klines("sh510050", limit=200), now)
    if not idx_rows:
        idx_rows = closed_bars(query_klines("sh000001", limit=200), now)
    for symbol, _ in MONITOR_TARGETS:
        try:
            rows = closed_bars(query_klines(symbol, limit=200), now)
            if len(rows) < 60:
                continue
            result = generate_signals(pd.DataFrame(rows), pd.DataFrame(idx_rows) if idx_rows else None,
                                      strategy_name="regime_confluence", symbol=symbol)
            record(symbol, result, rows, idx_rows, now=now)
            # Existing events need a history longer than the live signal warmup.
            evaluate(symbol, query_klines(symbol, limit=None), now=now)
        except Exception:
            logger.exception("推荐点记录/评估失败: %s", symbol)

def do_sync_all_symbols(datalen: int = 60) -> Dict[str, int]:
    """同步所有监控标的的最新5分钟K线并触发信号扫描"""
    results = {}
    for sym, name in SYNC_SYMBOLS:
        try:
            cnt = sync_symbol_5m_data(sym, datalen=datalen)
            results[sym] = cnt
        except Exception as e:
            results[sym] = -1
            print(f"[Scheduler] 同步 {sym} ({name}) 出错: {e}")
    
    # 同步落库后，立即执行买卖点信号扫描
    track_recommendations()
    try:
        check_and_notify_signals()
    except Exception as e:
        print(f"[Scheduler] 扫描触发信号异常: {e}")

    return results

async def trading_sync_worker(interval_trading: int = 60, interval_idle: int = 300):
    """
    开盘期间常驻后台异步工作者：
    - 开盘交易时段 (9:25~11:32, 12:58~15:05): 每 60 秒轮询增量同步最新 5分钟K线并检测推送
    - 非交易与休市时段: 每 300 秒 (5分钟) 心跳检测，降低服务器负载
    """
    scheduler_state["running"] = True
    print(f"[Scheduler] 股票数据定时同步后台守护协程已启动！交易时段间隔: {interval_trading}s, 休市间隔: {interval_idle}s")

    # 服务启动预同步
    try:
        now = datetime.now()
        trading = is_china_trading_time(now)
        scheduler_state["is_trading_time"] = trading
        res = do_sync_all_symbols(datalen=120)
        scheduler_state["last_sync_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
        scheduler_state["last_details"] = res
        scheduler_state["last_status"] = "success"
        scheduler_state["sync_count"] += 1
        print(f"[Scheduler] 初次启动预同步完成: {res}")
    except Exception as e:
        scheduler_state["error_msg"] = str(e)
        print(f"[Scheduler] 初次启动同步异常: {e}")

    while True:
        try:
            now = datetime.now()
            trading = is_china_trading_time(now)
            scheduler_state["is_trading_time"] = trading
            
            if trading:
                scheduler_state["interval_seconds"] = interval_trading
                scheduler_state["last_status"] = "syncing"
                res = do_sync_all_symbols(datalen=60)
                scheduler_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                scheduler_state["last_details"] = res
                scheduler_state["last_status"] = "success"
                scheduler_state["sync_count"] += 1
                sleep_time = interval_trading
            else:
                scheduler_state["interval_seconds"] = interval_idle
                scheduler_state["last_status"] = "idle (market closed)"
                sleep_time = interval_idle

        except asyncio.CancelledError:
            print("[Scheduler] 定时同步协程收到取消信号，已优雅退出。")
            scheduler_state["running"] = False
            break
        except Exception as e:
            scheduler_state["last_status"] = "error"
            scheduler_state["error_msg"] = str(e)
            print(f"[Scheduler Loop Error] {e}")
            sleep_time = 30

        await asyncio.sleep(sleep_time)

def get_scheduler_status() -> Dict[str, Any]:
    """获取当前调度器状态"""
    now = datetime.now()
    trading = is_china_trading_time(now)
    state = dict(scheduler_state)
    state["is_trading_time"] = trading
    state["current_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
    state["symbols"] = [{"symbol": s, "name": n} for s, n in SYNC_SYMBOLS]
    return state
