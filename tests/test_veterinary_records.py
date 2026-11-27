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

    def test_renewal_preserves_old_event_and_other_data(self):
        self.add();self.add(event(pet_id='cat_b'));old=self.m.export()
        previous=next(r for r in old['care_records'] if r['pet_id']=='cat_a')
        record=event(date=TODAY.isoformat(),title='New vaccine',notes='',due_date='2027-11-26')
        self.m.renew_care(record=record,today=TODAY,previous_record_id=previous['record_id'],expected_due_date=previous['due_date'])
        state=self.m.export();rows=state['care_records'];self.assertEqual(len(rows),3)
        self.assertIn(dict(previous,completed=True),rows)
        self.assertIn(next(r for r in old['care_records'] if r['pet_id']=='cat_b'),rows)
        new=next(r for r in rows if r['title']=='New vaccine')
        self.assertFalse(new['completed']);self.assertEqual(new['due_date'],'2027-11-26')
        self.assertEqual(state['pets'],old['pets']);self.assertEqual(state['food_periods'],old['food_periods'])
        self.assertEqual(health.PetHealth(state).export(),state)
        with self.assertRaises(ValueError):
            self.m.renew_care(record=record,today=TODAY,previous_record_id=previous['record_id'],expected_due_date=previous['due_date'])
        self.assertEqual(self.m.export(),state)

    def test_renewal_rejects_invalid_or_stale_requests_atomically(self):
        self.add();old=self.m.export();previous=old['care_records'][0]
        valid=event(date=TODAY.isoformat(),title='New vaccine',due_date=None)
        args=dict(today=TODAY,previous_record_id=previous['record_id'],expected_due_date=previous['due_date'])
        for record,overrides in [(event(),{}),(dict(valid,pet_id='cat_b'),{}),
                (dict(valid,category='consultation'),{}),(dict(valid,date='2026-11-19'),{}),
                (dict(valid,date='2026-11-27'),{}),(dict(valid,title=' '),{}),
                (dict(valid,due_date='2026-11-25'),{}),(dict(valid,completed=True,due_date='2027-11-26'),{}),
                (valid,{'previous_record_id':'f'*32}),(valid,{'expected_due_date':'2027-11-21'})]:
            with self.subTest(record=record,overrides=overrides),self.assertRaises(ValueError):
                self.m.renew_care(record=record,**dict(args,**overrides))
            self.assertEqual(self.m.export(),old)
        with patch(PACKAGE+'.veterinary_records.MAX_RECORDS',1),self.assertRaises(ValueError):
            self.m.renew_care(record=valid,**args)
        self.assertEqual(self.m.export(),old)
        self.m.renew_care(record=valid,**args)
        self.assertIsNone(self.m.export()['care_records'][-1]['due_date'])

    def test_renewal_rejects_duplicate_new_event_and_record_without_due_date(self):
        self.add();self.add(event(date=TODAY.isoformat(),title='Already saved',due_date=None))
        old=self.m.export();previous,new=old['care_records']
        for record,prev,due in [(event(date=TODAY.isoformat(),title='Already saved',due_date=None),previous,previous['due_date']),
                                (event(date=TODAY.isoformat(),title='Another'),new,previous['due_date'])]:
            with self.assertRaises(ValueError):
                self.m.renew_care(record=record,today=TODAY,previous_record_id=prev['record_id'],expected_due_date=due)
            self.assertEqual(self.m.export(),old)

    def test_native_summary_is_read_only(self):
        from test_pet_health_dashboard import with_health, dashboard
        card=dashboard.pet_health_card(dashboard.find_entities(with_health()),'fr')
        self.assertIn("'care_records'",card['content'])
        self.assertIn('care|length',card['content'])
        self.assertNotIn('record_pet_care',card['content'])
