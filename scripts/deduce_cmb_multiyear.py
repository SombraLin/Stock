import os
import sys
import json
import sqlite3
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.strategy import generate_signals, STRATEGY_META

def run_deduction():
    conn = sqlite3.connect("data/stock.db")
    df = pd.read_sql("SELECT datetime, open, high, low, close, volume, amount FROM kline_5m WHERE symbol='sh600036' ORDER BY datetime ASC", conn)
    conn.close()

    if df.empty:
        print("[!] 没有在数据库中找到 sh600036 的 K 线数据！")
        return

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["year"] = df["datetime"].dt.year
    df["date"] = df["datetime"].dt.date.astype(str)

    years = [int(y) for y in sorted(df["year"].unique())]
    print(f"[*] 成功加载招商银行 5分钟K线，共 {len(df)} 根，时间跨度: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
    print(f"[*] 覆盖年份: {years}")

    # 1. 每年宏观盘面量化画像
    market_overview = {}
    for y in years:
        sub = df[df["year"] == y]
        daily = sub.groupby("date").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
            volume=("volume", "sum"), amount=("amount", "sum")
        ).reset_index()

        y_open = daily.iloc[0]["open"]
        y_close = daily.iloc[-1]["close"]
        y_high = daily["high"].max()
        y_low = daily["low"].min()
        y_ret = (y_close - y_open) / y_open * 100

        # 计算日度最大回撤
        cummax = daily["close"].cummax()
        drawdown = (daily["close"] - cummax) / cummax * 100
        mdd = drawdown.min()

        market_overview[str(y)] = {
            "trading_days": int(len(daily)),
            "bars": int(len(sub)),
            "open": round(float(y_open), 2),
            "close": round(float(y_close), 2),
            "high": round(float(y_high), 2),
            "low": round(float(y_low), 2),
            "return_pct": round(float(y_ret), 2),
            "max_drawdown_pct": round(float(mdd), 2),
            "avg_daily_amount_yi": round(float(daily["amount"].mean() / 1e8), 2)
        }

    # 2. 各策略分年度及全周期回测推演
    strategies = ["boll_reversion", "hammer_reversal", "vol_breakout", "afternoon_confluence", "combined"]
    strategy_results = {}

    for strat in strategies:
        strategy_results[strat] = {"by_year": {}, "overall": {}}
        
        # 分年度运行
        for y in years:
            sub = df[df["year"] == y].copy().reset_index(drop=True)
            if len(sub) < 100:
                continue
            res = generate_signals(sub, index_df=None, strategy_name=strat)
            m = res["metrics"]
            strategy_results[strat]["by_year"][str(y)] = {
                "signals": int(len(res["signals"])),
                "buy_count": int(m.get("buy_count", 0)),
                "sell_count": int(m.get("sell_count", 0)),
                "win_rate_30m": round(float(m.get("win_rate_30m", 0)), 1),
                "avg_return_30m": round(float(m.get("avg_return_30m", 0)), 3),
                "win_rate_60m": round(float(m.get("win_rate_60m", 0)), 1),
                "avg_return_60m": round(float(m.get("avg_return_60m", 0)), 3),
                "tp_sl_win_rate": round(float(m.get("tp_sl_win_rate", 0)), 1),
                "tp_hit": int(m.get("tp_hit_count", 0)),
                "sl_hit": int(m.get("sl_hit_count", 0)),
                "timeout": int(m.get("timeout_count", 0)),
                "expectancy": round(float(m.get("tp_sl_avg_return", 0)), 3),
                "profit_loss_ratio": round(float(m.get("profit_loss_ratio", 0)), 2)
            }

        # 全量跨年度运行 (连续状态推演)
        full_res = generate_signals(df.copy().reset_index(drop=True), index_df=None, strategy_name=strat)
        fm = full_res["metrics"]
        strategy_results[strat]["overall"] = {
            "total_bars": int(len(df)),
            "signals": int(len(full_res["signals"])),
            "buy_count": int(fm.get("buy_count", 0)),
            "sell_count": int(fm.get("sell_count", 0)),
            "win_rate_30m": round(float(fm.get("win_rate_30m", 0)), 1),
            "avg_return_30m": round(float(fm.get("avg_return_30m", 0)), 3),
            "win_rate_60m": round(float(fm.get("win_rate_60m", 0)), 1),
            "avg_return_60m": round(float(fm.get("avg_return_60m", 0)), 3),
            "tp_sl_win_rate": round(float(fm.get("tp_sl_win_rate", 0)), 1),
            "tp_hit": int(fm.get("tp_hit_count", 0)),
            "sl_hit": int(fm.get("sl_hit_count", 0)),
            "timeout": int(fm.get("timeout_count", 0)),
            "expectancy": round(float(fm.get("tp_sl_avg_return", 0)), 3),
            "profit_loss_ratio": round(float(fm.get("profit_loss_ratio", 0)), 2)
        }

    # 3. 输出推演成果至报告文件
    report = {
        "market_overview": market_overview,
        "strategy_results": strategy_results
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/cmb_multiyear_deduction_2022_2026.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n[✓] 算法推演完成！推演结果已持久化至 reports/cmb_multiyear_deduction_2022_2026.json")
    return report

if __name__ == "__main__":
    run_deduction()
