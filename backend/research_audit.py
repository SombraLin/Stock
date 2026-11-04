"""Reproducible event study of the production signal code; never a portfolio backtest.

python3 -m backend.research_audit --output reports/audit_2026-11-04.json
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backend.strategy import STRATEGY_META, generate_signals

ROOT = Path(__file__).resolve().parents[1]


def trade_return(entry, exit_price, shares=1000, slippage_bps=5, commission=.00025,
                 min_commission=5, sell_tax=.0005, transfer=.00001):
    """Illustrative costs: commission 2.5bp/min CNY5, tax 5bp, transfer .1bp/side."""
    buy = entry * (1 + slippage_bps / 10000) * shares
    sell = exit_price * (1 - slippage_bps / 10000) * shares
    cost = buy + max(min_commission, buy * commission) + buy * transfer
    proceeds = sell - max(min_commission, sell * commission) - sell * (sell_tax + transfer)
    return (proceeds / cost - 1) * 100


def summary(events, field):
    rows = [x for x in events if x.get(field) is not None]
    if not rows:
        return {"n": 0, "mean_pct": None, "win_rate_pct": None, "day_cluster_ci95": None}
    values = np.array([x[field] for x in rows])
    # Resample entire signal days, preserving correlation of overlapping events.
    by_day = {}
    for x in rows:
        by_day.setdefault(x['signal_time'][:10], []).append(x[field])
    days = list(by_day.values())
    sums = np.array([sum(x) for x in days])
    counts = np.array([len(x) for x in days])
    rng = np.random.default_rng(20261104)
    sample = rng.integers(0, len(days), (2000, len(days)))
    means = sums[sample].sum(axis=1) / counts[sample].sum(axis=1)
    ci = np.quantile(means, [.025, .975]).tolist() if len(days) >= 2 else None
    return {"n": len(rows), "signal_days": len(days), "mean_pct": float(values.mean()),
            "median_pct": float(np.median(values)), "win_rate_pct": float((values > 0).mean() * 100),
            "day_cluster_ci95": ci}


def event_for(df, signal, boundaries):
    i = signal['index']
    row = df.iloc[i]
    result = {"signal_time": str(row.datetime), "side": signal['type'], "signal_price": signal['price']}
    day = str(row.datetime)[:10]
    result['split'] = 'train' if day < boundaries[0] else 'validation' if day < boundaries[1] else 'test'
    result['period'] = 'late' if str(row.datetime)[11:16] >= '14:30' else 'other'
    if i + 12 < len(df):
        result['close_12_gross'] = (df.iloc[i + 12].close / row.close - 1) * 100
    if i + 13 >= len(df):
        return result
    entry_i, exit_i = i + 1, i + 13
    entry, exit_price = df.iloc[entry_i].open, df.iloc[exit_i].open
    result.update(entry_time=str(df.iloc[entry_i].datetime), entry_price=float(entry))
    # A pre-existing inventory's hypothetical buy/sell price cycle, NOT guaranteed executable T trades.
    result['inventory_12_net'] = trade_return(entry, exit_price)
    result['inventory_12_gross'] = (exit_price / entry - 1) * 100
    result['cross_day_12'] = str(df.iloc[exit_i].datetime)[:10] != str(df.iloc[entry_i].datetime)[:10]
    if not result['cross_day_12'] and str(df.iloc[entry_i].datetime)[:10] == day:
        result['inventory_same_day_net'] = result['inventory_12_net']
    entry_day = str(df.iloc[entry_i].datetime)[:10]
    eligible = df.index[(df.index >= exit_i) & (df.datetime.str[:10] > entry_day)]
    if len(eligible):
        j = int(eligible[0])
        # Reject a horizon crossing the split boundary, including settlement extension.
        result['t1_exit_time'] = str(df.iloc[j].datetime)
        result['t1_net'] = trade_return(entry, df.iloc[j].open)
        if result['t1_exit_time'][:10] >= boundaries[1] and result['split'] != 'test':
            result.pop('t1_net', None)
        if result['t1_exit_time'][:10] >= boundaries[0] and result['split'] == 'train':
            result.pop('t1_net', None)
    # Purge all fixed horizons that cross a split boundary too.
    exit_day = str(df.iloc[exit_i].datetime)[:10]
    if (result['split'] == 'train' and exit_day >= boundaries[0]) or (result['split'] == 'validation' and exit_day >= boundaries[1]):
        for key in ['close_12_gross', 'inventory_12_net', 'inventory_12_gross', 'inventory_same_day_net']:
            result.pop(key, None)
    return result


def run(db_path):
    conn = sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True)
    frames = {s: pd.read_sql_query('SELECT * FROM kline_5m WHERE symbol=? ORDER BY datetime', conn, params=[s])
              for s in ['sh600036', 'sz000001', 'sh510050']}
    notifications = pd.read_sql_query('SELECT * FROM signal_notifications', conn)
    conn.close()
    data = {"method": "event study, not portfolio P&L; next-bar open is an execution proxy, not fill proof",
            "costs": {"shares": 1000, "commission": .00025, "min_commission_cny": 5,
                      "sell_tax": .0005, "transfer_per_side": .00001, "slippage_bps_per_side": 5},
            "strategy_sha256": hashlib.sha256((ROOT / 'backend/strategy.py').read_bytes()).hexdigest(),
            "symbols": {}, "notifications": {"n": len(notifications)}}
    if len(notifications):
        early = pd.to_datetime(notifications.created_at) < pd.to_datetime(notifications.signal_time)
        data['notifications']['before_bar_end'] = int(early.sum())
    for symbol in ['sh600036', 'sz000001']:
        df = frames[symbol]
        days = sorted(df.datetime.str[:10].unique())
        boundaries = [days[int(len(days) * .6)], days[int(len(days) * .8)]]
        invalid = (df.low > df[['open', 'close']].min(axis=1)) | (df.high < df[['open', 'close']].max(axis=1)) | (df.low > df.high) | (df.close <= 0)
        payload = {"bars": len(df), "days": len(days), "first": df.datetime.iloc[0], "last": df.datetime.iloc[-1],
                   "data_sha256": hashlib.sha256(df.to_csv(index=False).encode()).hexdigest(),
                   "invalid_ohlc": int(invalid.sum()), "zero_volume": int((df.volume <= 0).sum()),
                   "non_48_bar_days": {k: int(v) for k, v in df.groupby(df.datetime.str[:10]).size().items() if v != 48},
                   "split_boundaries": boundaries, "strategies": {}}
        # An unconditional comparison measures drift; same-time matching is a future stricter control.
        baseline = [event_for(df, {'index': i, 'type': 'BUY', 'price': float(df.iloc[i].close)}, boundaries)
                    for i in range(60, len(df) - 13)]
        payload['unconditional_baseline'] = {k: summary(baseline, k) for k in ['inventory_12_net', 'inventory_same_day_net', 't1_net']}
        for strategy in STRATEGY_META:
            print(symbol, strategy, flush=True)
            res = generate_signals(df, frames['sh510050'], strategy)
            events = [event_for(df, s, boundaries) for s in res['signals'] if s['type'] == 'BUY']
            fields = ['close_12_gross', 'inventory_12_gross', 'inventory_12_net', 'inventory_same_day_net', 't1_net']
            payload['strategies'][strategy] = {
                'production_metrics': res['metrics'],
                'all': {k: summary(events, k) for k in fields},
                'splits': {split: {k: summary([e for e in events if e['split'] == split], k) for k in fields}
                           for split in ['train', 'validation', 'test']},
                'late': {k: summary([e for e in events if e['period'] == 'late'], k) for k in fields},
                'events': events}
        data['symbols'][symbol] = payload
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=str(ROOT / 'data/stock.db'))
    parser.add_argument('--output', default=str(ROOT / 'reports/audit.json'))
    args = parser.parse_args()
    result = run(args.db)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
