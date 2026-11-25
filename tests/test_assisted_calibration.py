"""Assisted calibration tests: local storage and coordinator, no real HA/cloud."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_camera_transport import PACKAGE

store = importlib.import_module(PACKAGE + '.state_store')
cal = importlib.import_module(PACKAGE + '.calibration')
ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'mova_nutripal'
DAY = date(2026, 11, 24)


def initial():
    return {'samples': [], 'pending': None, 'last_attempt': 100, 'last_result': 'none'}


def measurement(**changes):
    return store.assisted_measurement(**dict(dict(day=DAY, today=DAY, portions=5,
        daily_counter=12, weight_before=0, weight_after=34, confirmed=True), **changes))


class AssistedSampleTests(unittest.TestCase):
    def test_real_weighing(self):
        value, detail = measurement()
        self.assertEqual(value, 6.8)
        self.assertEqual((detail['start_count'], detail['end_count']), (7, 12))
        self.assertEqual(detail['source'], 'assisted')
        self.assertEqual(measurement(weight_before=10, weight_after=44)[0], 6.8)

    def test_invalid_measurements(self):
        for changes in ({'confirmed': False}, {'confirmed': 1}, {'portions': True},
                        {'portions': 0}, {'portions': 2.5}, {'daily_counter': 4},
                        {'daily_counter': 12.5}, {'weight_before': -1}, {'weight_after': 0},
                        {'weight_before': 34}, {'weight_after': 5}, {'weight_after': 101},
                        {'weight_after': float('nan')}, {'weight_after': float('inf')},
                        {'day': DAY + timedelta(days=1)}, {'day': DAY-timedelta(days=31)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                measurement(**changes)

    def test_duplicate_or_overlap_rejected_across_sources(self):
        state = initial()
        self.assertTrue(store.append_sample(state, *measurement()))
        self.assertFalse(store.append_sample(state, *measurement()))
        for start, end in [(6, 8), (7, 12), (10, 13)]:
            self.assertFalse(store.append_sample(state, 7, {'source': 'passive',
                'day': DAY.isoformat(), 'start_count': start, 'end_count': end}))
        self.assertEqual(state['samples'], [6.8])
        self.assertTrue(store.append_sample(state, 7, {'source': 'passive',
            'day': DAY.isoformat(), 'start_count': 1, 'end_count': 7}))
        self.assertTrue(store.append_sample(state, *measurement(day=DAY-timedelta(days=1))))

    def test_passive_first_rejects_assisted_overlap(self):
        state = initial()
        self.assertTrue(store.append_sample(state, 7, {'source': 'passive',
            'day': DAY.isoformat(), 'start_count': 7, 'end_count': 12}))
        self.assertFalse(store.append_sample(state, *measurement()))

    def test_shared_median_with_three_measurements(self):
        state = initial()
        for day, after in [(DAY, 34), (DAY-timedelta(days=1), 35), (DAY-timedelta(days=2), 36)]:
            self.assertTrue(store.append_sample(state, *measurement(day=day, weight_after=after)))
        self.assertEqual(cal.effective_weight(state['samples'], 9), 7)
        self.assertEqual(cal.effective_weight(state['samples'][:2], 9), 9)
        self.assertEqual(cal.effective_weight(state['samples'], 9, False), 9)

    def test_legacy_preservation_and_bounded_history(self):
        state = initial(); state['samples'] = [9, 8]
        self.assertEqual(store.calibration_history(state)[0], {'weight': 9, 'source': 'legacy'})
        for i in range(16):
            self.assertTrue(store.append_sample(state, *measurement(day=DAY-timedelta(days=i))))
        self.assertEqual(len(state['samples']), 15)
        self.assertEqual(len(state['sample_details']), 15)
        self.assertTrue(all(x['source'] == 'assisted' for x in store.calibration_history(state)))

    def test_persistence_preserves_pending_and_cooldown(self):
        state = initial(); state['samples'] = [7]
        state['pending'] = {'time': 100, 'count': 6, 'ack': False, 'day': DAY.isoformat()}
        state['last_result'] = 'pending'
        store.append_sample(state, *measurement())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            store.save_state(path, state)
            self.assertEqual(store.load_state(path), state)
        self.assertEqual(state['last_attempt'], 100)
        self.assertEqual(state['pending']['count'], 6)

    def test_corrupt_metadata_rejected(self):
        state = initial(); store.append_sample(state, *measurement())
        for details in ([], [{'source': 'bogus'}], [dict(state['sample_details'][0], after=33)],
                        [dict(state['sample_details'][0], start_count=12)]):
            with self.subTest(details=details), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'state.json'; broken = deepcopy(state)
                broken['sample_details'] = details
                store.save_state(path, broken)
                with self.assertRaises(ValueError): store.load_state(path)

    def test_service_translations(self):
        fields = {'measurement_date','portions','daily_counter','weight_before','weight_after','confirmed'}
        for filename in ('strings.json','translations/en.json','translations/fr.json'):
            service = json.loads((ROOT/filename).read_text())['services']['add_calibration_measurement']
            self.assertEqual(set(service['fields']), fields)
            self.assertTrue(service['name'])


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        exceptions = types.ModuleType('homeassistant.exceptions')
        exceptions.HomeAssistantError = type('HomeAssistantError', (Exception,), {})
        update = types.ModuleType('homeassistant.helpers.update_coordinator')
        update.DataUpdateCoordinator = type('DataUpdateCoordinator', (), {})
        update.UpdateFailed = type('UpdateFailed', (Exception,), {})
        with patch.dict(sys.modules, {'homeassistant.exceptions': exceptions,
                                     'homeassistant.helpers.update_coordinator': update}):
            self.module = importlib.import_module(PACKAGE+'.coordinator')
        self.error = self.module.HomeAssistantError
        self.c = self.module.NutriPalCoordinator.__new__(self.module.NutriPalCoordinator)
        self.c.lock = asyncio.Lock(); self.c.stopping = False; self.c.storage_failed = False
        self.c.hass = Mock(is_running=True); self.c.entry = Mock(options={})
        self.c.daily = self.module.DailyBalance(); self.c.daily_storage_failed = False
        self.c.daily_path = "unused-test-path"
        self.c.hass.async_add_executor_job = AsyncMock()
        self.c.state = initial(); self.c.cal = Mock(); self.c.api = Mock()
        self.c._save = AsyncMock(); self.c.async_request_refresh = AsyncMock()
        self.today = self.module.datetime.now(self.module.TZ).date()

    async def record(self):
        await self.c.async_add_calibration_measurement(self.today, 5, 12, 0, 34, True)

    async def test_success_no_actuator_and_duplicate_rejected(self):
        await self.record()
        self.assertEqual(self.c.state['samples'], [6.8])
        self.c._save.assert_awaited_once(); self.c.async_request_refresh.assert_awaited_once()
        self.c.cal.reset.assert_called_once(); self.assertEqual(self.c.api.mock_calls, [])
        with self.assertRaises(self.error): await self.record()
        self.c._save.assert_awaited_once()

    async def test_manual_enabled_or_pending_blocks_recording(self):
        self.c.entry.options = {'manual_enabled': True}
        with self.assertRaises(self.error): await self.record()
        self.c.entry.options = {}; self.c.state['pending'] = {'count': 7}
        with self.assertRaises(self.error): await self.record()
        self.c._save.assert_not_awaited(); self.assertEqual(self.c.api.mock_calls, [])

    async def test_failed_save_restores_state(self):
        before = deepcopy(self.c.state); self.c._save.side_effect = OSError()
        with self.assertRaises(self.error): await self.record()
        self.assertEqual(self.c.state, before); self.c.async_request_refresh.assert_not_awaited()

    async def test_reset_clears_both_samples_and_metadata(self):
        await self.record(); await self.c.async_reset_calibration()
        self.assertEqual(self.c.state['samples'], []); self.assertEqual(self.c.state['sample_details'], [])
        self.assertEqual(self.c.state['last_attempt'], 100)
