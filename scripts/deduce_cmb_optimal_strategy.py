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
    cmb_d['ma20'] = cmb_d['close'].rolling(20).mean()
    cmb_d['ma60'] = cmb_d['close'].rolling(60).mean()
    cmb_d['ma60_slope'] = (cmb_d['ma60'] - cmb_d['ma60'].shift(5)) / cmb_d['ma60'].shift(5)
    cmb_d['gold_cross'] = cmb_d['ma20'] > cmb_d['ma60']
    cmb_d['strong_bull'] = (cmb_d['close'] > cmb_d['ma60']) & (cmb_d['ma60_slope'] >= 0)

    idx_d = daily[daily['symbol'] == 'sh000001'].copy().set_index('date')
    idx_d['idx_ma20'] = idx_d['close'].rolling(20).mean()
    idx_d['idx_ma60'] = idx_d['close'].rolling(60).mean()

    merged_d = cmb_d.join(idx_d[['close', 'idx_ma20', 'idx_ma60']], lsuffix='_cmb', rsuffix='_idx')
    merged_d['rs_ratio'] = merged_d['close_cmb'] / merged_d['close_idx']
    merged_d['rs_ma20'] = merged_d['rs_ratio'].rolling(20).mean()
    merged_d['rs_strong'] = merged_d['rs_ratio'] > merged_d['rs_ma20']
    
    # Combined conditions:
    # C1: Strong bull: close > ma60 & slope >= 0
    merged_d['c1_strong_bull'] = merged_d['strong_bull']
    # C2: Gold cross: ma20 > ma60
    merged_d['c2_gold_cross'] = merged_d['gold_cross']
    # C3: Trend + RS: (close > ma60) & rs_strong
    merged_d['c3_trend_rs'] = (merged_d['close_cmb'] > merged_d['ma60']) & merged_d['rs_strong']
    # C4: Multi-regime confluence: gold_cross & rs_strong
    merged_d['c4_confluence'] = merged_d['gold_cross'] & merged_d['rs_strong']
    # C5: Defensive regime: (strong_bull | (gold_cross & rs_strong))
    merged_d['c5_regime'] = merged_d['strong_bull'] | (merged_d['gold_cross'] & merged_d['rs_strong'])

    # Shift by 1 day to strictly eliminate lookahead bias
    shifted = merged_d[['c1_strong_bull', 'c2_gold_cross', 'c3_trend_rs', 'c4_confluence', 'c5_regime']].shift(1).reset_index()
    df = df.merge(shifted, on='date', how='left')

    def test_strategy(name, cond_col, tp=0.025, sl=0.015, max_hold=48, cooldown_bars=24):
        cash = 100000.0
        shares = 0
        in_pos = False
        entry_price = 0.0
        entry_idx = 0
        last_exit_idx = -999
        trades = 0
        trade_log = []
        daily_bals = {}

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
                    last_exit_idx = i

            if not in_pos and (i - last_exit_idx >= cooldown_bars):
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
        win_rate = (np.array(trade_log) > 0).mean() * 100 if trade_log else 0
        print(f"\n【{name}】")
        print(f"  总交易笔数: {trades} 笔 | 年均: {trades/4.8:.1f} 笔/年 | 胜率: {win_rate:.1f}%")
        last_b = 100000.0
        for y in years:
            dys = [d for d in daily_bals.keys() if d.startswith(y)]
            if dys:
                b = daily_bals[max(dys)]
                r = (b - last_b) / last_b * 100
                print(f"    {y}年: 结余 {b:>9.2f} 元 (当年净收益: {r:>6.2f}%)")
                last_b = b
        tot_ret = (last_b - 100000.0) / 100000.0 * 100
        print(f"  --> 5年最终净收益: {tot_ret:+.2f}%")

    print("=================== 实验 A: 日线宏观趋势与相对强弱对比 (TP 2.5%, SL 1.5%, 冷却24根K线/半天) ===================")
    test_strategy("A0. 无过滤高频基准", None, tp=0.025, sl=0.015, cooldown_bars=0)
    test_strategy("A1. 招行MA60均线走平或向上 (strong_bull)", "c1_strong_bull", tp=0.025, sl=0.015, cooldown_bars=24)
    test_strategy("A2. 招行日线MA20/MA60金叉多头 (gold_cross)", "c2_gold_cross", tp=0.025, sl=0.015, cooldown_bars=24)
    test_strategy("A3. 招行自身多头且相对大盘走强 (trend_rs)", "c3_trend_rs", tp=0.025, sl=0.015, cooldown_bars=24)
    test_strategy("A4. 双金叉与超额Alpha共振 (confluence)", "c4_confluence", tp=0.025, sl=0.015, cooldown_bars=24)
    test_strategy("A5. 稳健波段共振 (regime)", "c5_regime", tp=0.025, sl=0.015, cooldown_bars=24)

    print("\n=================== 实验 B: 止盈止损参数与波段收益对比 (使用 A3 策略) ===================")
    test_strategy("B1. 较小波段 (TP 2.0%, SL 1.2%, 冷却24根)", "c3_trend_rs", tp=0.020, sl=0.012, cooldown_bars=24)
    test_strategy("B2. 标准波段 (TP 2.5%, SL 1.5%, 冷却24根)", "c3_trend_rs", tp=0.025, sl=0.015, cooldown_bars=24)
    test_strategy("B3. 较大波段 (TP 3.0%, SL 1.8%, 冷却24根)", "c3_trend_rs", tp=0.030, sl=0.018, cooldown_bars=24)
    test_strategy("B4. 宽波段高盈亏比 (TP 3.5%, SL 1.5%, 冷却48根/1天)", "c3_trend_rs", tp=0.035, sl=0.015, cooldown_bars=48, max_hold=96)

if __name__ == '__main__':
    run()
