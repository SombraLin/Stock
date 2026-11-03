import re
import json
import requests
from typing import List, Dict, Any, Optional
from backend.database import upsert_klines

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn"
}

def fetch_latest_5m_klines(symbol: str, datalen: int = 120) -> List[Dict[str, Any]]:
    """
    从新浪财经抓取最新的 5 分钟 K 线数据
    symbol: 如 'sh600036' 或 'sh000001'
    """
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData?symbol={symbol}&scale=5&ma=no&datalen={datalen}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        text = resp.text
        
        # 匹配形如 var _=(...); 或 /*...*/\nvar _=(...);
        match = re.search(r'var\s+_=\((.*)\);?', text, re.DOTALL)
        if not match:
            # 尝试直接找 [...]
            bracket_match = re.search(r'(\[.*\])', text, re.DOTALL)
            if not bracket_match:
                print(f"[Fetcher] Unable to parse response for {symbol}")
                return []
            raw_json = bracket_match.group(1)
        else:
            raw_json = match.group(1)
            
        data = json.loads(raw_json)
        records = []
        for item in data:
            records.append({
                "datetime": item["day"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item["volume"]),
                "amount": float(item["amount"])
            })
        return records
    except Exception as e:
        print(f"[Fetcher Error] Failed to fetch 5m K-lines for {symbol}: {e}")
        return []

def sync_symbol_5m_data(symbol: str, datalen: int = 120) -> int:
    """抓取并入库最新5分钟K线"""
    records = fetch_latest_5m_klines(symbol, datalen=datalen)
    if records:
        affected = upsert_klines(symbol, records)
        return affected
    return 0

def fetch_realtime_quotes(symbols: List[str] = ["sh600036", "sh000001"]) -> Dict[str, Dict[str, Any]]:
    """
    抓取最新实时行情快照
    """
    symbols_str = ",".join(symbols)
    url = f"https://hq.sinajs.cn/list={symbols_str}"
    results = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        resp.encoding = "gbk"
        lines = resp.text.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line or "=" not in line:
                continue
            # e.g. var hq_str_sh600036="招商银行,42.500,42.130,42.600,42.850,42.090,42.600,42.620,50339716,2143348047.000,...,2026-10-29,11:30:00,00,";
            left, right = line.split("=", 1)
            sym_match = re.search(r'hq_str_([a-z0-9]+)', left)
            if not sym_match:
                continue
            symbol = sym_match.group(1)
            raw_content = right.strip('"; \r\n')
            parts = raw_content.split(",")
            
            if len(parts) >= 32:
                name = parts[0]
                open_p = float(parts[1]) if parts[1] else 0.0
                pre_close = float(parts[2]) if parts[2] else 0.0
                curr_p = float(parts[3]) if parts[3] else 0.0
                high_p = float(parts[4]) if parts[4] else 0.0
                low_p = float(parts[5]) if parts[5] else 0.0
                volume = float(parts[8]) if parts[8] else 0.0
                amount = float(parts[9]) if parts[9] else 0.0
                date_str = parts[30]
                time_str = parts[31]
                
                change = curr_p - pre_close if pre_close > 0 else 0.0
                change_pct = (change / pre_close * 100) if pre_close > 0 else 0.0
                
                results[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "price": curr_p,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "pre_close": pre_close,
                    "change": round(change, 3),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "amount": amount,
                    "datetime": f"{date_str} {time_str}"
                }
    except Exception as e:
        print(f"[Fetcher Error] Failed to fetch quotes: {e}")
        
    return results

if __name__ == "__main__":
    print("Testing 5m sync...")
    for sym in ["sh600036", "sh000001"]:
        cnt = sync_symbol_5m_data(sym, datalen=10)
        print(f"Synced {cnt} records for {sym}")
        
    print("Testing realtime quote:")
    quotes = fetch_realtime_quotes()
    for sym, q in quotes.items():
        print(sym, q)
