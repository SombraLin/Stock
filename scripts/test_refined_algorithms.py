import sqlite3
import pandas as pd
import numpy as np

# Load data prepared by previous script
from test_low_freq_cmb_algorithm import load_data, calculate_5m_indicators

df = load_data()
df = calculate_5m_indicators(df)

# Let's test different parameter sets:
# 1. Swing Trend: Buy when Daily Trend Bullish (CMB > Daily MA60) + 5M Oversold (RSI<35 & Low <= Boll_low)
#    Exit: Reach 5M Boll_up, OR Daily MA20 reached, OR TP 2.5%, SL 1.5%, hold up to 5 days (240 bars)
# 2. Reversion Mean: Buy when Daily RSI < 35 (extreme bottom)
# 3. Macro Confluence: Both Index > MA60 and CMB > MA60 (Dual Bull)

def test_strategy(df, name, entry_fn, tp_pct, sl_pct, max_bars, fee_rate=0.0008, cool_down=24):
    cash = 100000.0
    shares = 0
    in_pos = False
    entry_price = 0.0
    entry_idx = 0
    trades = []
    daily_equity = {}
    last_exit_idx = -999
    
    n = len(df)
    for i in range(60, n):
        row = df.iloc[i]
        cur_date = row['date']
        cur_close = row['close']
        high = row['high']
        low = row['low']
        
        if in_pos:
            hold_bars = i - entry_idx
            target_tp = entry_price * (1 + tp_pct)
            target_sl = entry_price * (1 - sl_pct)
            
            exit_trade = False
            exit_price = 0.0
            reason = ''
            
            # Dynamic Exit: Hit TP or hit Boll Upper band after profit
            if high >= target_tp:
                exit_trade = True
                exit_price = target_tp
                reason = 'TP'
            elif low <= target_sl:
                exit_trade = True
                exit_price = target_sl
                reason = 'SL'
            elif cur_close >= row['boll_up'] and cur_close > entry_price * 1.01:
                # 动态止盈：触及布林上轨且有至少1%浮盈
                exit_trade = True
                exit_price = cur_close
                reason = 'BOLL_UP_TP'
            elif hold_bars >= max_bars:
                exit_trade = True
                exit_price = cur_close
                reason = 'TIMEOUT'
                
            if exit_trade:
                gross = shares * exit_price
                fee = gross * fee_rate
                cash += (gross - fee)
                pnl = (gross - fee) - (shares * entry_price)
                ret = pnl / (shares * entry_price) * 100
                trades.append({
                    'entry_time': df.iloc[entry_idx]['datetime'],
                    'exit_time': row['datetime'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return_pct': ret,
                    'reason': reason,
                    'year': cur_date.year
                })
                in_pos = False
                shares = 0
                last_exit_idx = i
                
        if not in_pos and (i - last_exit_idx) >= cool_down:
            if entry_fn(row, df.iloc[i-1]):
                entry_price = cur_close
                entry_idx = i
                max_shares = int(cash // (entry_price * 100)) * 100
                if max_shares >= 100:
                    cash -= max_shares * entry_price
                    shares = max_shares
                    in_pos = True
                    
        daily_equity[cur_date] = cash + (shares * cur_close if in_pos else 0)
        
    return daily_equity, trades

# Candidate 1: 严格顺势波段（招行日线 > MA60 + 大盘 > MA60，双牛共振 + 5M下轨买）
def entry_dual_bull(row, prev):
    cmb_bull = pd.notna(row['cmb_d_ma60']) and (row['close'] >= row['cmb_d_ma60'])
    idx_bull = row['idx_bull'] == True
    dip = (row['low'] <= row['boll_low']) and (row['rsi14'] < 36)
    return cmb_bull and idx_bull and dip

# Candidate 2: 招行单边日线过滤（招行日线 > MA60，无论大盘如何，只做招行自己的多头回调）
def entry_cmb_bull_only(row, prev):
    cmb_bull = pd.notna(row['cmb_d_ma60']) and (row['close'] >= row['cmb_d_ma60'])
    dip = (row['low'] <= row['boll_low']) and (row['rsi14'] < 36)
    return cmb_bull and dip

# Candidate 3: 招商银行专属“大波段均值回归”（招行偏离日线MA20超过-2%，且5M出现锤子线或布林下轨拐头）
def entry_deep_value_reversion(row, prev):
    # 招行距离日线MA20有明显折价（超跌价值区）
    val_dip = pd.notna(row['cmb_d_ma20']) and (row['close'] < row['cmb_d_ma20'] * 0.985)
    # 5M 探底反弹 (前一根触碰下轨，当前根收红且站稳下轨上方)
    turn_up = (prev['low'] <= prev['boll_low']) and (row['close'] > row['open']) and (row['rsi14'] < 38)
    # 大盘不能出现暴跌熔断 (当日大盘非跌幅超2%)
    return val_dip and turn_up

candidates = [
    ("1. 双牛共振波段 (CMB>MA60 & Index>MA60, TP 2.5%, SL 1.5%)", entry_dual_bull, 0.025, 0.015, 144, 24),
    ("2. 招行多头波段 (CMB>MA60, TP 2.5%, SL 1.5%)", entry_cmb_bull_only, 0.025, 0.015, 144, 24),
    ("3. 深度价值均值回归 (日线折价1.5% + 5M拐头, TP 2.5%, SL 1.5%)", entry_deep_value_reversion, 0.025, 0.015, 144, 24),
    ("4. 招行多头波段 + 宽幅止盈 (CMB>MA60, TP 3.5%, SL 1.8%, 最长5天)", entry_cmb_bull_only, 0.035, 0.018, 240, 36),
]

years = [2022, 2023, 2024, 2025, 2026]

print(f"{'策略方案':<45} | {'总笔数':<6} | {'胜率':<6} | {'单笔净益':<8} | {'2022结余':<10} | {'2023结余':<10} | {'2024结余':<10} | {'2025结余':<10} | {'2026结余':<10}")
print("-" * 125)

for title, fn, tp, sl, hold, cd in candidates:
    eq, tr = test_strategy(df, title, fn, tp, sl, hold, fee_rate=0.0008, cool_down=cd)
    tr_df = pd.DataFrame(tr)
    cnt = len(tr)
    wr = (tr_df['return_pct'] > 0).mean() * 100 if cnt > 0 else 0
    avg_r = tr_df['return_pct'].mean() if cnt > 0 else 0
    
    bals = {}
    for y in years:
        dy = [d for d in eq.keys() if d.year == y]
        bals[y] = eq[max(dy)] if dy else 100000.0
        
    print(f"{title:<45} | {cnt:>5}笔 | {wr:>5.1f}% | {avg_r:>7.2f}% | {bals[2022]:>9.0f}元 | {bals[2023]:>9.0f}元 | {bals[2024]:>9.0f}元 | {bals[2025]:>9.0f}元 | {bals[2026]:>9.0f}元")
