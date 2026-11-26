"""Food history is a local declaration, not a feeding configuration."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_pet_health import health, TODAY, profile, direct
from test_pet_health_dashboard import with_health, dashboard


def period(day='2026-11-26', **kw):
    return dict({'start_date':day,'name':'Example mixture', 'components':[
        {'name':'Food A','percent':70,'kcal_per_100g':350},
        {'name':'Food B','percent':30,'kcal_per_100g':400}], 'ration_g':100,'portion_g':6.8}, **kw)


class FoodProfileTests(unittest.TestCase):
    def setUp(self):
        self.m=health.PetHealth()
        profile(self.m)
        self.m.record_weights(pet_id='cat_a',measurements=[direct()],today=TODAY)

    def add(self,r,replace=False):
        self.m.record_food_period(period=r,today=TODAY,replace_existing=replace)

    def test_legacy_migration_preserves_weights(self):
        old={'pets':self.m.export()['pets']}
        restored=health.PetHealth(old)
        self.assertEqual(restored.export()['pets'],old['pets'])
        self.assertEqual(restored.food_summary(TODAY),{'current':None,'history':[],'used_for_feeding':False})

    def test_weighted_energy_and_declared_reference(self):
        before=self.m.export()['pets']
        self.add(period())
        food=self.m.food_summary(TODAY)
        self.assertEqual(food['current']['kcal_per_100g'],365)
        self.assertEqual(food['current']['ration_kcal'],365)
        self.assertEqual(food['current']['portion_g'],6.8)
        self.assertFalse(food['used_for_feeding'])
        self.assertEqual(self.m.export()['pets'],before)

    def test_unknown_energy_never_guessed(self):
        self.add(period(components=[{'name':'A','percent':100}],ration_g=90))
        self.assertIsNone(self.m.food_summary(TODAY)['current']['ration_kcal'])
        self.assertIsNone(self.m.food_summary(TODAY)['current']['kcal_per_100g'])

    def test_chronology_and_date_selection(self):
        self.add(period());self.add(period('2026-11-20',name='Earlier'))
        self.assertEqual(self.m.food_summary(date(2026,11,24))['current']['name'],'Earlier')
        self.assertEqual(self.m.food_summary(TODAY)['current']['name'],'Example mixture')
        self.assertEqual(len(self.m.food_summary(TODAY)['history']),2)

    def test_idempotent_and_explicit_correction(self):
        self.add(period());before=self.m.export();self.add(period())
        self.assertEqual(self.m.export(),before)
        with self.assertRaises(ValueError): self.add(period(name='Changed'))
        self.assertEqual(self.m.export(),before)
        self.add(period(name='Changed'),True)
        self.assertEqual(self.m.food_summary(TODAY)['current']['name'],'Changed')

    def test_invalid_values_do_not_change_state(self):
        before=self.m.export()
        for r in [period('2026-11-27'),period(components=[{'name':'A','percent':99}]),
                  period(components=[{'name':'A','percent':50},{'name':'a','percent':50}]),
                  period(components=[{'name':'A','percent':True}]),period(ration_g=float('nan')),
                  period(portion_g=6.811),period(components=[{'name':'A','percent':100,'kcal_per_100g':901}]),
                  period(components=[{'name':'A','percent':100,'unknown':1}])]:
            with self.subTest(r=r), self.assertRaises(ValueError):self.add(r)
            self.assertEqual(self.m.export(),before)

    def test_roundtrip_and_copy(self):
        self.add(period());expected=self.m.export()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'health.json';health.save_health(p,self.m)
            self.assertEqual(health.load_health(p).export(),expected)
        self.m.food_summary(TODAY)['current']['components'].clear()
        self.assertEqual(self.m.export(),expected)

    def test_corrupt_history_rejected(self):
        self.add(period());state=self.m.export();state['food_periods'][0]['components'][0]['percent']=5
        with self.assertRaises(ValueError):health.PetHealth(state)

    def test_capacity_no_eviction(self):
        self.add(period());before=self.m.export()
        from test_camera_transport import PACKAGE
        with patch(PACKAGE+'.food_profiles.MAX_FOOD_PERIODS',1),self.assertRaises(ValueError):
            self.add(period('2026-11-25'))
        self.assertEqual(self.m.export(),before)

    def test_native_card_has_read_only_food(self):
        c=dashboard.pet_health_card(dashboard.find_entities(with_health()),'fr')
        self.assertIn("'food'",c['content'])
        self.assertIn('food.current.ration_kcal',c['content'])
        self.assertNotIn('record_food_period',c['content'])
