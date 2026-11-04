import os
import sys
import time
import baostock as bs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.database import upsert_klines, get_connection

QUARTERS = [
    # 2022
    ("2022-01-01", "2022-03-31"),
    ("2022-04-01", "2022-06-30"),
    ("2022-07-01", "2022-09-30"),
    ("2022-10-01", "2022-12-31"),
    # 2023
    ("2023-01-01", "2023-03-31"),
    ("2023-04-01", "2023-06-30"),
    ("2023-07-01", "2023-09-30"),
    ("2023-10-01", "2023-12-31"),
    # 2024
    ("2024-01-01", "2024-03-31"),
    ("2024-04-01", "2024-06-30"),
    ("2024-07-01", "2024-09-30"),
    ("2024-10-01", "2024-12-31"),
    # 2025
    ("2025-01-01", "2025-03-31"),
    ("2025-04-01", "2025-06-30"),
    ("2025-07-01", "2025-09-30"),
    ("2025-10-01", "2025-12-31"),
]

def fetch_quarter(start_date: str, end_date: str):
    print(f"[*] 抓取招商银行 5分钟线 [{start_date} ~ {end_date}]...", flush=True)
    rs = bs.query_history_k_data_plus(
        "sh.600036",
        "date,time,open,high,low,close,volume,amount",
        start_date=start_date,
        end_date=end_date,
        frequency="5",
        adjustflag="3"  # 不复权
    )
    if rs.error_code != "0":
        print(f"[!] 抓取失败 ({start_date}~{end_date}): {rs.error_msg}", flush=True)
        return []

    records = []
    while rs.next():
        row = rs.get_row_data()
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
        except Exception:
            continue
    return records

def main():
    t0 = time.time()
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[!] 登录 Baostock 失败: {lg.error_msg}")
        return

    total_records = 0
    try:
        for idx, (s, e) in enumerate(QUARTERS, 1):
            records = fetch_quarter(s, e)
            if records:
                upsert_klines("sh600036", records)
                total_records += len(records)
                print(f"[{idx}/{len(QUARTERS)}] 入库 {len(records)} 根K线 (累计: {total_records}) | 第一根: {records[0]['datetime']} | 最后一根: {records[-1]['datetime']}", flush=True)
            else:
                print(f"[{idx}/{len(QUARTERS)}] 无数据或跳过: {s}~{e}", flush=True)
            time.sleep(0.3)
    finally:
        bs.logout()

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT count(*), min(datetime), max(datetime) FROM kline_5m WHERE symbol = 'sh600036'")
    row = c.fetchone()
    conn.close()

    print("\n=== 招商银行 历史数据同步完成 ===")
    print(f"本次抓取累计入库: {total_records} 根K线 | 耗时: {time.time()-t0:.1f} 秒")
    print(f"数据库中 sh600036 当前全量数据: 总计 {row[0]} 根 | 时间跨度: {row[1]} ~ {row[2]}")

if __name__ == "__main__":
    main()
