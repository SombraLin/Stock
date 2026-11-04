import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import database
from backend.sim_costs import fees, money, migrate, apply_trade


class SimulationCostsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'stock.db'
        self.patch = patch.object(database, 'DB_PATH', str(self.path))
        self.patch.start()
        database.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_fee_components_and_minimum(self):
        self.assertEqual(fees(42000, 'BUY'), dict(commission=money(10.5), stamp_tax=money(0), transfer_fee=money(.42), fee=money(10.92)))
        self.assertEqual(fees(1000, 'SELL')['fee'], money(5.51))

    def test_initial_position_capitalizes_buy_fees(self):
        result = database.set_initial_position()
        self.assertEqual(result['cash'], 57989.08)
        summary = database.get_sim_account_summary(42.)
        self.assertEqual(summary['position']['unrealized_pnl'], -10.92)
        self.assertEqual(summary['total_pnl'], -10.92)
        self.assertEqual(summary['total_fees'], 10.92)

    def test_partial_sell_allocates_buy_fees(self):
        database.set_initial_position()
        result = database.execute_sim_trade('sh600036', 'SELL', 500, 42.97)
        self.assertEqual(result['trade']['fee'], 16.32)
        self.assertEqual(result['trade']['pnl'], 463.22)
        summary = database.get_sim_account_summary(42.97)
        self.assertEqual(summary['cash'], 79457.76)
        self.assertAlmostEqual(summary['total_pnl'], summary['realized_pnl'] + summary['position']['unrealized_pnl'], places=2)

    def test_same_price_round_trip_has_loss_equal_to_fees(self):
        self.assertEqual(database.execute_sim_trade('sz000001', 'BUY', 100, 10.)['status'], 'success')
        self.assertEqual(database.execute_sim_trade('sz000001', 'SELL', 100, 10.)['status'], 'success')
        summary = database.get_sim_account_summary(10., 'sz000001')
        self.assertEqual(summary['total_pnl'], -10.52)
        self.assertEqual(summary['total_pnl'], -summary['total_fees'])

    def test_rejected_order_is_atomic(self):
        before = database.get_sim_account_summary()
        for shares, price in [(100000, 42.), (100, float('nan')), (100, float('inf')), (1, 42.), (-100, 42.)]:
            self.assertEqual(database.execute_sim_trade('sh600036', 'BUY', shares, price)['status'], 'error')
        self.assertEqual(database.get_sim_account_summary(), before)
        self.assertEqual(database.execute_sim_trade('sh600036', 'SELL', 100, 42.)['status'], 'error')

    def test_invalid_initial_position_preserves_existing_account(self):
        database.set_initial_position()
        before = database.get_sim_account_summary()
        self.assertEqual(database.set_initial_position(shares=100000)['status'], 'error')
        self.assertEqual(database.get_sim_account_summary(), before)

    def test_nav_includes_other_symbols(self):
        database.execute_sim_trade('sh600036', 'BUY', 100, 42.)
        database.execute_sim_trade('sz000001', 'BUY', 100, 10.)
        summary = database.get_sim_account_summary(42., 'sh600036')
        # Without a market price for the other symbol it is valued at book cost.
        self.assertGreater(summary['total_assets'], 99990)

    def test_average_cost_rounding_conserves_total_basis(self):
        cash, positions, _ = apply_trade(100000, {}, 'sh600036', 'BUY', 300, 10.)
        realized = money(0)
        for _ in range(3):
            cash, positions, detail = apply_trade(cash, positions, 'sh600036', 'SELL', 100, 10.)
            realized += detail['pnl']
        self.assertEqual(cash - money(100000), realized)
        self.assertEqual(positions, {})

    def test_restart_does_not_recharge_new_trades(self):
        database.set_initial_position()
        database.execute_sim_trade('sh600036', 'SELL', 500, 42.97)
        before = database.get_sim_account_summary(42.97)
        database.init_db()
        self.assertEqual(database.get_sim_account_summary(42.97), before)

    def test_reset_clears_cost_totals_and_rejects_invalid_cash(self):
        database.set_initial_position()
        before = database.get_sim_account_summary()
        self.assertEqual(database.reset_sim_account(-1)['status'], 'error')
        self.assertEqual(database.get_sim_account_summary(), before)
        database.reset_sim_account()
        database.init_db()
        after = database.get_sim_account_summary()
        self.assertEqual(after['cash'], 100000.)
        self.assertEqual(after['total_fees'], 0.)
        self.assertEqual(after['trades'], [])


class LegacyMigrationTests(unittest.TestCase):
    def legacy(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.executescript('''
            CREATE TABLE sim_account(id INTEGER PRIMARY KEY,cash REAL,initial_cash REAL,updated_at TEXT);
            CREATE TABLE sim_position(symbol TEXT PRIMARY KEY,shares INTEGER,avg_cost REAL,updated_at TEXT);
            CREATE TABLE sim_trades(id INTEGER PRIMARY KEY,symbol TEXT,type TEXT,shares INTEGER,price REAL,amount REAL,fee REAL,pnl REAL,created_at TEXT,note TEXT);
            INSERT INTO sim_account VALUES(1,79458.38625,100000,'original');
            INSERT INTO sim_position VALUES('sh600036',500,42.,'original');
            INSERT INTO sim_trades VALUES(4,'sh600036','BUY',1000,42.,42000,10.5,0,'2026-10-28 14:30:00','original buy');
            INSERT INTO sim_trades VALUES(5,'sh600036','SELL',500,42.97,21485,16.11375,468.88625,'2026-10-29 14:52:19','original sell');
        ''')
        return c

    def test_migration_rebuilds_and_does_not_double_charge(self):
        c = self.legacy()
        before = [tuple(r) for r in c.execute('SELECT id,symbol,type,shares,price,created_at,note FROM sim_trades ORDER BY id')]
        report = migrate(c)
        self.assertEqual(report['new_cash'], 79457.76)
        self.assertEqual(report['new_total_fees'], 27.24)
        self.assertEqual(c.execute('SELECT pnl FROM sim_trades WHERE id=5').fetchone()[0], 463.22)
        after = [tuple(r) for r in c.execute('SELECT id,symbol,type,shares,price,created_at,note FROM sim_trades ORDER BY id')]
        self.assertEqual(before, after)
        dump = list(c.iterdump())
        self.assertIsNone(migrate(c))
        self.assertEqual(list(c.iterdump()), dump)
        c.close()

    def test_migration_rejects_missing_execution_history(self):
        c = self.legacy()
        c.execute('UPDATE sim_position SET shares=600')
        with self.assertRaisesRegex(ValueError, '持仓数量不一致'):
            migrate(c)
        self.assertEqual(c.execute('SELECT cash FROM sim_account').fetchone()[0], 79458.38625)
        self.assertEqual(c.execute('SELECT fee FROM sim_trades WHERE id=4').fetchone()[0], 10.5)
        c.close()


if __name__ == '__main__':
    unittest.main()
