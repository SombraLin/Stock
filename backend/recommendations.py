"""Immutable signal journal and hypothetical outcome tracking, separate from push delivery.

No broker orders, no automatic parameter fitting. All times are Asia/Shanghai.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.research_audit import trade_return, summary

ROOT = Path(__file__).resolve().parents[1]
JOURNAL_PATH = ROOT / 'data/recommendations.db'
TZ = ZoneInfo('Asia/Shanghai')
POLICY = {"version": 1, "shares": 1000, "slippage_bps": 5, "commission": .00025,
          "min_commission": 5, "sell_tax": .0005, "transfer": .00001,
          "fill": "next_completed_bar_open_proxy", "horizons_bars": [6, 12, 24, 48],
          "t1_horizon_bars": 12, "settlement": "next_observed_trading_date"}


def china_now():
    return datetime.now(TZ).replace(tzinfo=None)


def closed_bars(rows, now=None):
    """Sina timestamps denote bar END; allow 5s for final publication."""
    now = now or china_now()
    if now.tzinfo is not None:
        now = now.astimezone(TZ).replace(tzinfo=None)
    cutoff = (now - timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S')
    return [r for r in rows if str(r['datetime']) <= cutoff]


def version():
    digest = hashlib.sha256((ROOT / 'backend/strategy.py').read_bytes() + json.dumps(POLICY, sort_keys=True).encode()).hexdigest()
    return digest


def connect(path=None):
    path = Path(path or JOURNAL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS strategy_versions (
            version TEXT PRIMARY KEY, source TEXT NOT NULL, policy_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, strategy TEXT NOT NULL,
            version TEXT NOT NULL, signal_time TEXT NOT NULL, side TEXT NOT NULL,
            signal_price REAL NOT NULL, first_seen_at TEXT NOT NULL,
            origin TEXT NOT NULL, snapshot_json TEXT NOT NULL,
            UNIQUE(symbol,strategy,version,signal_time,side,origin)
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            recommendation_id INTEGER NOT NULL, mode TEXT NOT NULL, horizon INTEGER NOT NULL,
            evaluated_at TEXT NOT NULL, details_json TEXT NOT NULL,
            PRIMARY KEY(recommendation_id,mode,horizon),
            FOREIGN KEY(recommendation_id) REFERENCES recommendations(id)
        );
    ''')
    return conn


def record(symbol, result, stock_rows, index_rows, now=None, path=None, origin='live'):
    """Only fresh, completed live signals; historical replay must be explicitly labelled."""
    if origin not in ('live', 'historical_replay'):
        raise ValueError('invalid origin')
    now = now or china_now()
    rows = closed_bars(stock_rows, now)
    times = {str(r['datetime']) for r in rows[-3:]}
    indicators = {str(r['datetime']): r for r in result.get('data', [])}
    count = 0
    conn = connect(path)
    try:
        algorithm_version = version()
        conn.execute('INSERT OR IGNORE INTO strategy_versions VALUES (?,?,?)',
                     (algorithm_version, (ROOT / 'backend/strategy.py').read_text(), json.dumps(POLICY, sort_keys=True)))
        for signal in result.get('signals', []):
            ts = str(signal['datetime'])
            if origin == 'live' and (ts not in times or now - datetime.fromisoformat(ts) > timedelta(minutes=20)):
                continue
            if ts not in {str(r['datetime']) for r in rows}:
                continue
            inputs = [r for r in rows if str(r['datetime']) <= ts]
            index_inputs = [r for r in index_rows if str(r['datetime']) <= ts]
            snapshot = {"signal": signal, "strategy_meta": result.get('strategy_meta'),
                        "indicator_at_signal": indicators.get(ts), "policy": POLICY,
                        "input_rows": len(inputs), "warmup_start": inputs[0]['datetime'],
                        "input_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest(),
                        "recent_stock_bars": inputs[-80:], "recent_index_bars": index_inputs[-80:],
                        "live_full_stock_inputs": inputs if origin == 'live' else None,
                        "live_full_index_inputs": index_inputs if origin == 'live' else None,
                        "index_sha256": hashlib.sha256(json.dumps(index_inputs, sort_keys=True, default=str).encode()).hexdigest(),
                        "position_verified": False}
            # Future returns calculated by generate_signals are not information known at recommendation time.
            snapshot['signal'] = {k: v for k, v in signal.items() if not k.startswith(('ret_', 'tp_sl_'))}
            cursor = conn.execute('''INSERT OR IGNORE INTO recommendations
                (symbol,strategy,version,signal_time,side,signal_price,first_seen_at,origin,snapshot_json)
                VALUES (?,?,?,?,?,?,?,?,?)''', (symbol, signal['strategy'], algorithm_version, ts, signal['type'],
                signal['price'], now.strftime('%Y-%m-%d %H:%M:%S'), origin,
                json.dumps(snapshot, ensure_ascii=False, default=str, allow_nan=False)))
            count += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return count


def evaluate(symbol, stock_rows, now=None, path=None):
    now = now or china_now()
    rows = closed_bars(stock_rows, now)
    lookup = {str(r['datetime']): i for i, r in enumerate(rows)}
    conn = connect(path)
    count = 0
    try:
        for rec in conn.execute('SELECT * FROM recommendations WHERE symbol=?', (symbol,)).fetchall():
            idx = lookup.get(rec['signal_time'])
            if idx is None or idx + 1 >= len(rows):
                continue
            entry_i = idx + 1
            # Use the first opening AFTER observation, never an already elapsed opening.
            if rec['origin'] == 'live':
                seen = datetime.fromisoformat(rec['first_seen_at'])
                entry_i = next((j for j in range(entry_i, len(rows))
                                if datetime.fromisoformat(str(rows[j]['datetime'])) - timedelta(minutes=5) >= seen), None)
                if entry_i is None:
                    continue
            entry_row = rows[entry_i]
            policy = json.loads(rec['snapshot_json'])['policy']
            for horizon in policy['horizons_bars']:
                exit_i = entry_i + horizon
                if exit_i < len(rows):
                    modes = [('inventory', exit_i)]
                    if horizon == policy['t1_horizon_bars'] and rec['side'] == 'BUY':
                        eligible = next((j for j in range(exit_i, len(rows))
                                         if str(rows[j]['datetime'])[:10] > str(entry_row['datetime'])[:10]), None)
                        if eligible is not None:
                            modes.append(('new_position_t1', eligible))
                    for mode, j in modes:
                        entry, exit_price = float(entry_row['open']), float(rows[j]['open'])
                        shares, slip = policy['shares'], policy['slippage_bps']
                        gross = (exit_price / entry - 1) * 100
                        net = trade_return(entry, exit_price, shares, slip, policy['commission'],
                                           policy['min_commission'], policy['sell_tax'], policy['transfer'])
                        if rec['side'] == 'SELL':
                            sell = entry * (1 - slip / 10000) * shares
                            buy = exit_price * (1 + slip / 10000) * shares
                            proceeds = sell - max(policy['min_commission'], sell * policy['commission']) - sell * (policy['sell_tax'] + policy['transfer'])
                            cost = buy + max(policy['min_commission'], buy * policy['commission']) + buy * policy['transfer']
                            net = (proceeds - cost) / (entry * shares) * 100
                            gross = -gross
                        detail = {"entry_bar_end": entry_row['datetime'], "exit_bar_end": rows[j]['datetime'],
                                  "entry_price_proxy": entry, "exit_price_proxy": exit_price,
                                  "gross_pct": gross, "net_pct": net, "hypothetical": True,
                                  "interpretation": 'buy_then_sell' if rec['side'] == 'BUY' else 'sell_inventory_then_buy_back',
                                  "cross_day": rec['signal_time'][:10] != str(rows[j]['datetime'])[:10],
                                  "position_verified": False}
                        cursor = conn.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?)',
                            (rec['id'], mode, horizon, now.strftime('%Y-%m-%d %H:%M:%S'), json.dumps(detail, ensure_ascii=False)))
                        count += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return count


def recent(limit=100, path=None):
    conn = connect(path)
    try:
        records = []
        for row in conn.execute('SELECT * FROM recommendations ORDER BY id DESC LIMIT ?', (limit,)).fetchall():
            item = dict(row)
            item['snapshot'] = json.loads(item.pop('snapshot_json'))
            item['outcomes'] = [dict(x) for x in conn.execute('SELECT * FROM outcomes WHERE recommendation_id=?', (row['id'],))]
            for outcome in item['outcomes']:
                outcome['details'] = json.loads(outcome.pop('details_json'))
            records.append(item)
        return records
    finally:
        conn.close()


def performance(path=None):
    conn = connect(path)
    try:
        groups = {}
        for row in conn.execute('''SELECT r.symbol,r.strategy,r.version,r.origin,r.side,r.signal_time,
                                   o.mode,o.horizon,o.details_json FROM recommendations r
                                   JOIN outcomes o ON o.recommendation_id=r.id'''):
            key = tuple(row[k] for k in ['symbol', 'strategy', 'version', 'origin', 'side', 'mode', 'horizon'])
            details = json.loads(row['details_json'])
            # Inventory mode is specifically intraday; overnight events remain in the raw journal.
            if row['mode'] == 'inventory' and details['cross_day']:
                continue
            groups.setdefault(key, []).append({'signal_time': row['signal_time'], 'net_pct': details['net_pct']})
        return [dict(zip(['symbol', 'strategy', 'version', 'origin', 'side', 'mode', 'horizon'], key),
                     metrics=summary(events, 'net_pct')) for key, events in groups.items()]
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    from backend.database import query_klines
    from backend.strategy import generate_signals
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', action='store_true', help='Explicitly import historical signals; never label them live')
    parser.add_argument('--evaluate', action='store_true')
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    if args.replay or args.evaluate:
        now = china_now()
        idx = closed_bars(query_klines('sh510050', limit=None), now)
        for symbol in ['sh600036', 'sz000001']:
            rows = closed_bars(query_klines(symbol, limit=None), now)
            if args.replay:
                result = generate_signals(pd.DataFrame(rows), pd.DataFrame(idx), 'boll_reversion')
                print(symbol, 'historical_replay', record(symbol, result, rows, idx, now, origin='historical_replay'))
            if args.evaluate:
                print(symbol, 'outcomes', evaluate(symbol, rows, now))
    if args.summary:
        print(json.dumps(performance(), ensure_ascii=False, indent=2))
