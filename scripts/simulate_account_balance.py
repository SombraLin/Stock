import sqlite3
import pandas as pd
import numpy as np

DB_PATH = 'data/stock.db'

def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT datetime, open, high, low, close, volume, amount
        FROM kline_5m
        WHERE symbol = 'sh600036'
        ORDER BY datetime ASC
    """, conn)
    conn.close()
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df

def calculate_indicators(df):
    close = df['close']
    # Boll
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    df['ma20'] = ma20
    df['boll_upper'] = ma20 + 2 * std20
    df['boll_lower'] = ma20 - 2 * std20
    
    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi14'] = 100 - (100 / (1 + rs))
    
    # Volume MA5
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    
    # Hammer
    body = (close - df['open']).abs()
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    df['is_hammer'] = (lower_shadow >= 2 * body) & (upper_shadow <= body * 0.5) & (body > 0)
    
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    return df

def generate_signals(df, strategy):
    n = len(df)
    signals = [] # list of (bar_index, 'BUY'/'SELL')
    
    for i in range(20, n):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        if strategy == 'boll_reversion':
            if row['low'] <= row['boll_lower'] and row['rsi14'] < 40:
                signals.append((i, 'BUY'))
            elif row['high'] >= row['boll_upper'] and row['rsi14'] > 60:
                signals.append((i, 'SELL'))
                
        elif strategy == 'hammer_reversal':
            if row['is_hammer'] and row['close'] < row['ma20'] and row['rsi14'] < 45:
                signals.append((i, 'BUY'))
                
        elif strategy == 'vol_breakout':
            if (row['close'] > row['ma20'] and prev['close'] <= prev['ma20'] and 
                row['volume'] > 2.0 * row['vol_ma5'] and row['vol_ma5'] > 0):
                signals.append((i, 'BUY'))
                
        elif strategy == 'afternoon_confluence':
            if ('13:30' <= row['time_str'] <= '14:30' and 
                row['close'] > row['open'] and 
                row['rsi14'] > 50 and 
                row['volume'] > 1.2 * row['vol_ma5']):
                signals.append((i, 'BUY'))
                
    return signals

def simulate_portfolio(df, signals, initial_capital=100000.0, round_trip_fee=0.0, max_hold_bars=24, tp=0.012, sl=0.008):
    """
    Simulate realistic single-position account trajectory.
    When a trade is active, ignore new signals until position is closed.
    """
    capital = initial_capital
    n = len(df)
    signal_dict = {idx: sig for idx, sig in signals if sig == 'BUY'} # only BUY for long cash account
    
    in_pos = False
    entry_price = 0.0
    entry_idx = 0
    shares = 0
    cash = initial_capital
    
    trade_history = []
    daily_balances = {} # date -> equity
    
    # We step through bar by bar
    for i in range(len(df)):
        cur_bar = df.iloc[i]
        cur_date = cur_bar['datetime'].date()
        cur_close = cur_bar['close']
        
        # If in position, check exit conditions
        if in_pos:
            hold_bars = i - entry_idx
            high = cur_bar['high']
            low = cur_bar['low']
            
            # Check TP
            target_tp = entry_price * (1 + tp)
            target_sl = entry_price * (1 - sl)
            
            exit_trade = False
            exit_price = 0.0
            reason = ''
            
            if high >= target_tp:
                exit_trade = True
                exit_price = target_tp
                reason = 'TP'
            elif low <= target_sl:
                exit_trade = True
                exit_price = target_sl
                reason = 'SL'
            elif hold_bars >= max_hold_bars:
                exit_trade = True
                exit_price = cur_close
                reason = 'TIMEOUT'
                
            if exit_trade:
                gross_revenue = shares * exit_price
                fee = gross_revenue * round_trip_fee
                net_revenue = gross_revenue - fee
                cash += net_revenue
                pnl = net_revenue - (shares * entry_price)
                ret = pnl / (shares * entry_price)
                
                trade_history.append({
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'entry_time': df.iloc[entry_idx]['datetime'],
                    'exit_time': cur_bar['datetime'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'shares': shares,
                    'pnl': pnl,
                    'return': ret,
                    'reason': reason,
                    'equity_after': cash
                })
                in_pos = False
                shares = 0
                entry_price = 0.0
                
        # If not in position, check buy signal
        if not in_pos and i in signal_dict:
            # Enter trade at current close
            entry_price = cur_close
            entry_idx = i
            # Allocate all cash (in lots of 100 shares)
            # Reserve money for buy fee
            max_shares = int(cash // (entry_price * 100)) * 100
            if max_shares >= 100:
                cost = max_shares * entry_price
                cash -= cost
                shares = max_shares
                in_pos = True
                
        # Record equity
        current_equity = cash + (shares * cur_close if in_pos else 0)
        daily_balances[cur_date] = current_equity
        
    return daily_balances, trade_history

def main():
    df = load_data()
    df = calculate_indicators(df)
    
    strategies = ['boll_reversion', 'hammer_reversal', 'vol_breakout', 'afternoon_confluence']
    
    years = [2022, 2023, 2024, 2025, 2026]
    
    # Benchmark Buy & Hold
    # Start: 100,000 cash at df.iloc[0]['close']
    p0 = df.iloc[0]['close']
    bnh_shares = int(100000 // (p0 * 100)) * 100
    bnh_cash = 100000 - bnh_shares * p0
    
    print("===== 招商银行 10万本金各策略实盘推演 =====")
    
    for strat in strategies:
        signals = generate_signals(df, strat)
        
        # Case 1: 0 fee (理论无摩擦)
        daily_bal_0, trades_0 = simulate_portfolio(df, signals, round_trip_fee=0.0)
        # Case 2: 0.08% round trip fee (万1.5佣金 + 万5印花税 = 0.08%)
        daily_bal_fee, trades_fee = simulate_portfolio(df, signals, round_trip_fee=0.0008)
        
        print(f"\n策略: {strat} (总交易次数: 无摩擦 {len(trades_0)}次)")
        print(f"{'年份':<6} | {'无摩擦结余(元)':<14} | {'无摩擦年收益':<10} | {'含费率结余(0.08%)':<16} | {'含费年收益':<10}")
        print("-" * 65)
        
        last_bal_0 = 100000.0
        last_bal_fee = 100000.0
        
        for y in years:
            # find last trading day in year
            dates_y = [d for d in daily_bal_0.keys() if d.year == y]
            if not dates_y:
                continue
            last_date = max(dates_y)
            bal_0 = daily_bal_0[last_date]
            bal_fee = daily_bal_fee[last_date]
            
            ret_0 = (bal_0 - last_bal_0) / last_bal_0 * 100
            ret_fee = (bal_fee - last_bal_fee) / last_bal_fee * 100
            
            print(f"{y:<6} | {bal_0:>12.2f} 元 | {ret_0:>8.2f}% | {bal_fee:>14.2f} 元 | {ret_fee:>8.2f}%")
            
            last_bal_0 = bal_0
            last_bal_fee = bal_fee

if __name__ == '__main__':
    main()
