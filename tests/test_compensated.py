"""Experimental mass balance: offline, no actuator or cloud."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from test_camera_transport import PACKAGE
import test_assisted_calibration as assisted_tests

comp = importlib.import_module(PACKAGE + '.compensated')
store = importlib.import_module(PACKAGE + '.state_store')
DUE = datetime(2026, 11, 24, 21, tzinfo=comp.TZ)


def data(**changes):
    return dict(dict(online=True, device_status=1, warning_mask=0, fault_mask=0,
        schedule_date=DUE.date().isoformat(), portions_today=7, bowl_weight=0,
        intake_today=44, schedule=[dict(status=True, repeatType=1, expireStatus=False,
        supperFlag=0, planFinishStatus=False, feedingTime='21:00', portions=5)]), **changes)


class CompensatedTests(unittest.TestCase):
    def setUp(self):
        self.tracker = comp.CompensatedCalibration()
        self.d = data()

    def at(self, seconds, duration=5, **changes):
        self.d.update(changes)
        return self.tracker.observe(self.d, DUE + timedelta(seconds=seconds), duration)

    def before(self):
        self.assertIsNone(self.at(-90))
        self.assertIsNone(self.at(-60))
        self.assertEqual(self.tracker.status, 'baseline_ready')

    def completed(self):
        self.d['schedule'][0]['planFinishStatus'] = True
        self.d.update(portions_today=12, bowl_weight=13, intake_today=64)

    def consolidate(self, start=160, end=1560, **changes):
        for t in [*range(start, end, 60), end]:
            record = self.at(t, **changes)
            if record is not None:
                self.assertGreaterEqual(t, comp.MIN_FINAL_SECONDS)
                return record
        return None

    def sample(self):
        self.before(); self.completed()
        self.assertIsNone(self.at(100))
        self.assertIsNone(self.at(130, bowl_weight=3, intake_today=74))
        return self.consolidate()

    def test_real_example_eating_continues(self):
        r = self.sample()
        self.assertEqual(r['weight'], 6.6)
        self.assertEqual(r['distributed'], 33)
        self.assertEqual(r['portions'], 5)
        self.assertTrue(comp.valid_record(r))
        self.assertIsNone(self.at(1620))

    def test_food_present_before_meal_and_eaten(self):
        self.d['bowl_weight'] = 10; self.before(); self.completed()
        self.at(100, bowl_weight=14, intake_today=74)
        self.assertIsNone(self.at(130, bowl_weight=12, intake_today=76))
        r = self.consolidate()
        self.assertEqual(r['weight'], 6.8)

    def test_unstable_post_waits_for_counter_sync(self):
        self.before(); self.completed(); self.at(100, intake_today=44)
        self.assertIsNone(self.at(130, intake_today=64))
        self.assertEqual(self.consolidate()['weight'], 6.6)

    def test_no_sample_without_stable_pre(self):
        self.at(-30); self.completed()
        self.assertIsNone(self.at(100)); self.assertIsNone(self.at(130))

    def test_stale_baseline_rejected(self):
        self.at(-300); self.at(-270); self.completed()
        self.assertIsNone(self.at(100)); self.assertIsNone(self.at(130))

    def test_schedule_not_finished(self):
        self.before(); self.d.update(portions_today=12, bowl_weight=33)
        self.assertIsNone(self.at(100)); self.assertIsNone(self.at(130))

    def test_counter_mismatch(self):
        self.before(); self.completed()
        self.assertIsNone(self.at(100, portions_today=13)); self.assertIsNone(self.at(130))

    def test_counter_reset(self):
        self.before(); self.completed()
        self.assertIsNone(self.at(100, intake_today=2)); self.assertIsNone(self.at(130, intake_today=64))

    def test_bad_reading_and_fault(self):
        for change in ({'bowl_weight': None}, {'warning_mask': 1}, {'online': False}, {'fault_mask': 1}, {'intake_today': float('nan')}):
            with self.subTest(change=change):
                self.setUp(); self.before(); self.completed()
                self.assertIsNone(self.at(100, **change)); self.assertIsNone(self.at(130))

    def test_slow_snapshot_invalidates_baseline(self):
        self.before(); self.completed()
        self.assertIsNone(self.at(100, duration=31)); self.assertIsNone(self.at(130))

    def test_program_change_and_unsupported(self):
        self.before(); self.completed(); self.d['schedule'][0]['portions']=6
        self.assertIsNone(self.at(100)); self.assertIsNone(self.at(130))
        self.setUp(); self.d['schedule'][0]['repeatType']=2
        self.assertIsNone(self.at(-90)); self.assertEqual(self.tracker.status, 'unsupported_schedule')

    def test_stale_day(self):
        self.before(); self.completed()
        self.assertIsNone(self.at(100, schedule_date='2026-11-23'))
        self.assertIsNone(self.at(130, schedule_date=DUE.date().isoformat()))

    def test_out_of_range(self):
        self.before(); self.completed()
        self.at(100, bowl_weight=110); self.assertIsNone(self.at(130))
        r = self.consolidate(end=1740)
        self.assertEqual(r['quality'], 'rejected')
        self.assertEqual(r['reason'], 'out_of_range')

    def test_delayed_counter_and_peak_recovery(self):
        self.before(); self.completed()
        self.at(30, bowl_weight=33, intake_today=44)
        self.at(90, bowl_weight=15, intake_today=44)
        for t in range(150, 750, 60):
            self.assertIsNone(self.at(t, bowl_weight=15, intake_today=44))
        self.assertIsNone(self.at(750, bowl_weight=0, intake_today=77))
        r = self.consolidate(start=810)
        self.assertEqual(r['quality'], 'accepted')
        self.assertEqual(r['weight'], 6.6)
        self.assertEqual(r['peak']['bowl'], 33)

    def test_observed_peak_excludes_underestimate(self):
        self.before(); self.completed()
        self.at(30, bowl_weight=33, intake_today=44)
        self.at(90, bowl_weight=15, intake_today=44)
        r = self.consolidate(start=150, end=1740)
        self.assertEqual(r['quality'], 'rejected')
        self.assertEqual(r['reason'], 'below_observed_peak')
        records = []
        self.assertTrue(comp.append_observation(records, r))
        self.assertEqual(comp.diagnostic_summary(records), {'compensated_samples':0,'compensated_weight':None})

    def test_four_portion_user_case_rejected_if_peak_not_explained(self):
        self.d['schedule'][0]['portions'] = 4
        self.d.update(portions_today=4, intake_today=27)
        self.before()
        self.d['schedule'][0]['planFinishStatus'] = True
        self.at(30, portions_today=8, bowl_weight=23)
        self.at(90, bowl_weight=15)
        r = self.consolidate(start=150, end=1740)
        self.assertEqual(r['weight'], 3.75)
        self.assertEqual(r['peak']['bowl'], 23)
        self.assertEqual(r['reason'], 'below_observed_peak')
        self.assertTrue(comp.valid_record(r))
        self.assertEqual(comp.diagnostic_summary([r]), {'compensated_samples':0,'compensated_weight':None})

    def test_legacy_measurement_preserved_but_excluded(self):
        legacy = {'day': '2026-11-25', 'due': 1795586400, 'portions': 4,
                  'before': {'timestamp':1795586397.138378,'count':4,'bowl':0,'intake':27},
                  'after': {'timestamp':1795586582.866366,'count':8,'bowl':15,'intake':27},
                  'distributed':15,'weight':3.75}
        records = []
        self.assertTrue(comp.append_observation(records, legacy))
        self.assertEqual(comp.diagnostic_summary(records), {'compensated_samples':0,'compensated_weight':None})
        self.assertTrue(comp.append_observation(records,self.sample()))
        self.assertEqual(comp.diagnostic_summary(records), {'compensated_samples':1,'compensated_weight':6.6})
        state = {'samples':[6.8], 'pending':None, 'last_attempt':0, 'last_result':'none', 'compensated_records':records}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'; store.save_state(path,state)
            self.assertEqual(store.load_state(path),state)

    def test_gap_cannot_be_treated_as_stability(self):
        self.before(); self.completed(); self.at(100); self.at(130)
        self.assertIsNone(self.at(1500))
        self.assertIsNone(self.tracker.baseline)

    def test_extended_window_is_not_global(self):
        self.completed()
        for seconds, expected in [(-361,False),(-360,True),(600,True),(1800,True),(1801,False)]:
            self.assertEqual(comp.observation_window(self.d,DUE+timedelta(seconds=seconds)),expected)

    def test_no_duplicate_and_independent_storage(self):
        r = self.sample(); records = []
        self.assertTrue(comp.append_observation(records, r)); self.assertFalse(comp.append_observation(records, r))
        state = {'samples':[7,7,7], 'pending':None, 'last_attempt':100, 'last_result':'none', 'compensated_records':records}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'; store.save_state(path,state)
            self.assertEqual(store.load_state(path),state)
            state['compensated_records'] = records + [dict(r, weight=18)]
            store.save_state(path,state); loaded=store.load_state(path)
            self.assertEqual(len(loaded['compensated_records']),1)
            self.assertEqual(loaded['samples'],[7,7,7])
        self.assertEqual(comp.diagnostic_summary(records), {'compensated_samples':1,'compensated_weight':6.6})

    def test_diagnostics_do_not_change_effective_weight(self):
        r = self.sample()
        # Reuse the existing coordinator fixture without adding HA dependencies.
        fixture = assisted_tests.CoordinatorTests(); fixture.setUp(); c = fixture.c
        c.compensated = self.tracker
        c.state['samples'] = [7,7,7]
        before = c._enrich(deepcopy(self.d), DUE + timedelta(seconds=130))
        c.state['compensated_records'] = [r]
        after = c._enrich(deepcopy(self.d), DUE + timedelta(seconds=130))
        for key in ('calibration_weight','calibration_samples','estimated_distributed','budget','forecast','decision','manual_state'):
            self.assertEqual(before[key],after[key],key)
        self.assertEqual(after['calibration_weight'],9)
        self.assertEqual(after['compensated_weight'],6.6)
        self.assertEqual(c.api.mock_calls,[])


class CompensatedCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_polling_collects_diagnostics_only(self):
        from unittest.mock import AsyncMock
        fixture = assisted_tests.CoordinatorTests(); fixture.setUp(); c = fixture.c
        c.compensated = comp.CompensatedCalibration()
        c.cal.observe.return_value = None
        c.cal.candidate = None
        c._notify = AsyncMock()
        before = data()
        after = data(portions_today=12, bowl_weight=13, intake_today=64)
        after['schedule'][0]['planFinishStatus'] = True
        c._snapshot = AsyncMock(side_effect=[(deepcopy(d), DUE+timedelta(seconds=t))
            for d,t in [(before,-90),(before,-60),(after,100),(after,130)] + [(after,t) for t in range(160,1560,60)] + [(after,1560)]])
        for _ in range(5+len(range(160,1560,60))):
            result = await c._async_update_data()
        self.assertEqual(c._snapshot.await_count,5+len(range(160,1560,60)))
        self.assertEqual(c.update_interval,timedelta(seconds=60))
        self.assertEqual(c.state['samples'],[])
        self.assertEqual(result['compensated_samples'],1)
        self.assertEqual(result['compensated_weight'],6.6)
        self.assertEqual(result['calibration_weight'],9)
        c._save.assert_awaited_once()
        self.assertEqual(c.api.mock_calls,[])

    async def test_manual_option_disables_collection(self):
        from unittest.mock import AsyncMock
        fixture = assisted_tests.CoordinatorTests(); fixture.setUp(); c = fixture.c
        c.compensated = comp.CompensatedCalibration()
        c.cal.observe.return_value = None
        c.cal.candidate = None
        c._notify = AsyncMock()
        c.entry.options = {'manual_enabled': True}
        c._snapshot = AsyncMock(return_value=(data(),DUE-timedelta(seconds=60)))
        result = await c._async_update_data()
        self.assertEqual(result['compensated_samples'],0)
        self.assertIsNone(c.compensated.baseline)
        c._save.assert_not_awaited()
