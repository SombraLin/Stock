import os
import asyncio
from fastapi import FastAPI, Query, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import pandas as pd
from typing import Optional

from datetime import datetime
from backend.database import (
    init_db, query_klines, get_data_stats,
    get_sim_account_summary, execute_sim_trade, reset_sim_account, set_initial_position,
    get_recent_notifications, get_push_settings, update_push_settings
)
from backend.fetcher import sync_symbol_5m_data, fetch_realtime_quotes
from backend.strategy import generate_signals
from backend.scheduler import trading_sync_worker, get_scheduler_status, do_sync_all_symbols
from backend.notifier import send_signal_alert
from backend.recommendations import closed_bars, recent as recent_recommendations, performance

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="China Merchants Bank & Ping An Bank Quantitative Trading Platform", version="1.0.0")

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
async def on_startup():
    init_db()
    # 启动开盘期间常驻后台定时刷新守护协程 (开盘每60秒，休市每300秒)
    asyncio.create_task(trading_sync_worker(interval_trading=60, interval_idle=300))

@app.get("/")
async def index(request: Request, mode: Optional[str] = None):
    """主入口：若检测为移动端自动重定向至手机版 (/m)，电脑端保持宽屏专业版"""
    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(k in ua for k in ["mobile", "android", "iphone", "ipad", "phone"])
    if is_mobile and mode != "desktop":
        return RedirectResponse(url="/m")
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/m")
async def mobile_page():
    """专门为手机触屏与单手操作优化的移动端工作台"""
    return FileResponse(os.path.join(STATIC_DIR, "mobile.html"))

@app.get("/api/sync/status")
async def api_sync_status():
    """获取当前开盘期定时数据同步状态"""
    return JSONResponse(content={"status": "success", "data": get_scheduler_status()})

@app.get("/api/notify/history")
async def api_notify_history(limit: int = 20):
    """获取最近向飞书推送的量化信号记录"""
    history = get_recent_notifications(limit=limit)
    return JSONResponse(content={"status": "success", "data": history})

@app.get("/api/notify/settings")
async def api_notify_settings():
    """获取当前飞书推送配置（全局开关与各股票独立开关、信号类型过滤规则）"""
    settings = get_push_settings()
    return JSONResponse(content={"status": "success", "data": settings})

