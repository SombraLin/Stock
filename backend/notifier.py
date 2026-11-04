import requests
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("notifier")

DEFAULT_FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/dc87d069-d483-4364-a537-f4b7bf467628"
DASHBOARD_URL = "http://117.72.29.130/"

# 标的 Emoji 隐蔽映射表
SYMBOL_EMOJI = {
    "sh600036": "🌻",   # 招商银行 (金葵花)
    "sz000001": "🛡️",   # 平安银行 (平安盾牌)
    "sh601012": "☀️",   # 隆基绿能 (太阳能光伏)
    "sh000001": "📈",   # 上证指数
    "sh510050": "🏛️"    # 上证50ETF
}

def format_emoji_alert(
    symbol: str,
    signal_type: str,           # 'BUY' | 'SELL'
    price: float,
    signal_time: str = "",
    plan: Optional[Dict[str, Any]] = None,
    strategy_key: str = "boll_reversion"
) -> str:
    """
    严格生成极简无文字的 Emoji 暗号：
    - 标的: 🌻(招行) / 🛡️(平安)
    - 动作: 🟢(买入进场) / 🔴(卖出离场)
    - 属性: ⚡(强信号/黄金时段) / 💰(获利止盈) / 🛑(破位止损)
    - 目标: 🎯[止盈价] 🛑[止损价]
    - 链接: 🔗[直达后台，附带具体标的与策略参数]
    """
    sym_icon = SYMBOL_EMOJI.get(symbol, "📌")
    is_buy = signal_type.upper() == "BUY"
    action_icon = "🟢" if is_buy else "🔴"
    
    plan = plan or {}
    tp_price = plan.get("take_profit_price", round(price * (1.015 if is_buy else 0.985), 2))
    sl_price = plan.get("stop_loss_price", round(price * (0.992 if is_buy else 1.008), 2))
    
    # 状态符号
    status_icon = "⚡" if is_buy else "💰"
    time_short = signal_time[-8:-3] if len(signal_time) >= 5 else ""

    # 携带精准直达参数的直达URL
    target_url = f"{DASHBOARD_URL}?symbol={symbol}&strategy={strategy_key}"

    # 手机锁屏仅展示一行隐蔽代码：例如 "🌻 🟢 ⚡ 42.94 14:50"
    # 第二行是极简符号指标：🎯43.50 🛑42.60 🔗http://117.72.29.130/?symbol=sh600036&strategy=boll_reversion
    lines = [
        f"{sym_icon} {action_icon} {status_icon}  {price:.2f}  {time_short}",
        f"🎯 {tp_price:.2f}  🛑 {sl_price:.2f}  🔗 {target_url}"
    ]
    return "\n".join(lines)

def send_feishu_emoji_text(text: str, webhook_url: str = DEFAULT_FEISHU_WEBHOOK) -> bool:
    """以纯文本形式发送，确保手机锁屏通知横幅绝无任何敏感中文"""
    if not webhook_url:
        return False
    try:
        body = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        resp = requests.post(webhook_url, json=body, timeout=5)
        if resp.status_code == 200 and resp.json().get("code") == 0:
            return True
        logger.error(f"[Notifier] 飞书推送失败: {resp.text}")
    except Exception as e:
        logger.error(f"[Notifier] 飞书网络异常: {e}")
    return False

def send_signal_alert(
    symbol: str,
    stock_name: str,
    signal_type: str,
    price: float,
    signal_time: str,
    strategy_name: str = "",
    reason: str = "",
    plan: Optional[Dict[str, Any]] = None,
    webhook_url: str = DEFAULT_FEISHU_WEBHOOK
) -> bool:
    """统一向飞书发送 Emoji 隐蔽通知"""
    emoji_text = format_emoji_alert(symbol, signal_type, price, signal_time, plan, strategy_key=strategy_name or "boll_reversion")
    return send_feishu_emoji_text(emoji_text, webhook_url=webhook_url)

if __name__ == "__main__":
    # 本地测试招行买点与平安卖点
    t1 = format_emoji_alert("sh600036", "BUY", 42.94, "2026-10-30 09:35:00")
    print("--- 招行测试暗号 ---")
    print(t1)
    send_feishu_emoji_text(t1)
    
    t2 = format_emoji_alert("sz000001", "SELL", 11.54, "2026-10-30 09:40:00")
    print("--- 平安测试暗号 ---")
    print(t2)
    send_feishu_emoji_text(t2)
