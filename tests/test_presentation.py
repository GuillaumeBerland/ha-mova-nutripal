import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest
import json

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

presentation = load('presentation', 'custom_components/mova_nutripal/presentation.py')
dashboard = load('dashboard', 'tools/generate_dashboard.py')

class PresentationTest(unittest.TestCase):
    now = datetime(2026, 11, 24, 12, tzinfo=ZoneInfo('Europe/Paris'))

    def meal(self, at, portions=5, done=False, **kwargs):
        return dict(status=True, repeatType=1, expireStatus=False, supperFlag=0,
                    planFinishStatus=done, feedingTime=at, portions=portions) | kwargs

    def test_today(self):
        result = presentation.next_scheduled_meal([self.meal('06:50', 6, True), self.meal('21:00')], self.now)
        self.assertEqual(result, (self.now.replace(hour=21), 5))

    def test_tomorrow(self):
        result = presentation.next_scheduled_meal([self.meal('06:50', 6, True)], self.now)
        self.assertEqual(result, (self.now.replace(day=25, hour=6, minute=50), 6))

    def test_overdue(self):
        self.assertIsNone(presentation.next_scheduled_meal([self.meal('06:50'), self.meal('21:00')], self.now))

    def test_future_done(self):
        self.assertIsNone(presentation.next_scheduled_meal([self.meal('21:00', done=True)], self.now))

    def test_unknown_schedule(self):
        for rows in [None, [], [self.meal('21:00', repeatType=2)], [self.meal('21:00', expireStatus=True)], [self.meal('21:00', supperFlag=1)], [self.meal('bad')], [self.meal('21:00', status=False)]]:
            with self.subTest(rows=rows):
                self.assertIsNone(presentation.next_scheduled_meal(rows, self.now))

    def test_simultaneous(self):
        self.assertEqual(presentation.next_scheduled_meal([self.meal('21:00', 2), self.meal('21:00', 3)], self.now), (self.now.replace(hour=21),5))

    def test_timezone(self):
        now = datetime(2026, 3, 28, 23, tzinfo=ZoneInfo('Europe/Paris'))
        due, _ = presentation.next_scheduled_meal([self.meal('06:50', done=True)], now)
        self.assertEqual(due.isoformat(), '2026-03-29T06:50:00+02:00')

class DashboardTest(unittest.TestCase):
    def registry(self):
        return {'data': {'entities': [dict(platform='mova_nutripal', entity_id=f'{platform}.custom_{key}', unique_id='synthetic_'+key, device_id='example') for platform, keys in dashboard.GROUPS.items() for key in keys]}}

    def test_renamed_ids(self):
        e = dashboard.find_entities(self.registry())
        self.assertEqual(e['bowl_weight'], 'sensor.custom_bowl_weight')
        card = dashboard.make_card(e)
        self.assertEqual(card['type'], 'vertical-stack')
        encoded = json.dumps(card)
        self.assertIn('sensor.custom_next_meal', encoded)
        self.assertNotIn('button.', encoded)
        self.assertNotIn('call-service', encoded)
        self.assertNotIn('synthetic_', encoded)

    def test_disabled(self):
        r = self.registry()
        r['data']['entities'][0]['disabled_by'] = 'user'
        with self.assertRaisesRegex(ValueError, 'bowl_weight'):
            dashboard.find_entities(r)

    def test_multiple(self):
        r = self.registry()
        extra = [dict(row, device_id='other', unique_id='other_'+row['unique_id'], entity_id=row['entity_id']+'_other') for row in r['data']['entities']]
        r['data']['entities'].extend(extra)
        with self.assertRaisesRegex(ValueError, 'multiple feeders'):
            dashboard.find_entities(r)
        self.assertEqual(dashboard.find_entities(r, 'other')['bowl_weight'], 'sensor.custom_bowl_weight_other')

if __name__ == '__main__':
    unittest.main()
