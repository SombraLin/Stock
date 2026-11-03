import os
import pandas as pd
from backend.database import init_db, upsert_klines, get_data_stats

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSV_MAPPINGS = [
    {
        "symbol": "sh600036",
        "name": "招商银行",
        "filepath": os.path.join(BASE_DIR, "招商银行_5分钟_近2月.csv")
    },
    {
        "symbol": "sh000001",
        "name": "上证指数",
        "filepath": os.path.join(BASE_DIR, "上证指数_5分钟_近2月.csv")
    }
]

def import_csvs():
    init_db()
    total_imported = 0
    
    for item in CSV_MAPPINGS:
        path = item["filepath"]
        symbol = item["symbol"]
        name = item["name"]
        
        if not os.path.exists(path):
            print(f"[Warning] CSV file not found: {path}")
            continue
            
        print(f"Reading CSV for {name} ({symbol}) from {path}...")
        df = pd.read_csv(path)
        
        # Expected columns: 时间,开盘,最高,最低,收盘,成交量,成交额
        records = []
        for _, row in df.iterrows():
            records.append({
                "datetime": str(row["时间"]).strip(),
                "open": float(row["开盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "close": float(row["收盘"]),
                "volume": float(row["成交量"]),
                "amount": float(row["成交额"])
            })
            
        upsert_klines(symbol, records)
        print(f"Successfully imported {len(records)} 5-minute bars for {name} ({symbol})")
        total_imported += len(records)
        
    print("\n=== Current Database Statistics ===")
    stats = get_data_stats()
    for sym, info in stats.items():
        print(f"Symbol: {sym} | Name: {info['name']} | Count: {info['bar_count']} | Range: {info['first_time']} -> {info['latest_time']}")

if __name__ == "__main__":
    import_csvs()
