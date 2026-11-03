"""
利用 Baostock 免费公开源补全 2026 年过往 5 分钟 K 线数据
数据范围：2026-01-01 ~ 2026-08-26
标的：招商银行 (sh600036) 及 上证50ETF (sh510050)
"""

import os
import sys
import baostock as bs
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.database import get_connection, upsert_klines, get_data_stats

def fetch_and_fill_stock(bs_code: str, db_symbol: str, start_date: str = "2026-01-01", end_date: str = "2026-08-26"):
    print(f"[*] 开始通过 Baostock 抓取 {db_symbol} ({bs_code}) 历史5分钟数据 [{start_date} ~ {end_date}]...")
    
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,time,open,high,low,close,volume,amount",
        start_date=start_date,
        end_date=end_date,
        frequency="5",
        adjustflag="3"  # 不复权，与原csv及交易所原始行情严格一致
    )
    
    if rs.error_code != "0":
        print(f"[!] 抓取失败: {rs.error_msg}")
        return 0

    records = []
    while rs.next():
        row = rs.get_row_data()
        # row: ['2026-01-05', '20260105093500000', '42.4800', '42.7900', '42.3500', '42.7500', '8676870', '369326063.0000']
        t_raw = row[1]
        dt_str = f"{t_raw[0:4]}-{t_raw[4:6]}-{t_raw[6:8]} {t_raw[8:10]}:{t_raw[10:12]}:00"
        
        try:
            records.append({
                "datetime": dt_str,
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": float(row[6]),
                "amount": float(row[7])
            })
        except Exception as e:
            continue

    print(f"[*] 从 Baostock 成功获取 {len(records)} 根 5分钟K线，准备入库写入 SQLite...")
    if records:
        cnt = upsert_klines(db_symbol, records)
        print(f"[✓] 成功写入/合并 {cnt} 根数据到数据库！")
        return len(records)
    return 0

def main():
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[!] 登录 Baostock 失败: {lg.error_msg}")
        return

    conn = get_connection()
    conn.cursor().execute("INSERT OR IGNORE INTO stocks (symbol, name, market) VALUES ('sh510050', '上证50ETF', 'SH')")
    conn.commit()
    conn.close()

    try:
        # 1. 补全招商银行 2026 年初到 8 月底
        fetch_and_fill_stock("sh.600036", "sh600036", "2026-01-01", "2026-08-26")
        
        # 2. 补全上证50ETF（sh510050，作为大盘核心蓝筹高频对照）
        fetch_and_fill_stock("sh.510050", "sh510050", "2026-01-01", "2026-08-26")


        stats = get_data_stats()
        print("\n=== 本地数据库最新统计概览 ===")
        for sym, item in stats.items():
            print(f"标的: {sym} ({item.get('name')}) | 总K线数: {item.get('bar_count')} 根 | 时间范围: {item.get('first_time')} ~ {item.get('latest_time')}")

    finally:
        bs.logout()

if __name__ == "__main__":
    main()
