"""
招商银行 (600036) 5分钟K线 深度数据分析与模拟买卖回测
------------------------------------------------------
纯数据驱动，不预设结论。
输出：每种策略的胜率、盈亏比、累计收益曲线、最大回撤、
      以及按时间段/市场环境分层的表现差异。
"""

import sys, os, json, math
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

# --- 加载数据 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.database import query_klines

def load_data():
    stock = pd.DataFrame(query_klines("sh600036", limit=None))
    index = pd.DataFrame(query_klines("sh510050", limit=None))
    if index.empty:
        index = pd.DataFrame(query_klines("sh000001", limit=None))
    stock['datetime'] = pd.to_datetime(stock['datetime'])
    index['datetime'] = pd.to_datetime(index['datetime'])
    # 合并大盘数据
    idx_sub = index[['datetime', 'close', 'volume']].rename(
        columns={'close': 'idx_close', 'volume': 'idx_volume'})
    df = pd.merge(stock, idx_sub, on='datetime', how='left')
    df['idx_close'] = df['idx_close'].ffill()
    df.sort_values('datetime', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def add_indicators(df):
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    # 均线
    for w in [5, 10, 20, 60]:
        df[f'ma{w}'] = c.rolling(w).mean()

    # 布林带
    std20 = c.rolling(20).std()
    df['boll_mid'] = df['ma20']
    df['boll_up'] = df['boll_mid'] + 2 * std20
    df['boll_low'] = df['boll_mid'] - 2 * std20
    df['boll_width'] = (df['boll_up'] - df['boll_low']) / df['boll_mid'] * 100  # %

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df['dif'] = ema12 - ema26
    df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = (df['dif'] - df['dea']) * 2

    # RSI-14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df['rsi14'] = 100 - 100 / (1 + gain / (loss + 1e-9))

    # 成交量均线
    df['vol_ma5'] = v.rolling(5).mean()
    df['vol_ma20'] = v.rolling(20).mean()
    df['vol_ratio'] = v / (df['vol_ma5'] + 1)

    # 涨跌幅
    df['ret'] = c.pct_change()
    df['ret5'] = c.pct_change(5)
    df['idx_ret5'] = df['idx_close'].pct_change(5)
    df['alpha5'] = df['ret5'] - df['idx_ret5']  # 相对强弱

    # ATR (14)
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()

    # 日内时段标记
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    df['date'] = df['datetime'].dt.date
    df['hour'] = df['datetime'].dt.hour
    df['minute'] = df['datetime'].dt.minute

    # K线形态：锤子线/上影线/十字星
    body = (c - df['open']).abs()
    full_range = h - l + 1e-9
    df['body_ratio'] = body / full_range
    df['upper_shadow'] = (h - pd.concat([c, df['open']], axis=1).max(axis=1)) / full_range
    df['lower_shadow'] = (pd.concat([c, df['open']], axis=1).min(axis=1) - l) / full_range

    return df


# ============================================================
# 策略定义
# ============================================================
def strategy_boll_reversion(df, i):
    """布林带触下轨+RSI超卖 买入；触上轨+RSI超买 卖出"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['boll_low']) or pd.isna(row['rsi14']):
        return None
    if prev['low'] <= prev['boll_low'] and row['close'] > row['boll_low'] and row['rsi14'] < 40:
        return 'BUY'
    if prev['high'] >= prev['boll_up'] and row['close'] < row['boll_up'] and row['rsi14'] > 60:
        return 'SELL'
    return None

def strategy_ma_cross(df, i):
    """MA5金叉MA20买入，死叉卖出"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['ma5']) or pd.isna(row['ma20']):
        return None
    if prev['ma5'] <= prev['ma20'] and row['ma5'] > row['ma20']:
        return 'BUY'
    if prev['ma5'] >= prev['ma20'] and row['ma5'] < row['ma20']:
        return 'SELL'
    return None

def strategy_macd_cross(df, i):
    """MACD DIF上穿DEA买入，下穿卖出"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['dif']) or pd.isna(row['dea']):
        return None
    if prev['dif'] <= prev['dea'] and row['dif'] > row['dea']:
        return 'BUY'
    if prev['dif'] >= prev['dea'] and row['dif'] < row['dea']:
        return 'SELL'
    return None

def strategy_rsi_extreme(df, i):
    """RSI极值反转：<25买入，>75卖出"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['rsi14']):
        return None
    if prev['rsi14'] < 25 and row['rsi14'] >= 25:
        return 'BUY'
    if prev['rsi14'] > 75 and row['rsi14'] <= 75:
        return 'SELL'
    return None

def strategy_index_divergence(df, i):
    """招行vs大盘相对强弱策略"""
    row = df.iloc[i]
    if pd.isna(row['alpha5']) or pd.isna(row['ma10']):
        return None
    if row['alpha5'] > 0.005 and row['close'] > row['ma10'] and row['vol_ratio'] > 1.2:
        return 'BUY'
    if row['alpha5'] < -0.005 and row['close'] < row['ma10']:
        return 'SELL'
    return None

def strategy_vol_breakout(df, i):
    """放量突破MA20买入；缩量跌破卖出"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['ma20']) or pd.isna(row['vol_ma20']):
        return None
    if prev['close'] <= prev['ma20'] and row['close'] > row['ma20'] and row['volume'] > row['vol_ma20'] * 1.5:
        return 'BUY'
    if prev['close'] >= prev['ma20'] and row['close'] < row['ma20'] and row['volume'] > row['vol_ma20'] * 1.2:
        return 'SELL'
    return None

def strategy_hammer_reversal(df, i):
    """K线形态：长下影(锤子)买入，长上影卖出"""
    row = df.iloc[i]
    if pd.isna(row['rsi14']):
        return None
    # 锤子线底部买入
    if row['lower_shadow'] > 0.6 and row['body_ratio'] < 0.25 and row['rsi14'] < 40 and row['close'] <= row['boll_low'] * 1.005:
        return 'BUY'
    # 长上影顶部卖出
    if row['upper_shadow'] > 0.6 and row['body_ratio'] < 0.25 and row['rsi14'] > 60 and row['close'] >= row['boll_up'] * 0.995:
        return 'SELL'
    return None

def strategy_combined_score(df, i):
    """多因子评分综合"""
    row, prev = df.iloc[i], df.iloc[i-1]
    if pd.isna(row['boll_low']) or pd.isna(row['rsi14']) or pd.isna(row['dif']):
        return None
    
    score = 0.0
    # BOLL
    if row['close'] <= row['boll_low'] * 1.002:
        score += 2
    elif row['close'] >= row['boll_up'] * 0.998:
        score -= 2
    # RSI
    if row['rsi14'] < 30:
        score += 2
    elif row['rsi14'] > 70:
        score -= 2
    elif row['rsi14'] < 40:
        score += 1
    elif row['rsi14'] > 60:
        score -= 1
    # MACD 动量方向
    if row['dif'] > row['dea'] and row['macd_hist'] > prev['macd_hist']:
        score += 1.5
    elif row['dif'] < row['dea'] and row['macd_hist'] < prev['macd_hist']:
        score -= 1.5
    # MA
    if row['close'] > row['ma20'] and prev['close'] <= prev['ma20']:
        score += 1.5
    elif row['close'] < row['ma20'] and prev['close'] >= prev['ma20']:
        score -= 1.5
    # Alpha
    if not pd.isna(row['alpha5']):
        if row['alpha5'] > 0.003:
            score += 1
        elif row['alpha5'] < -0.003:
            score -= 1

    if score >= 3.5:
        return 'BUY'
    elif score <= -3.5:
        return 'SELL'
    return None


STRATEGIES = {
    'boll_reversion':    ('布林带通道极值均值回归', strategy_boll_reversion),
    'ma_cross':          ('双均线金叉死叉 (MA5/MA20)', strategy_ma_cross),
    'macd_cross':        ('MACD DIF/DEA 金叉死叉', strategy_macd_cross),
    'rsi_extreme':       ('RSI 极值反转 (<25/>75)', strategy_rsi_extreme),
    'index_divergence':  ('招行vs上证 相对强弱Alpha', strategy_index_divergence),
    'vol_breakout':      ('放量突破MA20', strategy_vol_breakout),
    'hammer_reversal':   ('K线锤子/上影形态反转', strategy_hammer_reversal),
    'combined_score':    ('多因子综合评分(≥3.5)', strategy_combined_score),
}


# ============================================================
# 回测引擎
# ============================================================
def backtest_fixed_horizon(df, strategy_fn, horizons=[6, 12, 24, 48]):
    """
    固定持有期回测：
    每个买入信号后，分别持有 N 根K线（5分钟×N），计算收益。
    """
    results = {h: [] for h in horizons}
    signals = []
    n = len(df)
    
    for i in range(60, n):
        sig = strategy_fn(df, i)
        if sig != 'BUY':
            continue
        buy_price = df.iloc[i]['close']
        buy_time = df.iloc[i]['datetime']
        
        entry = {
            'datetime': str(buy_time),
            'price': float(buy_price),
            'time_str': df.iloc[i]['time_str'],
            'rsi': float(df.iloc[i]['rsi14']) if not pd.isna(df.iloc[i]['rsi14']) else None,
            'boll_pos': None,
        }
        if not pd.isna(df.iloc[i]['boll_up']) and not pd.isna(df.iloc[i]['boll_low']):
            brange = df.iloc[i]['boll_up'] - df.iloc[i]['boll_low']
            if brange > 0:
                entry['boll_pos'] = float((buy_price - df.iloc[i]['boll_low']) / brange)
        
        for h in horizons:
            if i + h < n:
                exit_price = df.iloc[i + h]['close']
                ret_pct = (exit_price - buy_price) / buy_price * 100
                results[h].append({
                    **entry,
                    'exit_price': float(exit_price),
                    'ret_pct': float(ret_pct),
                    'horizon': h,
                })
        signals.append(entry)
    
    return results, signals

def backtest_signal_pair(df, strategy_fn, max_hold=96):
    """
    信号配对回测：
    BUY信号买入 → 等待SELL信号卖出 或 达到最大持有期强制平仓。
    模拟真实交易。
    """
    trades = []
    n = len(df)
    position = None  # None = 空仓
    
    for i in range(60, n):
        sig = strategy_fn(df, i)
        
        if position is None and sig == 'BUY':
            position = {
                'buy_idx': i,
                'buy_time': str(df.iloc[i]['datetime']),
                'buy_price': float(df.iloc[i]['close']),
                'buy_rsi': float(df.iloc[i]['rsi14']) if not pd.isna(df.iloc[i]['rsi14']) else None,
                'buy_time_str': df.iloc[i]['time_str'],
            }
        elif position is not None:
            sell_now = False
            exit_reason = ''
            
            if sig == 'SELL':
                sell_now = True
                exit_reason = '策略卖出信号'
            elif (i - position['buy_idx']) >= max_hold:
                sell_now = True
                exit_reason = f'超时强平({max_hold}根K线)'
            
            if sell_now:
                sell_price = float(df.iloc[i]['close'])
                ret_pct = (sell_price - position['buy_price']) / position['buy_price'] * 100
                hold_bars = i - position['buy_idx']
                trades.append({
                    **position,
                    'sell_idx': i,
                    'sell_time': str(df.iloc[i]['datetime']),
                    'sell_price': sell_price,
                    'sell_time_str': df.iloc[i]['time_str'],
                    'ret_pct': float(ret_pct),
                    'hold_bars': hold_bars,
                    'hold_minutes': hold_bars * 5,
                    'exit_reason': exit_reason,
                })
                position = None
    
    return trades


def calc_metrics(returns_list):
    """从收益率列表计算各种统计指标"""
    if not returns_list:
        return {
            'count': 0, 'win_rate': 0, 'avg_ret': 0, 'median_ret': 0,
            'max_win': 0, 'max_loss': 0, 'profit_loss_ratio': 0,
            'expectation': 0, 'sharpe_approx': 0,
            'total_ret': 0,
        }
    
    rets = np.array(returns_list)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    
    win_rate = len(wins) / len(rets) * 100
    avg_ret = float(np.mean(rets))
    median_ret = float(np.median(rets))
    
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.001
    plr = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # 期望值 = 胜率 × 平均盈利 - 败率 × 平均亏损
    expectation = (win_rate / 100) * avg_win - (1 - win_rate / 100) * avg_loss
    
    # 近似夏普 (均值/标准差)
    std = float(np.std(rets)) if len(rets) > 1 else 1
    sharpe = avg_ret / std if std > 0 else 0
    
    # 累计收益（假设每次满仓）
    cum = 1.0
    for r in rets:
        cum *= (1 + r / 100)
    total_ret = (cum - 1) * 100
    
    # 最大回撤
    peak = 1.0
    max_dd = 0
    cum_val = 1.0
    for r in rets:
        cum_val *= (1 + r / 100)
        peak = max(peak, cum_val)
        dd = (peak - cum_val) / peak * 100
        max_dd = max(max_dd, dd)
    
    return {
        'count': len(rets),
        'win_rate': round(win_rate, 1),
        'avg_ret': round(avg_ret, 3),
        'median_ret': round(median_ret, 3),
        'max_win': round(float(np.max(rets)), 3),
        'max_loss': round(float(np.min(rets)), 3),
        'profit_loss_ratio': round(plr, 2),
        'expectation': round(expectation, 3),
        'sharpe_approx': round(sharpe, 3),
        'total_ret': round(total_ret, 2),
        'max_drawdown': round(max_dd, 2),
    }


def analyze_by_time_period(signals_with_returns):
    """按日内时段分析信号表现"""
    period_map = {
        '09:30-10:00 早盘开盘半小时': lambda t: '09:' in t and int(t.split(':')[1]) < 60 and int(t.split(':')[0]) == 9,
        '10:00-10:30 早盘中段': lambda t: t >= '10:00' and t < '10:30',
        '10:30-11:30 早盘尾段': lambda t: t >= '10:30' and t <= '11:30',
        '13:00-14:00 午后开盘': lambda t: t >= '13:00' and t < '14:00',
        '14:00-14:30 午后中段': lambda t: t >= '14:00' and t < '14:30',
        '14:30-15:00 尾盘': lambda t: t >= '14:30' and t <= '15:00',
    }
    
    results = {}
    for period_name, cond_fn in period_map.items():
        filtered = [s for s in signals_with_returns if cond_fn(s.get('time_str', ''))]
        rets = [s['ret_pct'] for s in filtered]
        results[period_name] = calc_metrics(rets)
    
    return results


# ============================================================
# 主分析流程
# ============================================================
def run_full_analysis():
    print("=" * 80)
    print("招商银行(600036) 5分钟K线 — 纯数据驱动买卖点规律深度分析")
    print("=" * 80)
    
    df = load_data()
    df = add_indicators(df)
    
    total_bars = len(df)
    date_range = f"{df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}"
    trading_days = df['date'].nunique()
    
    print(f"\n数据总量: {total_bars} 根 5 分钟 K 线")
    print(f"时间范围: {date_range}")
    print(f"交易日数: {trading_days} 天")
    print(f"招商银行价格区间: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
    
    # 整体涨跌统计
    total_price_change = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
    print(f"期间总涨跌幅: {total_price_change:+.2f}%")
    
    all_results = {}
    
    for key, (name, fn) in STRATEGIES.items():
        print(f"\n{'─' * 70}")
        print(f"📊 策略: {name} ({key})")
        print(f"{'─' * 70}")
        
        # 1) 固定持有期回测
        horizon_results, signals = backtest_fixed_horizon(df, fn, horizons=[6, 12, 24, 48])
        
        print(f"\n  信号总数(买入): {len(signals)}")
        
        horizon_metrics = {}
        for h in [6, 12, 24, 48]:
            rets = [r['ret_pct'] for r in horizon_results[h]]
            m = calc_metrics(rets)
            horizon_metrics[h] = m
            minutes = h * 5
            print(f"\n  ── 固定持有 {h} 根K线 ({minutes}分钟) ──")
            print(f"     交易次数: {m['count']}")
            print(f"     胜  率: {m['win_rate']}%")
            print(f"     平均收益: {m['avg_ret']}%  |  中位数: {m['median_ret']}%")
            print(f"     最大盈利: {m['max_win']}%  |  最大亏损: {m['max_loss']}%")
            print(f"     盈亏比: {m['profit_loss_ratio']}")
            print(f"     数学期望: {m['expectation']}%")
            print(f"     累计收益: {m['total_ret']}%  |  最大回撤: {m['max_drawdown']}%")
        
        # 2) 信号配对回测
        trades = backtest_signal_pair(df, fn, max_hold=96)
        trade_rets = [t['ret_pct'] for t in trades]
        pair_m = calc_metrics(trade_rets)
        
        print(f"\n  ── 信号配对回测 (BUY→等SELL, 最大持仓96根K线) ──")
        print(f"     完整交易数: {pair_m['count']}")
        print(f"     胜  率: {pair_m['win_rate']}%")
        print(f"     平均收益: {pair_m['avg_ret']}%  |  中位数: {pair_m['median_ret']}%")
        print(f"     盈亏比: {pair_m['profit_loss_ratio']}")
        print(f"     数学期望: {pair_m['expectation']}%")
        print(f"     累计收益: {pair_m['total_ret']}%  |  最大回撤: {pair_m['max_drawdown']}%")
        
        if trades:
            hold_bars = [t['hold_bars'] for t in trades]
            print(f"     平均持仓: {np.mean(hold_bars):.0f} 根 ({np.mean(hold_bars)*5:.0f}分钟)")
            timeout_count = sum(1 for t in trades if '超时' in t['exit_reason'])
            print(f"     超时强平: {timeout_count}/{len(trades)} ({timeout_count/len(trades)*100:.0f}%)")
        
        # 3) 日内时段分析 (以12根K线=60分钟持有期为基准)
        period_analysis = analyze_by_time_period(horizon_results.get(12, []))
        
        print(f"\n  ── 日内时段表现分层 (持有60分钟) ──")
        for period, pm in period_analysis.items():
            if pm['count'] > 0:
                print(f"     {period}: 次数={pm['count']}, 胜率={pm['win_rate']}%, "
                      f"平均={pm['avg_ret']}%, 期望={pm['expectation']}%")
        
        all_results[key] = {
            'name': name,
            'signal_count': len(signals),
            'horizon_metrics': {str(h): horizon_metrics[h] for h in [6, 12, 24, 48]},
            'pair_metrics': pair_m,
            'pair_trades': trades,
            'period_analysis': {k: v for k, v in period_analysis.items()},
        }
    
    # ============================================================
    # 综合横向对比与结论
    # ============================================================
    print(f"\n\n{'═' * 80}")
    print("📋 八大策略横向对比总表")
    print(f"{'═' * 80}")
    print(f"\n{'策略名称':<28} {'信号数':>6} {'胜率(60m)':>10} {'平均收益':>10} {'盈亏比':>8} {'期望值':>8} {'累计收益':>10} {'最大回撤':>10}")
    print("─" * 100)
    
    ranking = []
    for key, res in all_results.items():
        m60 = res['horizon_metrics'].get('12', {})
        print(f"{res['name']:<26} {res['signal_count']:>6} "
              f"{m60.get('win_rate', 0):>9.1f}% "
              f"{m60.get('avg_ret', 0):>9.3f}% "
              f"{m60.get('profit_loss_ratio', 0):>7.2f} "
              f"{m60.get('expectation', 0):>7.3f}% "
              f"{m60.get('total_ret', 0):>9.2f}% "
              f"{m60.get('max_drawdown', 0):>9.2f}%")
        ranking.append((key, res['name'], m60.get('expectation', 0), m60.get('win_rate', 0), m60.get('profit_loss_ratio', 0)))
    
    # 按期望值排序
    ranking.sort(key=lambda x: x[2], reverse=True)
    
    print(f"\n\n{'═' * 80}")
    print("🏆 策略排名 (按数学期望值排序)")
    print(f"{'═' * 80}")
    for rank, (key, name, exp, wr, plr) in enumerate(ranking, 1):
        emoji = '🥇' if rank == 1 else ('🥈' if rank == 2 else ('🥉' if rank == 3 else f' {rank}.'))
        verdict = ''
        if exp > 0.02:
            verdict = '✅ 有正期望，可实盘验证'
        elif exp > 0:
            verdict = '⚠️ 微弱正期望，需优化参数'
        else:
            verdict = '❌ 负期望，当前参数不可直接使用'
        print(f"  {emoji} {name}: 期望={exp:+.3f}% | 胜率={wr:.1f}% | 盈亏比={plr:.2f}  {verdict}")
    
    # 将结果写入 JSON 供前端展示
    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'analysis_results.json')
    
    # 清除trades中的非标准float以便JSON序列化
    clean_results = {}
    for key, res in all_results.items():
        clean = {
            'name': res['name'],
            'signal_count': res['signal_count'],
            'horizon_metrics': res['horizon_metrics'],
            'pair_metrics': res['pair_metrics'],
            'period_analysis': res['period_analysis'],
            'pair_trades_count': len(res['pair_trades']),
            'sample_trades': res['pair_trades'][:10] if res['pair_trades'] else [],
        }
        clean_results[key] = clean
    
    meta = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_range': date_range,
        'total_bars': total_bars,
        'trading_days': trading_days,
        'price_range': f"{df['close'].min():.2f} ~ {df['close'].max():.2f}",
        'period_change_pct': round(total_price_change, 2),
        'ranking': [(key, name, round(exp, 3)) for key, name, exp, wr, plr in ranking],
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'strategies': clean_results}, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n详细数据已保存到: {output_path}")
    
    return all_results, meta


if __name__ == "__main__":
    run_full_analysis()
