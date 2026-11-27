"""Cross-feature regressions for local health data (no HA or cloud required)."""
import json
from pathlib import Path
import tempfile
import unittest

from test_pet_health import health, TODAY, profile, direct
from test_food_profiles import period
from test_veterinary_records import event
from test_health_reminders import render


class Beta2StabilizationTests(unittest.TestCase):
    def test_legacy_file_keeps_history_after_visual_edit_and_renewal(self):
        model = health.PetHealth()
        profile(model)
        profile(model, 'cat_b')
        model.record_weights(pet_id='cat_a', measurements=[direct()], today=TODAY)
        model.record_food_period(period=period(), today=TODAY)
        model.record_care(record=event(), today=TODAY)
        legacy = model.export()
        for pet in legacy['pets'].values():
            pet.pop('color', None)
            pet.pop('photo_url', None)
        old_record = legacy['care_records'][0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'health.json'
            path.write_text(json.dumps({'version': 1, 'state': legacy}), encoding='utf-8')
            restored = health.load_health(path)
            self.assertEqual(restored.export(), legacy)
            restored.save_profile(pet_id='cat_a', name='Example cat', today=TODAY,
                                  color='#527FBA', photo_url='/local/pets/cat_a.jpg')
            restored.renew_care(record=event(date=TODAY.isoformat(), title='New care',
                                             due_date=None), today=TODAY,
                                previous_record_id=old_record['record_id'],
                                expected_due_date=old_record['due_date'])
            health.save_health(path, restored)
            state = health.load_health(path).export()
        expected_pet = dict(legacy['pets']['cat_a'], color='#527fba',
                            photo_url='/local/pets/cat_a.jpg')
        self.assertEqual(state['pets']['cat_a'], expected_pet)
        self.assertEqual(state['pets']['cat_b'], legacy['pets']['cat_b'])
        self.assertEqual(state['food_periods'], legacy['food_periods'])
        self.assertEqual(len(state['care_records']), 2)
        self.assertIn(dict(old_record, completed=True), state['care_records'])

    def test_reminders_follow_new_due_date_not_closed_record(self):
        model = health.PetHealth()
        profile(model)
        profile(model, 'cat_b')
        model.save_profile(pet_id='cat_a', name='Example cat', today=TODAY,
                           color='#527fba', photo_url='/local/pets/cat_a.jpg')
        model.record_care(record=event(title='Previous care', due_date='2026-11-26'), today=TODAY)
        model.record_care(record=event(pet_id='cat_b', title='Other care',
                                       due_date='2026-11-26'), today=TODAY)
        profiles = [model.summary(key) for key in sorted(model.pets)]
        before = render(profiles, model.care_records, interval=0)[1]
        self.assertIn('Previous care', before)
        self.assertIn('Other care', before)
        old = next(r for r in model.care_records if r['pet_id'] == 'cat_a')
        model.renew_care(record=event(date=TODAY.isoformat(), title='Next care',
                                      due_date='2026-12-10'), today=TODAY,
                         previous_record_id=old['record_id'], expected_due_date=old['due_date'])
        after = render(profiles, model.care_records, interval=0)[1]
        self.assertNotIn('Previous care', after)
        self.assertNotIn('Next care', after)
        self.assertIn('Other care', after)
        later = render(profiles, model.care_records, today='2026-12-03', interval=0)[1]
        self.assertIn('Next care', later)
        self.assertNotIn('Previous care', later)
        new = next(r for r in model.care_records if r['title'] == 'Next care')
        model.renew_care(record=event(date='2026-12-03', title='Final care', due_date=None),
                         today=TODAY.replace(month=12, day=3),
                         previous_record_id=new['record_id'], expected_due_date=new['due_date'])
        final = render(profiles, model.care_records, today='2026-12-10', interval=0)[1]
        self.assertNotIn('Previous care', final)
        self.assertNotIn('Next care', final)
        self.assertNotIn('Final care', final)
        self.assertIn('Other care', final)
