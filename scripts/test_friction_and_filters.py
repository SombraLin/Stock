import sqlite3
import pandas as pd
import numpy as np

def load_and_prep():
    conn = sqlite3.connect('data/stock.db')
    df = pd.read_sql("SELECT datetime, open, high, low, close, volume, amount FROM kline_5m WHERE symbol = 'sh600036' ORDER BY datetime ASC", conn)
    conn.close()
    df['datetime'] = pd.to_datetime(df['datetime'])
    close = df['close']
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    df['ma20'] = ma20
    df['boll_lower'] = ma20 - 2 * std20
    df['boll_upper'] = ma20 + 2 * std20
    
    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi14'] = 100 - (100 / (1 + rs))
    
    # Daily MA60 trend filter: compute daily close and daily MA60
    df['date'] = df['datetime'].dt.date
    daily = df.groupby('date')['close'].last().reset_index()
    daily['daily_ma60'] = daily['close'].rolling(60).mean()
    daily['trend_bull'] = daily['close'] > daily['daily_ma60']
    
    df = df.merge(daily[['date', 'trend_bull']], on='date', how='left')
    return df

def simulate(df, use_trend_filter=False, tp=0.012, sl=0.008, fee_rate=0.0008, max_hold=24):
    cash = 100000.0
    shares = 0
    in_pos = False
    entry_price = 0.0
    entry_idx = 0
    trades = 0
    
    daily_balances = {}
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        cur_date = row['datetime'].date()
        cur_close = row['close']
        
        if in_pos:
            hold_bars = i - entry_idx
            high = row['high']
            low = row['low']
            target_tp = entry_price * (1 + tp)
            target_sl = entry_price * (1 - sl)
            
            exit_trade = False
            exit_price = 0.0
            
            if high >= target_tp:
                exit_trade = True
                exit_price = target_tp
            elif low <= target_sl:
                exit_trade = True
                exit_price = target_sl
            elif hold_bars >= max_hold:
                exit_trade = True
                exit_price = cur_close
                
            if exit_trade:
                gross = shares * exit_price
                fee = gross * fee_rate
                cash += (gross - fee)
                in_pos = False
                shares = 0
                trades += 1
                
        if not in_pos:
            # Check signal
            is_sig = (row['low'] <= row['boll_lower']) and (row['rsi14'] < 40)
            if use_trend_filter:
                is_sig = is_sig and (row['trend_bull'] == True)
                
            if is_sig:
                entry_price = cur_close
                entry_idx = i
                max_shares = int(cash // (entry_price * 100)) * 100
                if max_shares >= 100:
                    cash -= max_shares * entry_price
                    shares = max_shares
                    in_pos = True
                    
        daily_balances[cur_date] = cash + (shares * cur_close if in_pos else 0)
        
    return daily_balances, trades

df = load_and_prep()

print("===== 对比分析：费率与趋势过滤对 10 万本金最终结余的决定性影响 =====")
years = [2022, 2023, 2024, 2025, 2026]

scenarios = [
    ("1. 原始布林策略 (理论无摩擦 0%)", False, 0.0, 0.012, 0.008, 24),
    ("2. 原始布林策略 (股票实盘印花税+佣金 0.08%)", False, 0.0008, 0.012, 0.008, 24),
    ("3. 原始布林策略 (ETF低费率场内 0.01%)", False, 0.0001, 0.012, 0.008, 24),
    ("4. 增加日线趋势过滤 MA60 (股票实盘 0.08%)", True, 0.0008, 0.012, 0.008, 24),
    ("5. 增加日线趋势过滤 + 扩大盈亏空间 (TP 2.5%, SL 1.5%, 费率0.08%)", True, 0.0008, 0.025, 0.015, 48),
]

for name, filter_on, fee, tp, sl, hold in scenarios:
    bals, trades = simulate(df, use_trend_filter=filter_on, tp=tp, sl=sl, fee_rate=fee, max_hold=hold)
    print(f"\n【{name}】 (5年总交易: {trades} 笔)")
    last_b = 100000.0
    for y in years:
        dates_y = [d for d in bals.keys() if d.year == y]
        if dates_y:
            b = bals[max(dates_y)]
            ret = (b - last_b) / last_b * 100
            print(f"  {y}年结余: {b:>10.2f} 元 (当年收益: {ret:>6.2f}%)")
            last_b = b
