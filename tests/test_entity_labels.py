"""Presentation checks; entity keys, states and identifiers remain stable."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'mova_nutripal'


class EntityLabelTests(unittest.TestCase):
    def setUp(self):
        self.en = json.loads((ROOT / 'translations/en.json').read_text())
        self.fr = json.loads((ROOT / 'translations/fr.json').read_text())

    def test_english_source_matches_translation(self):
        self.assertEqual(json.loads((ROOT / 'strings.json').read_text()), self.en)

    def test_all_entity_keys_and_states_match(self):
        self.assertEqual(set(self.fr['entity']), set(self.en['entity']))
        for domain, entities in self.en['entity'].items():
            self.assertEqual(set(entities), set(self.fr['entity'][domain]))
            for key, entry in entities.items():
                translated = self.fr['entity'][domain][key]
                self.assertEqual(set(entry.get('state', {})), set(translated.get('state', {})))
                for spec in (entry, translated):
                    self.assertTrue(spec['name'].strip())

    def test_labels_distinguish_median_estimates_and_settings(self):
        sensors = self.fr['entity']['sensor']
        self.assertIn('médian', sensors['measured_weight']['name'])
        self.assertIn('estimée', sensors['estimated_distributed']['name'])
        self.assertIn('simulé', sensors['suggested_portions']['name'])
        self.assertNotEqual(sensors['target']['name'],
                            self.fr['entity']['number']['target_setting']['name'])
        self.assertIn('median', self.en['entity']['sensor']['measured_weight']['name'])
