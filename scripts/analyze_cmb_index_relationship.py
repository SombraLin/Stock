import sqlite3
import pandas as pd
import numpy as np

def load_daily():
    conn = sqlite3.connect('data/stock.db')
    df = pd.read_sql("""
        SELECT symbol, date, open, high, low, close, volume, amount, pct_change
        FROM kline_daily
        WHERE symbol IN ('sh600036', 'sh000001')
        ORDER BY date ASC
    """, conn)
    conn.close()
    
    cmb = df[df['symbol'] == 'sh600036'].copy().set_index('date')
    idx = df[df['symbol'] == 'sh000001'].copy().set_index('date')
    
    merged = cmb[['open', 'high', 'low', 'close', 'volume', 'pct_change']].join(
        idx[['open', 'high', 'low', 'close', 'volume', 'pct_change']],
        lsuffix='_cmb', rsuffix='_idx', how='inner'
    ).reset_index()
    
    return merged

def analyze_regimes(df):
    print("===== 招商银行与上证指数跨周期关系深度实证分析 =====")
    df['year'] = pd.to_datetime(df['date']).dt.year
    
    # 均线
    df['ma20_idx'] = df['close_idx'].rolling(20).mean()
    df['ma60_idx'] = df['close_idx'].rolling(60).mean()
    df['ma20_cmb'] = df['close_cmb'].rolling(20).mean()
    df['ma60_cmb'] = df['close_cmb'].rolling(60).mean()
    
    # 相对强弱 RS: CMB / Index
    df['rs_ratio'] = df['close_cmb'] / df['close_idx']
    df['rs_ma20'] = df['rs_ratio'].rolling(20).mean()
    
    # 年度相关系数与 Beta
    years = [2022, 2023, 2024, 2025, 2026]
    print("\n1. 历年相关系数与 Beta (CMB vs 上证指数)")
    print(f"{'年份':<6} | {'相关系数(Correlation)':<18} | {'Beta系数':<10} | {'招行涨跌幅':<12} | {'大盘涨跌幅':<12}")
    print("-" * 70)
    
    for y in years:
        sub = df[df['year'] == y]
        if len(sub) < 10:
            continue
        corr = sub['pct_change_cmb'].corr(sub['pct_change_idx'])
        cov = np.cov(sub['pct_change_cmb'], sub['pct_change_idx'])[0][1]
        var_idx = np.var(sub['pct_change_idx'])
        beta = cov / var_idx if var_idx > 0 else 0
        
        y_ret_cmb = (sub['close_cmb'].iloc[-1] - sub['open_cmb'].iloc[0]) / sub['open_cmb'].iloc[0] * 100
        y_ret_idx = (sub['close_idx'].iloc[-1] - sub['open_idx'].iloc[0]) / sub['open_idx'].iloc[0] * 100
        
        print(f"{y:<6} | {corr:>18.3f} | {beta:>10.2f} | {y_ret_cmb:>11.2f}% | {y_ret_idx:>11.2f}%")
        
    # 分析大盘不同趋势状态下，招商银行逢低做多的真实胜率和期望
    print("\n2. 大盘趋势环境对招商银行逢低买入胜率的决定性影响 (2022-2026)")
    # 定义招行超跌: 当日跌幅或偏离度
    # 状态A: 大盘处于日线 MA20 上方 (大盘强势/震荡偏多)
    # 状态B: 大盘处于日线 MA20 下方 (大盘弱势/阴跌)
    sub_all = df[df['year'] >= 2022].copy()
    sub_all['fwd_ret_5d'] = (sub_all['close_cmb'].shift(-5) - sub_all['close_cmb']) / sub_all['close_cmb'] * 100
    sub_all['fwd_ret_10d'] = (sub_all['close_cmb'].shift(-10) - sub_all['close_cmb']) / sub_all['close_cmb'] * 100
    sub_all['cmb_dip'] = (sub_all['close_cmb'] < sub_all['ma20_cmb']) # 招行处于均线下方(回调/探底)
    
    # 状态 A: 大盘在 MA20 之上，招行回调
    cond_a = sub_all['cmb_dip'] & (sub_all['close_idx'] >= sub_all['ma20_idx'])
    res_a = sub_all[cond_a]['fwd_ret_5d'].dropna()
    
    # 状态 B: 大盘在 MA20 之下，招行回调 (顺势下跌，接飞刀)
    cond_b = sub_all['cmb_dip'] & (sub_all['close_idx'] < sub_all['ma20_idx'])
    res_b = sub_all[cond_b]['fwd_ret_5d'].dropna()
    
    # 状态 C: 相对强弱背离 - 大盘下跌创新低，但招行相对大盘走强 (RS上升)
    sub_all['idx_down'] = sub_all['close_idx'] < sub_all['close_idx'].shift(1)
    sub_all['rs_up'] = sub_all['rs_ratio'] > sub_all['rs_ratio'].shift(1)
    cond_c = sub_all['idx_down'] & sub_all['rs_up'] & (sub_all['close_idx'] >= sub_all['ma60_idx'])
    res_c = sub_all[cond_c]['fwd_ret_5d'].dropna()
    
    print(f"情景 A【大盘健康(Index >= MA20) + 招行回调探底】:")
    print(f"  触发样本数: {len(res_a)} 天")
    print(f"  后5日胜率: {(res_a > 0).mean()*100:.1f}%")
    print(f"  后5日平均收益: {res_a.mean():.2f}%")
    print(f"  盈亏比: {res_a[res_a>0].mean() / abs(res_a[res_a<0].mean() + 1e-9):.2f}")
    
    print(f"\n情景 B【大盘熊市阴跌(Index < MA20) + 招行回调探底(接飞刀)】:")
    print(f"  触发样本数: {len(res_b)} 天")
    print(f"  后5日胜率: {(res_b > 0).mean()*100:.1f}%")
    print(f"  后5日平均收益: {res_b.mean():.2f}%")
    print(f"  盈亏比: {res_b[res_b>0].mean() / abs(res_b[res_b<0].mean() + 1e-9):.2f}")
    
    print(f"\n情景 C【大盘中枢之上震荡，招行抗跌顶立(RS相对强弱背离逆势走强)】:")
    print(f"  触发样本数: {len(res_c)} 天")
    print(f"  后5日胜率: {(res_c > 0).mean()*100:.1f}%")
    print(f"  后5日平均收益: {res_c.mean():.2f}%")
    print(f"  盈亏比: {res_c[res_c>0].mean() / abs(res_c[res_c<0].mean() + 1e-9):.2f}")

if __name__ == '__main__':
    df = load_daily()
    analyze_regimes(df)
