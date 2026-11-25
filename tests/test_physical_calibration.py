"""Physical series storage and authoritative configured reference (no HA/cloud)."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import json
from pathlib import Path
import tempfile
import unittest

import test_assisted_calibration as assisted
from test_dashboard_layout import dashboard, registry

physical = importlib.import_module(assisted.PACKAGE + '.physical_calibration')
DAY = date(2026, 11, 25)
TRIALS = [{'portions': n, 'grams': g} for n, g in
          [(1,7),(1,7),(1,7),(3,19),(3,21),(4,28),(4,27),(5,34),(5,34),(10,68)]]


class PhysicalSeriesTests(unittest.TestCase):
    def test_real_series(self):
        record = physical.build_series(DAY, TRIALS, True)
        self.assertEqual(record['total_portions'], 37)
        self.assertEqual(record['total_grams'], 252)
        self.assertEqual(record['weighted_mean'], 6.8108)
        self.assertEqual(record['suggested_reference'], 6.8)
        self.assertTrue(physical.valid_series(record))

    def test_invalid_series(self):
        for trials in ([], TRIALS[:2], TRIALS * 4, [None]*3,
                       [{'portions': True, 'grams': 7}]*3,
                       [{'portions': 1.5, 'grams': 7}]*3,
                       [{'portions': 0, 'grams': 7}]*3,
                       [{'portions': 1, 'grams': True}]*3,
                       [{'portions': 1, 'grams': float('nan')}]*3,
                       [{'portions': 1, 'grams': 21}]*3,
                       [{'portions': 1, 'grams': 1}]*3):
            with self.subTest(trials=trials), self.assertRaises(ValueError):
                physical.build_series(DAY, trials, True)
        with self.assertRaises(ValueError):
            physical.build_series(DAY, TRIALS, False)

    def test_retention_and_duplicate(self):
        records = []
        for n in range(12):
            r = physical.build_series(DAY + timedelta(days=n), TRIALS, True)
            self.assertTrue(physical.append_series(records, r))
            self.assertFalse(physical.append_series(records, r))
        self.assertEqual(len(records), 10)
        self.assertEqual(records[0]['date'], '2026-11-27')

    def test_storage_and_invalid_diagnostics(self):
        state = assisted.initial(); state['samples'] = [6.8]
        state['pending'] = {'time': 100, 'count': 6, 'ack': False, 'day': DAY.isoformat()}
        r = physical.build_series(DAY, TRIALS, True)
        state['physical_series'] = [r, dict(r, suggested_reference=3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            assisted.store.save_state(path, state)
            loaded = assisted.store.load_state(path)
            self.assertEqual(loaded, dict(state, physical_series=[r]))
            del state['physical_series']
            assisted.store.save_state(path, state)
            self.assertEqual(assisted.store.load_state(path), state)

    def test_summary_does_not_claim_provenance(self):
        r = physical.build_series(DAY, TRIALS, True)
        self.assertFalse(physical.summary([], 6.8)['reference_matches_series'])
        self.assertFalse(physical.summary([r], 9)['reference_matches_series'])
        self.assertTrue(physical.summary([r], 6.8)['reference_matches_series'])

    def test_dashboard_and_translations(self):
        e = dashboard.find_entities(registry())
        for lang in ('fr', 'en'):
            view = dashboard.make_dashboard(e, lang)
            self.assertIn(e['physical_reference'], json.dumps(view))
            self.assertIn('diagnostic', dashboard.calibration_card(e, lang)['content'].lower())
        for filename in ('strings.json','translations/en.json','translations/fr.json'):
            d = json.loads((assisted.ROOT/filename).read_text())
            self.assertEqual(set(d['services']['record_physical_calibration']['fields']),
                             {'measurement_date','trials','confirmed'})
            self.assertIn('physical_reference', d['entity']['sensor'])


class PhysicalCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        f = assisted.CoordinatorTests(); f.setUp()
        self.c, self.error, self.today = f.c, f.error, f.today
        self.c.compensated = f.module.CompensatedCalibration()
        self.now = f.module.datetime.now(f.module.TZ)

    async def record(self):
        await self.c.async_record_physical_calibration(self.today, TRIALS, True)

    async def test_record_never_changes_reference_or_commands(self):
        self.c.entry.options = {'portion_weight': 9}
        await self.record()
        self.assertEqual(self.c.state['physical_series'][0]['suggested_reference'], 6.8)
        self.assertEqual(self.c.entry.options, {'portion_weight': 9})
        self.assertEqual(self.c.state['samples'], [])
        self.assertEqual(self.c.api.mock_calls, [])
        self.c._save.assert_awaited_once()
        self.c.async_request_refresh.assert_awaited_once()
        with self.assertRaises(self.error):
            await self.record()
        self.c._save.assert_awaited_once()

    async def test_failed_save_rolls_back(self):
        before = deepcopy(self.c.state)
        self.c._save.side_effect = OSError()
        with self.assertRaises(self.error):
            await self.record()
        self.assertEqual(self.c.state, before)
        self.c.async_request_refresh.assert_not_awaited()

    async def test_safety_and_future_date(self):
        self.c.entry.options = {'manual_enabled': True}
        with self.assertRaises(self.error): await self.record()
        self.c.entry.options = {}
        self.c.state['pending'] = {'count': 1}
        with self.assertRaises(self.error): await self.record()
        self.c.state['pending'] = None
        with self.assertRaises(self.error):
            await self.c.async_record_physical_calibration(self.today + timedelta(days=1), TRIALS, True)
        self.c._save.assert_not_awaited()

    async def test_reference_authoritative_and_explicit_change(self):
        await self.record()
        self.c.state['samples'] = [3,4,5]
        self.c.entry.options = {'portion_weight': 9, 'auto_calibration': True}
        data = {'portions_today': 8, 'schedule': [], 'bowl_weight': 0}
        result = self.c._enrich(deepcopy(data), self.now)
        self.assertEqual(result['calibration_weight'], 9)
        self.assertEqual(result['estimated_distributed'], 72)
        self.assertEqual(result['measured_weight'], 4)
        self.assertEqual(result['physical_reference'], 6.8)
        self.assertFalse(result['reference_matches_series'])
        self.c.entry.options = {'portion_weight': 6.8, 'auto_calibration': True}
        result = self.c._enrich(deepcopy(data), self.now)
        self.assertEqual(result['calibration_weight'], 6.8)
        self.assertEqual(result['estimated_distributed'], 54.4)
        self.assertTrue(result['reference_matches_series'])
        await self.c.async_reset_calibration()
        self.assertEqual(self.c.state['samples'], [])
        self.assertEqual(len(self.c.state['physical_series']), 1)
