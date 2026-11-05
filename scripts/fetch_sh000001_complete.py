import os
import sys
import sqlite3
import pandas as pd
import requests
import json
import akshare as ak

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "stock.db")

def init_kline_daily_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kline_daily (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        amount REAL NOT NULL,
        turnover REAL DEFAULT 0.0,
        pct_change REAL DEFAULT 0.0,
        PRIMARY KEY (symbol, date)
    )
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_kline_daily_sym_date
    ON kline_daily (symbol, date ASC)
    """)
    conn.commit()

def fetch_sh000001_daily():
    print("[1/4] 抓取上证指数 (000001) 自1990年至今全部历史日线数据...")
    df = ak.index_zh_a_hist(symbol="000001", period="daily", start_date="19901219", end_date="20261105")
    print(f"[*] 成功获取 {len(df)} 个交易日历史数据 (从 {df['日期'].iloc[0]} 至 {df['日期'].iloc[-1]})")
    return df

def fetch_sh000001_5m():
    print("[2/4] 从新浪财经获取上证指数全量 5分钟高频 K 线...")
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=5&ma=5&datalen=10000"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    raw_data = resp.json()
    print(f"[*] 成功获取 {len(raw_data)} 根 5分钟K线 (从 {raw_data[0]['day']} 至 {raw_data[-1]['day']})")
    return raw_data

def save_to_db(df_daily, raw_5m):
    print("[3/4] 数据写入本地数据库 data/stock.db ...")
    conn = sqlite3.connect(DB_PATH)
    init_kline_daily_table(conn)
    cursor = conn.cursor()
    
    # 1. 写入 kline_daily
    daily_records = []
    for _, row in df_daily.iterrows():
        daily_records.append((
            'sh000001',
            str(row['日期']),
            float(row['开盘']),
            float(row['最高']),
            float(row['最低']),
            float(row['收盘']),
            float(row['成交量']),
            float(row['成交额']),
            float(row.get('换手率', 0.0) or 0.0),
            float(row.get('涨跌幅', 0.0) or 0.0)
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
    """, daily_records)
    print(f"[✓] 成功写入 kline_daily: {len(daily_records)} 条上证指数历史日线记录！")
    
    # 2. 写入 kline_5m
    m5_records = []
    for item in raw_5m:
        m5_records.append((
            'sh000001',
            item['day'],
            float(item['open']),
            float(item['high']),
            float(item['low']),
            float(item['close']),
            float(item['volume']),
            float(item.get('amount', 0.0) or 0.0)
        ))
        
    cursor.executemany("""
    INSERT INTO kline_5m (symbol, datetime, open, high, low, close, volume, amount)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol, datetime) DO UPDATE SET
        open=excluded.open,
        high=excluded.high,
        low=excluded.low,
        close=excluded.close,
        volume=excluded.volume,
        amount=excluded.amount
    """, m5_records)
    print(f"[✓] 成功写入 kline_5m: {len(m5_records)} 根上证指数 5分钟K线！")
    
    # 3. 更新 stocks 表中的 last_sync_time
    cursor.execute("""
    UPDATE stocks SET last_sync_time = datetime('now', 'localtime') WHERE symbol = 'sh000001'
    """)
    
    conn.commit()
    conn.close()

def export_csv(df_daily, raw_5m):
    print("[4/4] 导出标准归档 CSV 文件...")
    # 导出日线
    daily_csv = os.path.join(BASE_DIR, "data", "sh000001_daily_1990_2026.csv")
    df_daily.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    print(f"[✓] 日线全量数据已保存至: {daily_csv}")
    
    # 导出 5m
    df_5m = pd.DataFrame(raw_5m)
    m5_csv = os.path.join(BASE_DIR, "data", "sh000001_5m_full.csv")
    df_5m.to_csv(m5_csv, index=False, encoding="utf-8-sig")
    print(f"[✓] 5分钟高频数据已保存至: {m5_csv}")

def main():
    df_daily = fetch_sh000001_daily()
    raw_5m = fetch_sh000001_5m()
    save_to_db(df_daily, raw_5m)
    export_csv(df_daily, raw_5m)
    print("\n[SUCCESS] 上证指数全量历史数据抓取、清洗、入库与导出完成！")

if __name__ == "__main__":
    main()
