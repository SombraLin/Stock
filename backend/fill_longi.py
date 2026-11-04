import os
import sys
import baostock as bs
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.database import get_connection, upsert_klines, get_data_stats
from backend.fetcher import fetch_latest_5m_klines

def main():
    print("[1/4] 注册隆基绿能 (sh601012) 到 stocks 及 push_configs 数据表...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO stocks (symbol, name, market) VALUES ('sh601012', '隆基绿能', 'SH')")
    cursor.execute("""
    INSERT OR IGNORE INTO stock_push_configs (symbol, enabled, signal_filter, updated_at)
    VALUES ('sh601012', 1, 'ALL', datetime('now', 'localtime'))
    """)
    conn.commit()
    conn.close()

    print("[2/4] 从 Baostock 抓取 2026 年初到 2026-09-02 的 5分钟历史数据...")
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[!] 登录 Baostock 失败: {lg.error_msg}")
        return

    records_bs = []
    try:
        rs = bs.query_history_k_data_plus(
            "sh.601012",
            "date,time,open,high,low,close,volume,amount",
            start_date="2026-01-01",
            end_date="2026-09-02",
            frequency="5",
            adjustflag="3"
        )
        while rs.next():
            row = rs.get_row_data()
            t_raw = row[1]
            dt_str = f"{t_raw[0:4]}-{t_raw[4:6]}-{t_raw[6:8]} {t_raw[8:10]}:{t_raw[10:12]}:00"
            try:
                records_bs.append({
                    "datetime": dt_str,
                    "open": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "close": float(row[5]),
                    "volume": float(row[6]),
                    "amount": float(row[7])
                })
            except Exception:
                continue
    finally:
        bs.logout()

    print(f"[*] Baostock 抓取完成，共 {len(records_bs)} 根K线，正在入库...")
    if records_bs:
        cnt_bs = upsert_klines("sh601012", records_bs)
        print(f"[✓] Baostock 成功写入/合并 {cnt_bs} 根数据！")

    print("[3/4] 从新浪财经获取 2026-09-02 至今日最新的 5分钟K线...")
    records_sina = fetch_latest_5m_klines("sh601012", datalen=1920)
    print(f"[*] 新浪财经获取完成，共 {len(records_sina)} 根K线，正在入库...")
    if records_sina:
        cnt_sina = upsert_klines("sh601012", records_sina)
        print(f"[✓] 新浪财经成功写入/合并 {cnt_sina} 根数据！")

    print("[4/4] 验证数据库状态...")
    stats = get_data_stats()
    for sym, item in stats.items():
        print(f"标的: {sym} ({item.get('name')}) | 总K线数: {item.get('bar_count')} 根 | 时间范围: {item.get('first_time')} ~ {item.get('latest_time')}")

if __name__ == "__main__":
    main()
