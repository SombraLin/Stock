import sqlite3
import pandas as pd
import numpy as np

def run():
    conn = sqlite3.connect('data/stock.db')
    df = pd.read_sql("SELECT datetime, open, high, low, close, volume FROM kline_5m WHERE symbol = 'sh600036' ORDER BY datetime ASC", conn)
    daily = pd.read_sql("SELECT symbol, date, close FROM kline_daily WHERE symbol IN ('sh600036', 'sh000001') ORDER BY date ASC", conn)
    conn.close()
    
    df['datetime'] = pd.to_datetime(df['datetime'])
    df['date'] = df['datetime'].dt.strftime('%Y-%m-%d')
    
    # 5m indicators
    close = df['close']
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    df['ma20'] = ma20
    df['boll_lower'] = ma20 - 2 * std20
    df['boll_upper'] = ma20 + 2 * std20
    
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi14'] = 100 - (100 / (1 + rs))
    
    # Daily indicators
    cmb_d = daily[daily['symbol'] == 'sh600036'].copy().set_index('date')
    cmb_d['cmb_ma60'] = cmb_d['close'].rolling(60).mean()
    cmb_d['cmb_bull'] = cmb_d['close'] > cmb_d['cmb_ma60']
    
    idx_d = daily[daily['symbol'] == 'sh000001'].copy().set_index('date')
    idx_d['idx_ma60'] = idx_d['close'].rolling(60).mean()
    idx_d['idx_ma20'] = idx_d['close'].rolling(20).mean()
    idx_d['idx_bull'] = idx_d['close'] > idx_d['idx_ma60']
    idx_d['idx_short_bull'] = idx_d['close'] > idx_d['idx_ma20']
    
    # Relative strength: cmb / idx
    merged_d = cmb_d[['close', 'cmb_bull']].join(idx_d[['close', 'idx_bull', 'idx_short_bull']], lsuffix='_cmb', rsuffix='_idx')
    merged_d['rs_ratio'] = merged_d['close_cmb'] / merged_d['close_idx']
    merged_d['rs_ma20'] = merged_d['rs_ratio'].rolling(20).mean()
    merged_d['rs_strong'] = merged_d['rs_ratio'] > merged_d['rs_ma20']
    
    # Shift daily by 1 day to strictly eliminate lookahead bias!
    merged_d_shifted = merged_d.shift(1).reset_index()
    
    df = df.merge(merged_d_shifted[['date', 'cmb_bull', 'idx_bull', 'idx_short_bull', 'rs_strong']], on='date', how='left')
    
    def simulate_filter(cond_name, cond_col, tp=0.025, sl=0.015, max_hold=48):
        cash = 100000.0
        shares = 0
        in_pos = False
        entry_price = 0.0
        entry_idx = 0
        trades = 0
        daily_bals = {}
        trade_log = []
        
        for i in range(20, len(df)):
            row = df.iloc[i]
            cur_date = row['date']
            cur_close = row['close']
            
            if in_pos:
                hold_bars = i - entry_idx
                target_tp = entry_price * (1 + tp)
                target_sl = entry_price * (1 - sl)
                
                exit_trade = False
                exit_price = 0.0
                
                if row['high'] >= target_tp:
                    exit_trade = True
                    exit_price = target_tp
                elif row['low'] <= target_sl:
                    exit_trade = True
                    exit_price = target_sl
                elif hold_bars >= max_hold:
                    exit_trade = True
                    exit_price = cur_close
                    
                if exit_trade:
                    gross = shares * exit_price
                    fee = gross * 0.0008
                    cash += (gross - fee)
                    pnl = (gross - fee) - (shares * entry_price)
                    ret = pnl / (shares * entry_price) * 100
                    trade_log.append(ret)
                    in_pos = False
                    shares = 0
                    trades += 1
                    
            if not in_pos:
                is_dip = (row['low'] <= row['boll_lower']) and (row['rsi14'] < 40)
                if cond_col is not None:
                    is_sig = is_dip and (row[cond_col] == True)
                else:
                    is_sig = is_dip
                    
                if is_sig:
                    entry_price = cur_close
                    entry_idx = i
                    max_shares = int(cash // (entry_price * 100)) * 100
                    if max_shares >= 100:
                        cash -= max_shares * entry_price
                        shares = max_shares
                        in_pos = True
                        
            daily_bals[cur_date] = cash + (shares * cur_close if in_pos else 0)
            
        years = ['2022', '2023', '2024', '2025', '2026']
        print(f"\n【{cond_name}】 (总交易: {trades} 笔 | 胜率: {(np.array(trade_log)>0).mean()*100:.1f}%)")
        last_b = 100000.0
        for y in years:
            dys = [d for d in daily_bals.keys() if d.startswith(y)]
            if dys:
                b = daily_bals[max(dys)]
                r = (b - last_b) / last_b * 100
                print(f"  {y}年结余: {b:>10.2f} 元 (当年净收益: {r:>6.2f}%)")
                last_b = b

    print("===== 实证测试：大盘因子与招行个股趋势对波段策略的收益决定 =====")
    
    # 方案 1: 无过滤基准
    simulate_filter("1. 无过滤原始策略 (TP 2.5%, SL 1.5%)", None)
    
    # 方案 2: 仅招行自身日线 MA60
    simulate_filter("2. 仅招行日线多头 (CMB > MA60)", "cmb_bull")
    
    # 方案 3: 仅大盘日线多头 (Index > MA60)
    simulate_filter("3. 仅大盘日线多头 (Index > MA60)", "idx_bull")
    
    # 方案 4: 招行相对强弱走强 (RS_ratio > RS_MA20)
    simulate_filter("4. 招行相对大盘走强 (Alpha相对强弱 RS > RS_MA20)", "rs_strong")
    
    # 方案 5: 组合过滤：招行趋势良好且大盘非瀑布下杀 (cmb_bull & (idx_short_bull | rs_strong))
    df['combo_bull'] = df['cmb_bull'] & (df['idx_short_bull'] | df['rs_strong'])
    simulate_filter("5. 智能共振过滤 (招行多头 + 大盘站上MA20或招行逆势抗跌)", "combo_bull")

if __name__ == '__main__':
    run()