@app.post("/api/notify/settings")
async def api_update_notify_settings(request: Request):
    """更新飞书推送配置"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"status": "error", "message": "Invalid JSON body"}, status_code=400)
    
    global_enabled = bool(body.get("global_enabled", True))
    stocks = body.get("stocks", [])
    
    ok = update_push_settings(global_enabled=global_enabled, stock_configs=stocks)
    if not ok:
        return JSONResponse(content={"status": "error", "message": "Failed to update settings in database"}, status_code=500)
    
    updated = get_push_settings()
    return JSONResponse(content={"status": "success", "message": "推送设置已更新并实时生效", "data": updated})

@app.post("/api/notify/test")
async def api_notify_test(request: Request):
    """手动测试飞书消息推送，支持指定标的与信号类型 (BUY/SELL)"""
    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    except Exception:
        body = {}
    symbol = body.get("symbol", "sh600036")
    signal_type = str(body.get("signal_type", "BUY")).upper()
    if signal_type not in ["BUY", "SELL"]:
        signal_type = "BUY"
    stock_name_map = {"sh600036": "招商银行", "sz000001": "平安银行", "sh601012": "隆基绿能"}
    stock_name = stock_name_map.get(symbol, symbol)
    quotes = fetch_realtime_quotes([symbol])
    fallback_map = {"sh600036": 42.94, "sz000001": 11.54, "sh601012": 12.00}
    fallback_price = fallback_map.get(symbol, 10.0)
    price = float(quotes.get(symbol, {}).get("price", fallback_price))
    
    is_buy = signal_type == "BUY"
    tp = round(price * 1.015, 2) if is_buy else round(price * 0.985, 2)
    sl = round(price * 0.992, 2) if is_buy else round(price * 1.008, 2)

    ok = send_signal_alert(
        symbol=symbol,
        stock_name=stock_name,
        signal_type=signal_type,
        price=price,
        signal_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        strategy_name=f"午后黄金多因子策略 ({'买点' if is_buy else '卖点'}手动测试)",
        reason=f"用户在控制台发起「{stock_name}」{'买入进场' if is_buy else '卖出离场'}飞书通知测试",
        plan={"take_profit_price": tp, "stop_loss_price": sl, "hold_minutes": 60}
    )
    return JSONResponse(content={"status": "success" if ok else "error", "sent": ok, "symbol": symbol, "signal_type": signal_type})

@app.get("/api/stats")
async def api_stats():
    """获取数据库中各标的的数据条数与时间范围"""
    stats = get_data_stats()
    return JSONResponse(content={"status": "success", "data": stats})


@app.get("/api/recommendations")
async def api_recommendations(limit: int = Query(50, ge=1, le=500)):
    """Immutable observations and separate T+1/inventory hypothetical outcomes."""
    return {"status": "success", "data": recent_recommendations(limit)}


@app.get("/api/recommendations/summary")
async def api_recommendation_summary():
    return {"status": "success", "data": performance(), "note": "假设成交评估；历史回放与实时推荐、买点与卖点、T+1与底仓做T分别统计"}

@app.get("/api/quotes")
async def api_quotes():
    """获取最新实时分时行情快照"""
    quotes = fetch_realtime_quotes(["sh600036", "sz000001", "sh601012", "sh000001"])
    return JSONResponse(content={"status": "success", "data": quotes})

@app.get("/api/klines")
async def api_klines(symbol: str = "sh600036", limit: int = 1500):
    """获取指定标的的历史 5 分钟 K 线"""
    rows = query_klines(symbol, limit=limit)
    return JSONResponse(content={
        "status": "success",
        "symbol": symbol,
        "count": len(rows),
        "data": rows
    })

@app.get("/api/analysis")
async def api_analysis(symbol: str = "sh600036", strategy: str = "boll_reversion", limit: int = 1500):
    """
    运行策略量化分析并返回包含技术指标、买卖点信号与回测评估结果，以及针对最新盘面的交易提示
    """
    stock_rows = closed_bars(query_klines(symbol, limit=limit))
    idx_rows = closed_bars(query_klines("sh510050", limit=limit))
    if not idx_rows:
        idx_rows = closed_bars(query_klines("sh000001", limit=limit))
    
    if not stock_rows:
        return JSONResponse(content={"status": "error", "message": f"No stock data available for {symbol}"}, status_code=400)
        
    stock_df = pd.DataFrame(stock_rows)
    idx_df = pd.DataFrame(idx_rows) if idx_rows else None
    
    result = generate_signals(stock_df, idx_df, strategy_name=strategy)
    return JSONResponse(content={
        "status": "success",
        "strategy": strategy,
        "symbol": symbol,
        "metrics": result["metrics"],
        "signals": result["signals"],
        "data": result["data"],
        "strategy_meta": result.get("strategy_meta", {}),
        "all_strategies": result.get("all_strategies", {}),
        "latest_decision": result.get("latest_decision", {})
    })

@app.post("/api/sync")
async def api_sync(background_tasks: BackgroundTasks):
    """增量同步最新5分钟K线到数据库 (支持所有标的)"""
    results = do_sync_all_symbols(datalen=120)
    stats = get_data_stats()
    scheduler_info = get_scheduler_status()
    return JSONResponse(content={
        "status": "success",
        "message": f"同步完成: {results}",
        "details": results,
        "scheduler": scheduler_info,
        "stats": stats
    })

@app.get("/api/sim/account")

async def api_sim_account(symbol: str = "sh600036"):
    """获取模拟交易账户资金、持仓与最新行情浮动盈亏"""
    # 尝试从行情接口或最新K线中获取实时价
    quotes = fetch_realtime_quotes([symbol])
    current_price = 0.0
    if symbol in quotes and quotes[symbol].get("price"):
        current_price = float(quotes[symbol]["price"])
    else:
        recent = query_klines(symbol, limit=1)
        if recent:
            current_price = float(recent[-1]["close"])

    summary = get_sim_account_summary(current_price=current_price, symbol=symbol)
    return JSONResponse(content={"status": "success", "data": summary})

@app.post("/api/sim/trade")
async def api_sim_trade(request: Request):
    """
    提交模拟买入/卖出委托
    payload: { symbol: 'sh600036', type: 'BUY'|'SELL', shares: 500, price: 42.98, note: '' }
    """
    body = await request.json()
    symbol = body.get("symbol", "sh600036")
    trade_type = body.get("type", "BUY")
    shares = int(body.get("shares", 100))
    price = float(body.get("price", 0.0))
    note = body.get("note", "")

    # 若未指定成交价，以最新实时价成交
    if price <= 0:
        quotes = fetch_realtime_quotes([symbol])
        if symbol in quotes and quotes[symbol].get("price"):
            price = float(quotes[symbol]["price"])
        else:
            recent = query_klines(symbol, limit=1)
            if recent:
                price = float(recent[-1]["close"])

    res = execute_sim_trade(symbol=symbol, trade_type=trade_type, shares=shares, price=price, note=note)
    if res.get("status") == "error":
        return JSONResponse(content=res, status_code=400)
    
    # 附带返回最新账户状态
    summary = get_sim_account_summary(current_price=price, symbol=symbol)
    res["account"] = summary
    return JSONResponse(content=res)

@app.post("/api/sim/reset")
async def api_sim_reset(request: Request):
    """一键重置模拟交易账户"""
    try:
        body = await request.json()
        initial_cash = float(body.get("initial_cash", 100000.0))
    except Exception:
        initial_cash = 100000.0

    res = reset_sim_account(initial_cash=initial_cash)
    if res.get("status") == "error":
        return JSONResponse(content=res, status_code=400)
    summary = get_sim_account_summary(current_price=0.0)
    res["account"] = summary
    return JSONResponse(content=res)


@app.post("/api/sim/set_holding")

async def api_sim_set_holding(request: Request):
    """自定义初始底仓（如昨天买入 1000 股 @ 42 元）"""
    body = await request.json()
    symbol = body.get("symbol", "sh600036")
    shares = int(body.get("shares", 1000))
    price = float(body.get("price", 42.0))
    buy_date = body.get("buy_date", "2026-10-28 14:30:00")
    initial_cash = float(body.get("initial_cash", 100000.0))
    
    res = set_initial_position(symbol=symbol, shares=shares, price=price, buy_date=buy_date, initial_cash=initial_cash)
    if res.get("status") == "error":
        return JSONResponse(content=res, status_code=400)
    quotes = fetch_realtime_quotes([symbol])
    current_price = price
    if symbol in quotes and quotes[symbol].get("price"):
        current_price = float(quotes[symbol]["price"])
    summary = get_sim_account_summary(current_price=current_price, symbol=symbol)
    res["account"] = summary
    return JSONResponse(content=res)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)


