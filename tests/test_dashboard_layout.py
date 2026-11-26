"""Offline validation of the generated read-only dashboard."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/generate_dashboard.py'
spec = importlib.util.spec_from_file_location('dashboard_layout', SCRIPT)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def registry(optional=True):
    rows = []
    for groups in (dashboard.GROUPS, dashboard.OPTIONAL) if optional else (dashboard.GROUPS,):
        for domain, keys in groups.items():
            rows.extend(dict(platform='mova_nutripal', entity_id=f'{domain}.renamed_{key}',
                             unique_id='private_did_' + key, device_id='private_device') for key in keys)
    return {'data': {'entities': rows}}


def cards(tree):
    if isinstance(tree, dict):
        if 'type' in tree:
            yield tree
        for value in tree.values():
            yield from cards(value)
    elif isinstance(tree, list):
        for value in tree:
            yield from cards(value)


class DashboardLayoutTests(unittest.TestCase):
    def test_responsive_sections_and_title(self):
        e = dashboard.find_entities(registry())
        result = dashboard.make_dashboard(e, 'fr', 'Luna & Mia')
        self.assertEqual(result['title'], 'Luna & Mia')
        view = result['views'][0]
        self.assertEqual(view['type'], 'sections')
        self.assertEqual(view['max_columns'], 2)
        self.assertEqual(len(view['sections']), 2)
        self.assertEqual([section['cards'][0]['heading'] for section in view['sections']],
                         ['Alimentation', 'Prochain repas et caméra'])
        self.assertTrue(all(c['grid_options']['columns'] == 'full' for section in view['sections'] for c in section['cards'][1:]))
        self.assertTrue(all(section['cards'][0]['type'] == 'heading' for section in view['sections']))

    def test_optional_camera_does_not_autoplay_or_fetch_thumbnail(self):
        e = dashboard.find_entities(registry())
        for result in (dashboard.make_card(e), dashboard.make_dashboard(e)):
            camera = [c for c in cards(result) if c.get('entity') == e['camera_snapshot']]
            self.assertEqual(len(camera), 1)
            self.assertEqual(camera[0]['type'], 'tile')
            self.assertFalse(camera[0]['show_entity_picture'])
            self.assertEqual(camera[0]['tap_action'], {'action': 'more-info'})
            self.assertNotIn('camera_view', json.dumps(result))

    def test_missing_optional_and_disabled_camera(self):
        r = registry()
        for row in r['data']['entities']:
            if row['entity_id'].startswith('camera.'):
                row['disabled_by'] = 'user'
        e = dashboard.find_entities(r)
        self.assertNotIn('camera_snapshot', e)
        self.assertNotIn('camera.', json.dumps(dashboard.make_dashboard(e)))
        self.assertEqual(len(dashboard.make_dashboard(dashboard.find_entities(registry(False)))['views'][0]['sections']), 2)

    def test_camera_from_other_feeder_is_not_used(self):
        r = registry(False)
        r['data']['entities'].append(dict(platform='mova_nutripal', entity_id='camera.other', unique_id='other_camera_snapshot', device_id='other'))
        e = dashboard.find_entities(r, 'private_device')
        self.assertNotIn('camera_snapshot', e)

    def test_read_only_no_private_registry_data_or_icon_overrides(self):
        e = dashboard.find_entities(registry())
        for result in (dashboard.make_card(e), dashboard.make_dashboard(e)):
            encoded = json.dumps(result)
            for forbidden in ('private_did', 'private_device', 'button.', 'call-service', 'perform-action', 'custom:', 'card_mod'):
                self.assertNotIn(forbidden, encoded)
            if result.get('views'):
                self.assertNotIn('number.', json.dumps(result['views'][0]))
            else:
                self.assertNotIn('number.', encoded)
            for c in cards(result):
                if c['type'] == 'tile' and not c['entity'].startswith('camera.'):
                    self.assertNotIn('icon', c)
                    self.assertEqual(c['tap_action']['action'], 'more-info')
                    self.assertEqual(c['icon_tap_action']['action'], 'more-info')

    def test_english_and_history(self):
        result = dashboard.make_dashboard(dashboard.find_entities(registry()), 'en')
        headings = [c['heading'] for c in cards(result) if c['type'] == 'heading']
        self.assertIn('Feeding', headings)
        self.assertIn('Calibration and maintenance', headings)
        self.assertIn('Hybrid regulation', headings)
        self.assertEqual(sorted(c['hours_to_show'] for c in cards(result) if c['type'] == 'history-graph'), [24, 48])

    def test_cli_preserves_single_card_default_and_supports_full_dashboard(self):
        data = json.dumps(registry())
        for args, expected in [([], 'vertical-stack'), (['--format', 'dashboard', '--language', 'en'], 'sections')]:
            p = subprocess.run([sys.executable, str(SCRIPT), *args], input=data, text=True, capture_output=True, check=True)
            result = json.loads(p.stdout)
            self.assertEqual(result.get('type') or result['views'][0]['type'], expected)

    def test_invalid_registry_entity_id_not_injected(self):
        r = registry()
        r['data']['entities'][0]['entity_id'] = 'sensor.bad\nsecret'
        with self.assertRaisesRegex(ValueError, 'bowl_weight'):
            dashboard.find_entities(r)

    def test_camera_in_feeding_and_health_in_maintenance(self):
        e = dashboard.find_entities(registry())
        view = dashboard.make_dashboard(e)['views'][0]
        self.assertTrue(any(c.get('entity') == e['camera_snapshot'] for c in cards(view)))
        self.assertIn(e['online'], json.dumps(view))

    def test_progress_uses_distribution_forecast_and_target_not_intake(self):
        e = dashboard.find_entities(registry())
        for lang in ('fr', 'en'):
            c = dashboard.distribution_progress(e, lang)
            self.assertEqual(c['entity_id'], [e[k] for k in ('estimated_distributed', 'forecast', 'target', 'simulation')])
            for term in ('is_number(d)', 't > 0', 'du == tu', 'fu == du', 'f >= d', 'f - d', '100 * f / t', '🟦', '🟧', '⬜'):
                self.assertIn(term, c['content'])
            self.assertNotIn(e['intake_today'], c['content'])

    def test_calibration_summary(self):
        e = dashboard.find_entities(registry())
        for lang in ('fr', 'en'):
            c = dashboard.calibration_card(e, lang)
            self.assertEqual(c['entity_id'], [e[k] for k in ('calibration_samples', 'calibration_enabled', 'measured_weight')])
            for term in ('n < 3', '3 - n', "enabled == 'off'", 'is_number(measured)', '🟪'):
                self.assertIn(term, c['content'])

    def test_next_meal_uses_time_and_countdown(self):
        e = dashboard.find_entities(registry())
        for lang, date_format in [('fr', '%d/%m %H:%M'), ('en', '%Y-%m-%d %H:%M')]:
            c = dashboard.next_meal_card(e, lang)
            self.assertNotIn('entity_id', c)  # now() keeps the countdown live
            for term in (e['next_meal'], e['next_meal_portions'], e['calibration_weight'], 'as_local(meal)', 'now()', date_format, 'seconds >= 0'):
                self.assertIn(term, c['content'])

    def test_health_summary_checks_unknown_states(self):
        e = dashboard.find_entities(registry())
        c = dashboard.health_card(e, 'fr')
        self.assertEqual(c['entity_id'], [e['online'], e['has_warning'], e['has_fault'], e['manual_pending']])
        self.assertIn("pending == 'on'", c['content'])
        self.assertIn("fault == 'off' and warning == 'off'", c['content'])
        self.assertIn('État à vérifier', c['content'])

    def test_v5_essentials_only_and_stable_paths(self):
        e = dashboard.find_entities(registry())
        for lang, labels in [('fr', ['Accueil','Planning','Historique','Technique']),
                             ('en', ['Home','Schedule','History','Technical'])]:
            views = dashboard.make_dashboard(e,lang)['views']
            self.assertEqual([v['title'] for v in views], labels)
            self.assertEqual([v['path'] for v in views], ['feeding','meals','feeding-history','technical'])
            home = json.dumps(views[0]); tech = json.dumps(views[-1])
            for k in ('budget','compensated_weight','desiccant_days','calibration_samples','manual_result'):
                self.assertNotIn(e[k],home); self.assertIn(e[k],tech)
            self.assertNotIn('calendar.',home)
            self.assertIn(e['bowl_weight'],home)
            self.assertIn(e['intake_yesterday'],home)

    def test_v5_summary_distinguishes_sources_and_excluded_days(self):
        e = dashboard.find_entities(registry())
        for lang in ('fr','en'):
            card = dashboard.overview_card(e,lang)
            for token in ("q == 'reconstructed'", "q != 'excluded'", "q == 'excluded'", 'valid_progress', '🟦', '🟧', '(sp-rem)*w', 'is_number(p)'):
                self.assertIn(token,card['content'])
            self.assertIn(e['scheduled_daily_weight'],card['entity_id'])
        fallback = dashboard.overview_card(dashboard.find_entities(registry(False)), 'fr')
        self.assertNotIn('sensor.renamed_daily_', fallback['content'])

    def test_v5_planning_uses_validated_program_and_dynamic_schedule(self):
        e = dashboard.find_entities(registry())
        card = dashboard.planning_card(e,'fr')
        self.assertIn(e['remaining_portions'],card['entity_id'])
        self.assertIn(e['scheduled_daily_portions'],card['entity_id'])
        self.assertIn("active|sum(attribute='portions') == p", card['content'])
        self.assertNotIn('02:00',card['content'])

    def test_v5_weekly_history_excludes_atypical_and_incomplete_days(self):
        e = dashboard.find_entities(registry())
        card = dashboard.weekly_card(e,'fr')
        self.assertEqual(card['entity_id'],[e['daily_history_count']])
        for token in ('rows[-7:]','row.excluded_reason',"row.quality == 'reconstructed'",'row.target > 0','Bilan incomplet'):
            self.assertIn(token,card['content'])

    def test_v51_progress_uses_schedule_not_raw_counter(self):
        e = dashboard.find_entities(registry())
        c = dashboard.overview_card(e, 'fr')
        self.assertIn("decision in ['device_not_ready','budget_reached','meal_soon','bowl_not_empty','would_feed']", c['content'])
        self.assertIn('0 <= rem <= sp', c['content'])
        self.assertIn('(p-sp*w)|abs <= 0.02', c['content'])
        self.assertIn('(sp-rem)*w', c['content'])
        self.assertNotIn(e['portions_today'], c['content'])
        self.assertIn('Programme total (inclut les repas restants)', c['content'])
        self.assertIn('Progression du programme indisponible', c['content'])

    def test_v51_reference_mismatch_is_visible_but_read_only(self):
        e = dashboard.find_entities(registry())
        for lang in ('fr', 'en'):
            c = dashboard.overview_card(e, lang)
            self.assertIn(e['physical_reference'], c['entity_id'])
            self.assertIn(e['calibration_weight'], c['entity_id'])
            self.assertIn('(w-proposed)|abs > 0.001', c['content'])
            self.assertNotIn('number.', json.dumps(c))

    def test_v51_consumption_exclusion_and_raw_access(self):
        e = dashboard.find_entities(registry())
        views = dashboard.make_dashboard(e)['views']
        for c in cards(views[0]):
            if c['type'] == 'tile':
                self.assertNotIn(c['entity'], (e['intake_today'], e['intake_yesterday']))
        c = dashboard.consumption_card(e, 'fr')
        self.assertIn("{% if excluded %}", c['content'])
        self.assertIn("{% if yesterday_excluded %}", c['content'])
        self.assertIn(e['intake_today'], json.dumps(views[-1]))
        self.assertIn(e['intake_yesterday'], json.dumps(views[2]))
