import sqlite3
import gzip

LOCAL_DB = "data/stock.db"
OUTPUT_SQL = "data/remote_sync_sh000001.sql.gz"

conn = sqlite3.connect(LOCAL_DB)
cursor = conn.cursor()

lines = []
lines.append("BEGIN TRANSACTION;\n")

# 1. kline_daily schema
lines.append("""
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
);
CREATE INDEX IF NOT EXISTS idx_kline_daily_sym_date ON kline_daily (symbol, date ASC);
""")

# 2. kline_daily rows
cursor.execute("SELECT symbol, date, open, high, low, close, volume, amount, turnover, pct_change FROM kline_daily")
daily_rows = cursor.fetchall()
print(f"Exporting {len(daily_rows)} kline_daily rows...")
for r in daily_rows:
    lines.append(f"INSERT OR REPLACE INTO kline_daily (symbol, date, open, high, low, close, volume, amount, turnover, pct_change) VALUES ('{r[0]}', '{r[1]}', {r[2]}, {r[3]}, {r[4]}, {r[5]}, {r[6]}, {r[7]}, {r[8]}, {r[9]});\n")

# 3. sh000001 kline_5m rows
cursor.execute("SELECT symbol, datetime, open, high, low, close, volume, amount FROM kline_5m WHERE symbol = 'sh000001'")
m5_rows = cursor.fetchall()
print(f"Exporting {len(m5_rows)} sh000001 kline_5m rows...")
for r in m5_rows:
    lines.append(f"INSERT OR REPLACE INTO kline_5m (symbol, datetime, open, high, low, close, volume, amount) VALUES ('{r[0]}', '{r[1]}', {r[2]}, {r[3]}, {r[4]}, {r[5]}, {r[6]}, {r[7]});\n")

# 4. update last_sync_time
lines.append("UPDATE stocks SET last_sync_time = datetime('now', 'localtime') WHERE symbol = 'sh000001';\n")

lines.append("COMMIT;\n")

conn.close()

with gzip.open(OUTPUT_SQL, "wt", encoding="utf-8") as f:
    f.writelines(lines)

print(f"[✓] Successfully generated compressed sync file: {OUTPUT_SQL}")
