"""Representative-day flags and program/physical display, independent of feeding."""
from copy import deepcopy
from datetime import timedelta
import json
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from test_daily_balance import DAY, data, balance
from test_dashboard_layout import dashboard, registry
from test_physical_calibration import TRIALS, physical
import test_assisted_calibration as assisted


class ExcludedDayTests(TestCase):
    def complete_opening(self):
        t = balance.DailyBalance()
        t.observe(data(0, 76, 12), DAY-timedelta(minutes=2), 5, 6.8, 100)
        t.observe(data(0, 0, 0, intake_yesterday=76, portions_yesterday=12), DAY+timedelta(minutes=2), 5, 6.8, 100)
        return t

    def test_flag_keeps_raw_values_and_suppresses_reconstruction(self):
        t = self.complete_opening()
        now = DAY+timedelta(hours=18)
        d = data(0,309,48,estimated_distributed=326.4,forecast=346.8,decision='budget_reached')
        t.observe(d, now, 5, 6.8, 100)
        self.assertEqual(t.summary(d,now)['daily_reconstructed'],309)
        raw = deepcopy(t.last)
        t.mark_day(DAY.date(), DAY.date(), 'Calibration trials')
        s = t.summary(d,now)
        self.assertEqual(s['daily_quality'],'excluded')
        for k in ('daily_reconstructed','daily_portion_weight','daily_difference','daily_corrected_forecast'):
            self.assertIsNone(s[k])
        self.assertEqual(t.last,raw)
        self.assertEqual(s['daily_current']['consumed'],309)
        self.assertEqual(d['forecast'],346.8)

    def test_archive_mark_and_reload(self):
        t = self.complete_opening()
        t.observe(data(0,309,48), DAY+timedelta(hours=23,minutes=58),5,6.8,100)
        t.mark_day(DAY.date(), DAY.date(),'Calibration trials')
        tomorrow=DAY+timedelta(days=1,minutes=2)
        d=data(0,0,0,intake_yesterday=309,portions_yesterday=48)
        t.observe(d,tomorrow,5,6.8,100)
        restored=balance.DailyBalance(t.export())
        s=restored.summary(d,tomorrow)
        self.assertEqual(s['daily_quality'],'reconstructed')
        self.assertTrue(s['daily_yesterday_excluded'])
        self.assertEqual(s['daily_history'][-1]['excluded_reason'],'Calibration trials')
        self.assertEqual(s['daily_history'][-1]['consumed'],309)
        self.assertEqual(s['daily_reconstructed'],0)
        self.assertEqual(restored.export(),t.export())

    def test_old_state_migrates_and_validation(self):
        state=self.complete_opening().export(); state.pop('excluded_days')
        t=balance.DailyBalance(state)
        self.assertEqual(t.excluded_days,{})
        for day,reason in [(DAY.date()+timedelta(days=1),'x'),(DAY.date()-timedelta(days=31),'x'),(DAY.date(),'  '),(DAY.date(),'x'*121)]:
            with self.assertRaises(ValueError): t.mark_day(day,DAY.date(),reason)
        self.assertTrue(t.mark_day(DAY.date(),DAY.date(),'trial'))
        self.assertFalse(t.mark_day(DAY.date(),DAY.date(),'trial'))
        t.prune_marks(DAY.date()+timedelta(days=31))
        self.assertEqual(t.excluded_days,{})

    def test_dashboard_uses_physical_card_and_program_fallback(self):
        e=dashboard.find_entities(registry())
        for lang in ('fr','en'):
            card=dashboard.daily_balance_card(e,lang)
            self.assertIn(e['scheduled_daily_weight'],card['entity_id'])
            self.assertIn('🟦',card['content']); self.assertIn('🟩',card['content'])
            self.assertIn("q == 'excluded'",card['content'])
            physical_card=dashboard.physical_card(e,lang)
            self.assertIn('latest.total_portions',physical_card['content'])
            self.assertIn(e['physical_reference'],physical_card['entity_id'])
            view=dashboard.make_dashboard(e,lang)
            encoded=json.dumps(view,ensure_ascii=False)
            self.assertIn(physical_card['title'],encoded)
            self.assertNotIn('3 mesures initiales',encoded)
            self.assertIn('row.excluded_reason',encoded)

    def test_service_translated(self):
        for filename in ('strings.json','translations/en.json','translations/fr.json'):
            d=json.loads((assisted.ROOT/filename).read_text())
            self.assertEqual(set(d['services']['mark_feeding_day']['fields']),{'measurement_date','reason'})


