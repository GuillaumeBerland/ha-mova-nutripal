"""Daily mass balance, persisted diagnostic history and read-only dashboard."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock
from test_camera_transport import PACKAGE
from test_dashboard_layout import dashboard, registry
import test_assisted_calibration as assisted

balance = importlib.import_module(PACKAGE + '.daily_balance')
store = importlib.import_module(PACKAGE + '.state_store')
DAY = datetime(2026, 11, 25, tzinfo=balance.TZ)


def data(bowl=0, intake=0, portions=0, **kwargs):
    return dict(dict(online=True, device_status=1, warning_mask=0, fault_mask=0,
                     bowl_weight=bowl, intake_today=intake, portions_today=portions), **kwargs)


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tracker = balance.DailyBalance()

    def read(self, when, d, duration=5, weight=9):
        return self.tracker.observe(d, when, duration, weight, 100)

    def begin(self):
        self.read(DAY-timedelta(minutes=2), data(13,64,12))
        self.read(DAY+timedelta(minutes=2), data(13,0,0,intake_yesterday=64,portions_yesterday=12))
        self.assertEqual(self.tracker.opening,13)

    def test_midday_install_does_not_invent_opening(self):
        d=data(13,64,12)
        self.read(DAY+timedelta(hours=10),d)
        s=self.tracker.summary(d, DAY)
        self.assertEqual(s['daily_quality'],'missing_boundary')
        self.assertIsNone(s['daily_reconstructed'])

    def test_reconstructed_and_corrected(self):
        self.begin(); d=data(18,49,8,estimated_distributed=72,forecast=126,decision='budget_reached')
        now=DAY+timedelta(hours=8); self.read(now,d)
        s=self.tracker.summary(d,now)
        self.assertEqual(s['daily_reconstructed'],54)
        self.assertEqual(s['daily_portion_weight'],6.75)
        self.assertEqual(s['daily_difference'],-18)
        self.assertEqual(s['daily_corrected_forecast'],108)
        self.assertEqual(s['daily_quality'],'reconstructed')
        self.assertEqual(d['forecast'],126)

    def test_zero_is_real_when_boundary_known(self):
        self.begin(); d=data(13,0,0)
        self.assertEqual(self.tracker.summary(d,DAY)['daily_reconstructed'],0)
        self.assertIsNone(self.tracker.summary(d,DAY)['daily_portion_weight'])

    def test_complete_day_archive(self):
        self.begin(); self.read(DAY+timedelta(hours=23,minutes=58),data(8,100,14),weight=7)
        self.read(DAY+timedelta(days=1,minutes=2),data(8,0,0,intake_yesterday=100,portions_yesterday=14))
        r=self.tracker.history[-1]
        self.assertEqual((r['day'],r['reconstructed'],r['theoretical'],r['difference'],r['consumed']),('2026-11-25',95,98,-3,100))
        self.assertEqual(self.tracker.history[0]['quality'],'missing_boundary')
        self.assertIsNone(self.tracker.history[0]['reconstructed'])

    def test_boundary_changed_bowl_or_counters_rejected(self):
        for changes in ({'bowl_weight':12},{'intake_yesterday':65},{'portions_yesterday':11},{'intake_today':1},{'portions_today':1}):
            with self.subTest(changes=changes):
                self.tracker=balance.DailyBalance(); self.read(DAY-timedelta(minutes=2),data(13,64,12))
                d=data(13,0,0,intake_yesterday=64,portions_yesterday=12); d.update(changes)
                self.read(DAY+timedelta(minutes=2),d)
                self.assertIsNone(self.tracker.opening)
                self.assertIsNone(self.tracker.history[-1]['reconstructed'])

    def test_midnight_gap_rejected(self):
        self.read(DAY-timedelta(minutes=7),data(13,64,12))
        self.read(DAY+timedelta(minutes=1),data(13,0,0,intake_yesterday=64,portions_yesterday=12))
        self.assertIsNone(self.tracker.opening)

    def test_multiday_gap_no_fake_history(self):
        self.begin(); self.read(DAY+timedelta(days=3,minutes=1),data(13,0,0,intake_yesterday=88,portions_yesterday=14))
        self.assertEqual(len(self.tracker.history),2)
        self.assertIsNone(self.tracker.history[-1]['consumed'])
        self.assertIsNone(self.tracker.opening)

    def test_counter_regression_invalidates_day(self):
        self.begin(); self.read(DAY+timedelta(hours=7),data(13,25,4))
        d=data(13,23,3); now=DAY+timedelta(hours=8); self.read(now,d)
        self.assertEqual(self.tracker.summary(d,now)['daily_quality'],'inconsistent')
        self.assertIsNone(self.tracker.summary(d,now)['daily_reconstructed'])

    def test_invalid_reading_does_not_update(self):
        self.begin(); original=self.tracker.export()
        for d,duration in [(data(3,4,1,online=False),5),(data(3,4,1),31),(data(None,4,1),5),(data(3,4,True),5),(data(3,4,1,device_status=2),5)]:
            self.assertFalse(self.read(DAY+timedelta(hours=1),d,duration))
            self.assertEqual(self.tracker.export(),original)

    def test_negative_balance_inconsistent(self):
        self.begin(); d=data(0,1,0); now=DAY+timedelta(hours=1); self.read(now,d)
        self.assertEqual(self.tracker.summary(d,now)['daily_quality'],'inconsistent')

    def test_uncertain_schedule_has_no_corrected_forecast(self):
        self.begin(); d=data(18,49,8,estimated_distributed=72,forecast=126,decision='schedule_uncertain')
        now=DAY+timedelta(hours=8); self.read(now,d)
        self.assertIsNone(self.tracker.summary(d,now)['daily_corrected_forecast'])
        self.assertEqual(self.tracker.summary(d,now)['daily_reconstructed'],54)

    def test_stale_snapshot_not_used(self):
        self.begin(); d=data(13,0,0)
        self.assertIsNone(self.tracker.summary(d,DAY,fresh=False)['daily_reconstructed'])
        self.assertIsNone(self.tracker.summary(data(12,0,0),DAY)['daily_reconstructed'])
        self.assertIsNone(self.tracker.summary(d,DAY+timedelta(days=1))['daily_reconstructed'])

    def test_storage_roundtrip_and_bad_file(self):
        self.begin()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'daily.json'; store.save_state(p,self.tracker.export())
            self.assertEqual(balance.load_daily(p).export(),self.tracker.export())
            p.write_text('{bad json')
            with self.assertRaises(ValueError): balance.load_daily(p)

    def test_retention_30_days(self):
        self.begin()
        for i in range(35):
            self.read(DAY+timedelta(days=i,hours=23,minutes=58),data(13,98,14))
            self.read(DAY+timedelta(days=i+1,minutes=2),data(13,0,0,intake_yesterday=98,portions_yesterday=14))
        self.assertEqual(len(self.tracker.history),30)
        self.assertEqual(self.tracker.history[-1]['reconstructed'],98)
        self.assertEqual(len({r['day'] for r in self.tracker.history}),30)

    def test_dst_day_uses_local_midnight(self):
        now=datetime(2026,3,29,tzinfo=balance.TZ)
        self.read(now-timedelta(minutes=2),data(13,64,12))
        self.read(now+timedelta(minutes=2),data(13,0,0,intake_yesterday=64,portions_yesterday=12))
        self.read(now+timedelta(hours=23,minutes=58),data(13,98,14))
        self.read(now+timedelta(days=1,minutes=2),data(13,0,0,intake_yesterday=98,portions_yesterday=14))
        self.assertEqual(self.tracker.history[-1]['reconstructed'],98)

    def test_dashboard_optional_and_labels(self):
        e=dashboard.find_entities(registry())
        self.assertEqual(e['forecast'], 'sensor.renamed_forecast')
        self.assertEqual(e['daily_corrected_forecast'], 'sensor.renamed_daily_corrected_forecast')
        for lang in ('fr','en'):
            v=dashboard.make_dashboard(e,lang)
            self.assertEqual(v['views'][2]['path'],'feeding-history')
            main=dashboard.daily_balance_card(e,lang)
            self.assertIn(e['daily_reconstructed'],main['entity_id'])
            self.assertIn(e['calibration_weight'],main['entity_id'])
            self.assertIn('🟩',main['content'])
            self.assertIn(e['daily_history_count'],v['views'][2]['sections'][0]['cards'][2]['entity_id'])
        old=dashboard.make_dashboard(dashboard.find_entities(registry(False)))
        self.assertEqual(len(old['views']),3)
        self.assertNotIn('daily_reconstructed',json.dumps(old))


class DailyCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_failure_does_not_disable_existing_planner(self):
        fixture=assisted.CoordinatorTests(); fixture.setUp(); c=fixture.c
        c.compensated=c.__class__.__init__.__globals__['CompensatedCalibration']()
        c.cal.observe.return_value=None; c.cal.candidate=None
        c._notify=AsyncMock(); c.hass.async_add_executor_job.side_effect=OSError('disk')
        d=data(13,0,0, schedule=[])
        c._snapshot=AsyncMock(return_value=(deepcopy(d),DAY+timedelta(hours=8)))
        result=await c._async_update_data()
        self.assertTrue(c.daily_storage_failed)
        self.assertFalse(c.storage_failed)
        self.assertEqual(result['daily_quality'],'storage_error')
        self.assertIsNone(result['daily_reconstructed'])
        self.assertEqual(result['estimated_distributed'],0)
        self.assertEqual(c.api.mock_calls,[])
        c._save.assert_not_awaited()

    async def test_daily_diagnostics_do_not_affect_existing_planner(self):
        fixture=assisted.CoordinatorTests(); fixture.setUp(); c=fixture.c
        c.compensated=c.__class__.__init__.__globals__['CompensatedCalibration']()
        d=data(18,49,8,schedule=[],_daily_observed=True)
        now=DAY+timedelta(hours=8)
        before=c._enrich(deepcopy(d),now)
        c.daily.observe(data(13,64,12),DAY-timedelta(minutes=2),5,9,100)
        c.daily.observe(data(13,0,0,intake_yesterday=64,portions_yesterday=12),DAY+timedelta(minutes=2),5,9,100)
        c.daily.observe(d,now,5,9,100)
        after=c._enrich(deepcopy(d),now)
        self.assertEqual(after['daily_reconstructed'],54)
        for k in ('estimated_distributed','forecast','budget','decision','calibration_weight','manual_state'):
            self.assertEqual(before[k],after[k])
        self.assertEqual(c.api.mock_calls,[])
