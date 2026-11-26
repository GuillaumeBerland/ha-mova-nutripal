"""Health view is optional, dynamically bound and isolated from feeding."""
import json
import unittest
from test_dashboard_layout import dashboard, registry, cards


def with_health():
    r = registry()
    r['data']['entities'] += [dict(platform='mova_nutripal', entity_id='sensor.renamed_health',
        unique_id='private_did_pet_health', device_id='private_device'),
        dict(platform='mova_nutripal', entity_id='sensor.some_cat_weight',
             unique_id='private_did_pet_example_weight', device_id='pet_device')]
    return r


class HealthDashboardTests(unittest.TestCase):
    def test_optional_health_view(self):
        old = dashboard.make_dashboard(dashboard.find_entities(registry()))
        self.assertNotIn('pet-health', [v['path'] for v in old['views']])
        e = dashboard.find_entities(with_health())
        self.assertEqual(e['pet_health'], 'sensor.renamed_health')
        view = dashboard.make_dashboard(e)
        self.assertEqual([v['path'] for v in view['views']], ['feeding','meals','feeding-history','pet-health','technical'])
        self.assertNotIn('sensor.some_cat_weight',json.dumps(view))
        self.assertNotIn('sensor.renamed_health',json.dumps(view['views'][0]))
        self.assertNotIn('custom:',json.dumps(view))

    def test_opt_in_card_and_english(self):
        e = dashboard.find_entities(with_health())
        view = dashboard.make_dashboard(e, 'en', health_ui=True)['views'][3]
        self.assertEqual(view['title'],'Health')
        self.assertEqual(view['type'],'panel')
        self.assertEqual(view['cards'],[{'type':'custom:mova-pet-health-card','entity':'sensor.renamed_health','language':'en'}])
        self.assertNotIn('custom:',json.dumps(dashboard.make_card(e)))

    def test_disabled_or_other_feeder_health_not_selected(self):
        r = with_health()
        r['data']['entities'][-2]['disabled_by'] = 'user'
        self.assertNotIn('pet_health',dashboard.find_entities(r))
        del r['data']['entities'][-2]['disabled_by']
        r['data']['entities'][-2]['device_id'] = 'other_feeder'
        self.assertNotIn('pet_health',dashboard.find_entities(r, 'private_device'))

    def test_no_personal_data_copied(self):
        r = with_health()
        r['data']['entities'][-2]['name'] = 'PRIVATE PERSONAL DATA'
        for ui in (False,True):
            config = json.dumps(dashboard.make_dashboard(dashboard.find_entities(r),health_ui=ui))
            for value in ('PRIVATE PERSONAL DATA','private_did','private_device','some_cat_weight'):
                self.assertNotIn(value,config)

    def test_native_summary_uses_live_profiles_and_handles_unavailable(self):
        c=dashboard.pet_health_card(dashboard.find_entities(with_health()),'fr')
        self.assertEqual(c['entity_id'],['sensor.renamed_health'])
        for term in ("'profiles'", 'unavailable','p.target_kg','p.change_grams','p.measurement_count','p.name|e'):
            self.assertIn(term,c['content'])