class BetaCoordinatorTests(IsolatedAsyncioTestCase):
    def setUp(self):
        fixture=assisted.CoordinatorTests(); fixture.setUp()
        self.c,self.error,self.today=fixture.c,fixture.error,fixture.today
        self.c.compensated=self.c.__class__.__init__.__globals__['CompensatedCalibration']()

    async def test_mark_action_persists_without_commands(self):
        await self.c.async_mark_feeding_day(self.today,'tests')
        self.assertEqual(self.c.daily.excluded_days,{self.today.isoformat():'tests'})
        self.c.hass.async_add_executor_job.assert_awaited_once()
        self.c.async_request_refresh.assert_awaited_once()
        self.assertEqual(self.c.api.mock_calls,[])
        self.c._save.assert_not_awaited()

    async def test_mark_failed_storage_rolls_back(self):
        self.c.hass.async_add_executor_job.side_effect=OSError()
        with self.assertRaises(self.error): await self.c.async_mark_feeding_day(self.today,'tests')
        self.assertEqual(self.c.daily.excluded_days,{})
        self.assertTrue(self.c.daily_storage_failed)
        self.assertFalse(self.c.storage_failed)
        self.c.async_request_refresh.assert_not_awaited()

    def test_program_ignores_extra_portions_and_requires_fresh_schedule(self):
        c=self.c; c.entry.options={'portion_weight':6.8}
        schedule=[dict(status=True,repeatType=1,expireStatus=False,planFinishStatus=hour!='21:00',supperFlag=0,portions=p,feedingTime=hour) for hour,p in [('02:00',4),('07:00',4),('14:00',3),('21:00',3)]]
        now=DAY+timedelta(hours=18)
        d=data(0,309,48,schedule=schedule,schedule_date=DAY.date().isoformat())
        r=c._enrich(deepcopy(d),now)
        self.assertEqual(r['scheduled_daily_portions'],14)
        self.assertEqual(r['scheduled_daily_weight'],95.2)
        self.assertEqual(r['estimated_distributed'],326.4)
        self.assertEqual(r['forecast'],346.8)
        c.daily.mark_day(DAY.date(),DAY.date(),'trials')
        marked=c._enrich(deepcopy(d),now)
        for key in ('estimated_distributed','forecast','budget','decision','manual_state'):
            self.assertEqual(marked[key],r[key])
        self.assertEqual(marked['daily_quality'],'excluded')
        self.assertIsNone(c._enrich(dict(d,schedule_date='2026-11-24'),now)['scheduled_daily_weight'])

    async def test_physical_series_day_is_automatically_flagged(self):
        c=self.c; c.entry.options={'portion_weight':6.8}
        c.state['physical_series']=[physical.build_series(DAY.date(),TRIALS,True)]
        c.cal.candidate=None; c.cal.observe.return_value=None
        c._notify=AsyncMock()
        c._snapshot=AsyncMock(return_value=(data(0,309,48,schedule=[]),DAY+timedelta(hours=18)))
        result=await c._async_update_data()
        self.assertEqual(result['daily_quality'],'excluded')
        self.assertEqual(c.daily.excluded_days[DAY.date().isoformat()],'physical_calibration')
        self.assertEqual(result['estimated_distributed'],326.4)
        self.assertEqual(c.api.mock_calls,[])
