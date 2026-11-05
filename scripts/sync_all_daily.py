import os
import sys
import sqlite3
import pandas as pd
import akshare as ak

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "stock.db")

SYMBOLS = [
    ("sh600036", "600036", "stock"),
    ("sz000001", "000001", "stock"),
    ("sh601012", "601012", "stock"),
    ("sh510050", "510050", "fund"),
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for full_sym, code, s_type in SYMBOLS:
        print(f"[*] 正在抓取 {full_sym} 全量日线历史...", flush=True)
        try:
            if s_type == "stock":
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="19900101", end_date="20261105", adjust="")
            else:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date="19900101", end_date="20261105", adjust="")
            
            records = []
            for _, r in df.iterrows():
                d_str = str(r['日期'])
                records.append((
                    full_sym,
                    d_str,
                    float(r['开盘']),
                    float(r['最高']),
                    float(r['最低']),
                    float(r['收盘']),
                    float(r['成交量']),
                    float(r['成交额']),
                    float(r.get('换手率', 0.0) or 0.0),
                    float(r.get('涨跌幅', 0.0) or 0.0)
                ))
                
            cursor.executemany("""
            INSERT INTO kline_daily (symbol, date, open, high, low, close, volume, amount, turnover, pct_change)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                amount=excluded.amount,
                turnover=excluded.turnover,
                pct_change=excluded.pct_change
            """, records)
            conn.commit()
            print(f"[✓] {full_sym} 成功写入 {len(records)} 条日线记录 (从 {records[0][1]} 至 {records[-1][1]})", flush=True)
        except Exception as e:
            print(f"[!] 抓取 {full_sym} 失败: {e}", flush=True)
            
    conn.close()
    print("[SUCCESS] 全标的完整日线历史库构建完成！")

if __name__ == "__main__":
    main()
