"""Midnight diagnostics and deliberately narrow recovery of delayed totals."""
from datetime import timedelta
import json
import unittest
from test_daily_balance import balance, data, DAY
from test_dashboard_layout import dashboard, registry, cards


class MidnightRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.t = balance.DailyBalance()
        self.read(-2, data(0, 98, 14))

    def read(self, minute, d):
        now = DAY + timedelta(minutes=minute)
        self.t.observe(d, now, 5, 6.8, 100)
        return self.t.summary(d, now)

    def first(self):
        return self.read(2, data(0, 0, 0, intake_yesterday=90, portions_yesterday=14))

    def test_delayed_yesterday_total(self):
        s = self.first()
        self.assertEqual(s['daily_boundary']['status'], 'retry')
        self.assertEqual(s['daily_boundary']['reasons'], ['yesterday_intake_mismatch'])
        self.assertIsNone(s['daily_reconstructed'])
        s = self.read(7, data(0, 0, 0, intake_yesterday=98, portions_yesterday=14))
        self.assertEqual(s['daily_boundary']['status'], 'confirmed')
        self.assertEqual(s['daily_reconstructed'], 0)
        self.assertEqual(self.t.history[-1]['consumed'], 98)
        self.assertIsNone(self.t.history[-1]['reconstructed'])  # yesterday opening unknown

    def test_pending_survives_restart_and_old_state_loads(self):
        old = self.t.export(); old.pop('boundary')
        self.t = balance.DailyBalance(old)
        self.first()
        self.t = balance.DailyBalance(self.t.export())
        self.assertEqual(self.read(6, data(0, 0, 0, intake_yesterday=98, portions_yesterday=14))['daily_quality'], 'reconstructed')

    def test_changed_bowl_or_new_food_cancels_retry(self):
        for d in (data(1,0,0), data(0,1,0), data(0,0,1)):
            with self.subTest(d=d):
                self.setUp(); self.first()
                d.update(intake_yesterday=98, portions_yesterday=14)
                s=self.read(5,d)
                self.assertEqual(s['daily_boundary']['status'],'failed')
                self.assertIsNone(s['daily_reconstructed'])

    def test_nonzero_new_counters_not_recovered(self):
        s=self.read(2,data(0,98,14,intake_yesterday=98,portions_yesterday=14))
        self.assertIn('today_counters_not_zero',s['daily_boundary']['reasons'])
        self.assertIsNone(self.read(5,data(0,0,0,intake_yesterday=98,portions_yesterday=14))['daily_reconstructed'])

    def test_late_or_gapped_retry_rejected(self):
        self.first()
        self.read(7,data(0,0,0,intake_yesterday=90,portions_yesterday=14))
        self.read(12,data(0,0,0,intake_yesterday=90,portions_yesterday=14))
        self.assertIsNone(self.read(16,data(0,0,0,intake_yesterday=98,portions_yesterday=14))['daily_reconstructed'])
        self.assertEqual(self.t.boundary['status'],'failed')
        self.setUp(); self.first()
        self.assertIsNone(self.read(10,data(0,0,0,intake_yesterday=98,portions_yesterday=14))['daily_reconstructed'])

    def test_yesterday_higher_than_last_reading_not_recovered(self):
        self.first()
        s=self.read(5,data(0,0,0,intake_yesterday=99,portions_yesterday=14))
        self.assertEqual(s['daily_boundary']['reasons'],['yesterday_counters_changed'])
        self.assertIsNone(s['daily_reconstructed'])

    def test_midnight_polling_window(self):
        for minute, expected in [(-11,False),(-10,True),(0,True),(15,True),(16,False)]:
            self.assertEqual(balance.near_midnight(DAY+timedelta(minutes=minute)),expected)


class SettingsDashboardTests(unittest.TestCase):
    def test_native_settings_only_on_technical_view(self):
        e=dashboard.find_entities(registry())
        for lang in ('fr','en'):
            v=dashboard.make_dashboard(e,lang)['views']
            settings=[c for c in cards(v[-1]) if c.get('type')=='entities' and any(row['entity'].startswith('number.') for row in c['entities'])]
            self.assertEqual(len(settings),1)
            self.assertEqual([r['entity'] for r in settings[0]['entities']], [e['reference_setting'],e['target_setting']])
            self.assertNotIn('number.',json.dumps(v[:-1]))
            self.assertIn('midnight_boundary',json.dumps(v[-1]))
        self.assertIsNone(dashboard.configuration_card(dashboard.find_entities(registry(False)),'fr'))
