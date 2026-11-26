"""Care records remain local declarations and preserve legacy health data."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_pet_health import health, TODAY, profile, direct
from test_camera_transport import PACKAGE
from test_food_profiles import period


def event(**kw):
    return dict({'pet_id':'cat_a','date':'2026-11-20','category':'vaccination',
                 'title':'Example vaccine','notes':'Recorded at visit',
                 'due_date':'2027-11-20'}, **kw)


class CareTests(unittest.TestCase):
    def setUp(self):
        self.m=health.PetHealth()
        profile(self.m)
        profile(self.m,'cat_b')
        self.m.record_weights(pet_id='cat_a',measurements=[direct()],today=TODAY)
        self.m.record_food_period(period=period(),today=TODAY)

    def add(self,r=None,**kw):
        self.m.record_care(record=event() if r is None else r,today=TODAY,**kw)

    def test_migration(self):
        old=self.m.export();old.pop('care_records')
        self.assertEqual(health.PetHealth(old).export(),dict(old,care_records=[]))

    def test_isolated_records_and_distinct_same_day_events(self):
        old=self.m.export();self.add();self.add(event(title='Exam',category='consultation'));self.add(event(pet_id='cat_b'))
        state=self.m.export();self.assertEqual(len(state['care_records']),3)
        self.assertEqual(len({r['record_id'] for r in state['care_records']}),3)
        self.assertEqual(state['pets'],old['pets']);self.assertEqual(state['food_periods'],old['food_periods'])

    def test_exact_duplicate_idempotent(self):
        self.add();old=self.m.export();self.add();self.assertEqual(self.m.export(),old)

    def test_explicit_correction_and_completion(self):
        self.add();old=self.m.export();key=old['care_records'][0]['record_id']
        with self.assertRaises(ValueError):self.add(event(completed=True),record_id=key)
        self.assertEqual(self.m.export(),old)
        self.add(event(completed=True),record_id=key,replace_existing=True)
        row=self.m.export()['care_records'][0];self.assertTrue(row['completed']);self.assertEqual(row['record_id'],key)

    def test_wrong_pet_or_unknown_id(self):
        self.add();old=self.m.export();key=old['care_records'][0]['record_id']
        for r,k in [(event(pet_id='cat_b'),key),(event(),'f'*32)]:
            with self.assertRaises(ValueError):self.add(r,record_id=k,replace_existing=True)
        self.assertEqual(self.m.export(),old)

    def test_bad_fields_atomic(self):
        old=self.m.export()
        for r in [event(pet_id='unknown'),event(date='2026-11-27'),event(date='2026-02-30'),event(category='invalid'),event(title=' '),event(notes='x'*501),event(due_date='2026-11-19'),event(due_date=None,completed=True),event(completed='true'),event(extra=1)]:
            with self.subTest(r=r),self.assertRaises(ValueError):self.add(r)
            self.assertEqual(self.m.export(),old)
        with self.assertRaises(ValueError):self.add(replace_existing=True)

    def test_roundtrip_and_capacity(self):
        self.add();old=self.m.export()
        with patch(PACKAGE+'.veterinary_records.MAX_RECORDS',1),self.assertRaises(ValueError):self.add(event(title='Another'))
        self.assertEqual(self.m.export(),old)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'health.json';health.save_health(path,self.m)
            self.assertEqual(health.load_health(path).export(),old)
        old['care_records'][0]['title']='changed';self.assertNotEqual(self.m.export(),old)

    def test_corrupt_records_rejected(self):
        self.add();state=self.m.export();state['care_records'].append(state['care_records'][0].copy())
        with self.assertRaises(ValueError):health.PetHealth(state)

    def test_native_summary_is_read_only(self):
        from test_pet_health_dashboard import with_health, dashboard
        card=dashboard.pet_health_card(dashboard.find_entities(with_health()),'fr')
        self.assertIn("'care_records'",card['content'])
        self.assertIn('care|length',card['content'])
        self.assertNotIn('record_pet_care',card['content'])
