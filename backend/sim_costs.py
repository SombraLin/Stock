"""A-share simulation cost accounting. Monetary amounts settle to cents."""
import json
from decimal import Decimal, ROUND_HALF_UP

VERSION = 'a_share_costs_v1'
POLICY = {'version': VERSION, 'commission_rate': 0.00025, 'minimum_commission': 5.0,
          'sell_stamp_tax_rate': 0.0005, 'transfer_rate_per_side': 0.00001,
          'description': '佣金万2.5（每笔最低5元）＋卖出印花税0.05%＋双边过户费0.001%；金额四舍五入到分'}


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('金额必须为有限数字')
    return result


def money(value):
    return decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def fees(amount, side):
    if side not in ('BUY', 'SELL'):
        raise ValueError('不支持的交易类型')
    amount = money(amount)
    commission = money(max(Decimal('5'), amount * Decimal('.00025')))
    tax = money(amount * Decimal('.0005')) if side == 'SELL' else Decimal('0.00')
    transfer = money(amount * Decimal('.00001'))
    return {'commission': commission, 'stamp_tax': tax, 'transfer_fee': transfer,
            'fee': commission + tax + transfer}


def apply_trade(cash, positions, symbol, side, shares, price, allow_deficit=False):
    price = decimal(price)
    if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0 or price <= 0:
        raise ValueError('数量必须为正整数，价格必须大于0')
    if side == 'BUY' and shares % 100:
        raise ValueError('A股买入必须是整手 (100股的整数倍)')
    amount = money(price * shares)
    detail = fees(amount, side)
    positions = {k: dict(v) for k, v in positions.items()}
    position = positions.get(symbol, {'shares': 0, 'cost': Decimal('0.00')})
    cash = money(cash)
    pnl = Decimal('0.00')
    if side == 'BUY':
        total = amount + detail['fee']
        if not allow_deficit and cash < total:
            raise ValueError(f'可用现金不足！需要 ¥{total:.2f}，当前可用 ¥{cash:.2f}')
        cash -= total
        position['cost'] = money(position['cost']) + total
        position['shares'] += shares
        positions[symbol] = position
    else:
        if position['shares'] < shares:
            raise ValueError(f'可用持仓不足！欲卖出 {shares} 股，当前持仓 {position["shares"]} 股')
        allocated_cost = money(decimal(position['cost']) * shares / position['shares'])
        cash += amount - detail['fee']
        pnl = amount - detail['fee'] - allocated_cost
        position['cost'] = money(position['cost']) - allocated_cost
        position['shares'] -= shares
        if position['shares']:
            positions[symbol] = position
        else:
            positions.pop(symbol, None)
    return cash, positions, {'amount': amount, **detail, 'pnl': pnl}


def migrate(conn):
    """Rebuild from original executions, NOT by subtracting all fees a second time.

    Caller owns the transaction. Position counts must match before any data changes.
    """
    conn.execute('''CREATE TABLE IF NOT EXISTS sim_cost_migrations
                    (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, details_json TEXT NOT NULL)''')
    if conn.execute('SELECT 1 FROM sim_cost_migrations WHERE version=?', (VERSION,)).fetchone():
        return None
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(sim_trades)')}
    for name in ['commission', 'stamp_tax', 'transfer_fee']:
        if name not in columns:
            conn.execute(f'ALTER TABLE sim_trades ADD COLUMN {name} REAL NOT NULL DEFAULT 0')
    account = conn.execute('SELECT * FROM sim_account WHERE id=1').fetchone()
    trades = conn.execute('SELECT * FROM sim_trades ORDER BY created_at,id').fetchall()
    old_positions = [dict(r) for r in conn.execute('SELECT * FROM sim_position')]
    initial_cash = money(account['initial_cash'])
    cash, positions, rebuilt = initial_cash, {}, []
    for trade in trades:
        cash, positions, detail = apply_trade(cash, positions, trade['symbol'], trade['type'],
                                               trade['shares'], trade['price'], allow_deficit=True)
        rebuilt.append((trade, detail))
    old_shares = {r['symbol']: r['shares'] for r in old_positions if r['shares']}
    if old_shares != {s: p['shares'] for s, p in positions.items()}:
        raise ValueError('历史成交流水与当前持仓数量不一致，拒绝自动修复')
    old_fees = sum((decimal(t['fee']) for t in trades), Decimal(0))
    new_fees = sum((d['fee'] for _, d in rebuilt), Decimal(0))
    for trade, detail in rebuilt:
        conn.execute('''UPDATE sim_trades SET amount=?,fee=?,pnl=?,commission=?,stamp_tax=?,transfer_fee=? WHERE id=?''',
                     tuple(float(detail[k]) for k in ['amount', 'fee', 'pnl', 'commission', 'stamp_tax', 'transfer_fee']) + (trade['id'],))
    for symbol, position in positions.items():
        conn.execute('UPDATE sim_position SET avg_cost=? WHERE symbol=?',
                     (float(position['cost'] / position['shares']), symbol))
    conn.execute("UPDATE sim_account SET cash=?,updated_at=datetime('now','localtime') WHERE id=1", (float(cash),))
    report = {'policy': POLICY, 'trades': len(trades), 'old_cash': float(account['cash']), 'new_cash': float(cash),
              'old_total_fees': float(old_fees), 'new_total_fees': float(new_fees),
              'old_positions': old_positions,
              'new_positions': {s: {'shares': p['shares'], 'cost': float(p['cost']), 'avg_cost': float(p['cost'] / p['shares'])} for s, p in positions.items()}}
    conn.execute("INSERT INTO sim_cost_migrations VALUES (?,datetime('now','localtime'),?)",
                 (VERSION, json.dumps(report, ensure_ascii=False)))
    return report
