import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.recommendations import closed_bars, record, recent, evaluate, performance


def bars():
    result = []
    for day in range(3):
        for start in [datetime(2026, 11, 2 + day, 9, 35), datetime(2026, 11, 2 + day, 13, 5)]:
            for n in range(24):
                result.append(dict(datetime=str(start + timedelta(minutes=5 * n)), open=10., high=10.1,
                                   low=9.9, close=10., volume=1000., amount=10000.))
    return result


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.db'
        self.rows = bars()
        self.signal = dict(index=0, datetime=self.rows[0]['datetime'], type='BUY', strategy='boll_reversion',
                           price=10., reason='test', ret_60m=999., tp_sl_ret=999.)
        self.result = {'signals': [self.signal], 'data': [], 'strategy_meta': {}}
        self.now = datetime(2026, 11, 4, 16)

    def tearDown(self):
        self.tmp.cleanup()

    def replay(self):
        return record('sz000001', self.result, self.rows, [], self.now, self.path, 'historical_replay')

    def test_open_bar_and_publication_delay(self):
        self.assertEqual(len(closed_bars(self.rows, datetime(2026, 11, 2, 9, 35, 4))), 0)
        self.assertEqual(len(closed_bars(self.rows, datetime(2026, 11, 2, 9, 35, 5))), 1)

    def test_stale_is_not_live(self):
        self.assertEqual(record('sz000001', self.result, self.rows, [], self.now, self.path), 0)

    def test_immutable_and_no_future_returns(self):
        self.assertEqual(self.replay(), 1)
        self.signal['price'] = 20.
        self.assertEqual(self.replay(), 0)
        rec = recent(path=self.path)[0]
        self.assertEqual(rec['signal_price'], 10.)
        self.assertNotIn('ret_60m', rec['snapshot']['signal'])
        self.assertNotIn('tp_sl_ret', rec['snapshot']['signal'])

    def test_origin_separation(self):
        self.replay()
        record('sz000001', self.result, self.rows, [], datetime(2026, 11, 2, 9, 35, 10), self.path)
        self.assertEqual(len(recent(path=self.path)), 2)

    def test_t1_is_after_entry_date(self):
        self.replay()
        evaluate('sz000001', self.rows, self.now, self.path)
        outcome = next(x['details'] for x in recent(path=self.path)[0]['outcomes'] if x['mode'] == 'new_position_t1')
        self.assertGreater(outcome['exit_bar_end'][:10], outcome['entry_bar_end'][:10])
        self.assertLess(outcome['net_pct'], 0.)

    def test_pending_and_idempotent_outcomes(self):
        self.replay()
        self.assertEqual(evaluate('sz000001', self.rows[:3], self.now, self.path), 0)
        self.assertGreater(evaluate('sz000001', self.rows, self.now, self.path), 0)
        self.assertEqual(evaluate('sz000001', self.rows, self.now, self.path), 0)

    def test_live_fill_occurs_after_first_seen(self):
        seen = datetime(2026, 11, 2, 9, 35, 10)
        record('sz000001', self.result, self.rows, [], seen, self.path)
        evaluate('sz000001', self.rows, self.now, self.path)
        detail = recent(path=self.path)[0]['outcomes'][0]['details']
        self.assertGreaterEqual(datetime.fromisoformat(detail['entry_bar_end']) - timedelta(minutes=5), seen)

    def test_sell_measures_inventory_not_short(self):
        self.signal['type'] = 'SELL'
        self.replay()
        rows = [dict(r) for r in self.rows]
        for row in rows[2:]:
            row['open'] = 9.
        evaluate('sz000001', rows, self.now, self.path)
        outcomes = recent(path=self.path)[0]['outcomes']
        self.assertFalse(any(x['mode'] == 'new_position_t1' for x in outcomes))
        self.assertGreater(outcomes[0]['details']['net_pct'], 0)
        self.assertEqual(outcomes[0]['details']['interpretation'], 'sell_inventory_then_buy_back')
        self.assertTrue(performance(self.path))


if __name__ == '__main__':
    unittest.main()
