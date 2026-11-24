"""Check icon translations against the existing entity translations."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'mova_nutripal'


class EntityIconTests(unittest.TestCase):
    def setUp(self):
        self.icons = json.loads((ROOT / 'icons.json').read_text())['entity']
        self.strings = json.loads((ROOT / 'strings.json').read_text())['entity']

    def test_all_translated_entities_covered_except_native_battery(self):
        self.assertEqual(set(self.icons), set(self.strings))
        for domain, entities in self.strings.items():
            expected = set(entities)
            if domain == 'sensor':
                expected.remove('battery')
            self.assertEqual(set(self.icons[domain]), expected, domain)

    def test_binary_icons_cover_both_states(self):
        for key, spec in self.icons['binary_sensor'].items():
            self.assertEqual(set(spec['state']), {'on', 'off'}, key)
            self.assertNotEqual(spec['state']['on'], spec['state']['off'], key)

    def test_enum_icons_match_raw_states(self):
        for key, spec in self.icons['sensor'].items():
            self.assertEqual(set(spec.get('state', {})),
                             set(self.strings['sensor'][key].get('state', {})), key)

    def test_icon_format_and_defaults(self):
        for entities in self.icons.values():
            for spec in entities.values():
                self.assertLessEqual(set(spec), {'default', 'state'})
                for name in [spec['default'], *spec.get('state', {}).values()]:
                    self.assertIsNotNone(re.fullmatch(r'mdi:[a-z0-9]+(?:-[a-z0-9]+)*', name))

    def test_camera_icon_and_native_battery(self):
        tree = ast.parse((ROOT / 'camera.py').read_text())
        camera = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == 'NutriPalCamera')
        assignment = next(node for node in camera.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == '_attr_icon'
                                  for t in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value), 'mdi:cctv')
        self.assertNotIn('battery', self.icons['sensor'])
