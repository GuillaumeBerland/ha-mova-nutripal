"""Render the optional HA automation's actual templates with representative states."""
from datetime import datetime, date
from pathlib import Path
import unittest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = yaml.safe_load((ROOT / 'dashboard/health_reminders_automation.yaml').read_text())


def render(profiles, records, *, today='2026-11-26', interval=7, lead=7, state='2'):
    env = Environment(undefined=StrictUndefined)
    attributes = {'profiles': profiles, 'care_records': records}
    def as_datetime(value, default=None):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return default
    ctx = dict(health_entity='sensor.example_pet_health', weighing_interval_days=interval,
               care_lead_days=lead, now=lambda: datetime.fromisoformat(today),
               as_datetime=as_datetime, state_attr=lambda entity, key: attributes.get(key),
               states=lambda entity: state)
    ready = env.from_string(AUTOMATION['conditions'][0]['value_template']).render(**ctx) == 'True'
    return ready, env.from_string(AUTOMATION['actions'][0]['variables']['reminder_message']).render(**ctx) if ready else ''


def pet(name='Example', latest='2026-11-19', key='a'):
    return dict(name=name, latest_date=latest, pet_id=key)


def care(due='2026-11-26', *, completed=False, key='a', title='Example visit'):
    return dict(pet_id=key, due_date=due, completed=completed, title=title)


class HealthReminderTests(unittest.TestCase):
    def test_due_weighing_boundary(self):
        self.assertIn('7 j', render([pet()], [])[1])
        self.assertEqual(render([pet(latest='2026-11-20')], [])[1], '')

    def test_no_weighing_and_disabled(self):
        self.assertIn('aucune pesée', render([pet(latest=None)], [])[1])
        self.assertEqual(render([pet(latest=None)], [], interval=0)[1], '')

    def test_care_due_window_and_order(self):
        text = render([pet()], [care('2026-12-03', title='Soon'), care('2026-11-25', title='Late'), care(title='Today'), care('2026-12-04', title='Later')], interval=0)[1]
        self.assertIn('en retard de 1 j', text)
        self.assertIn('aujourd’hui', text)
        self.assertIn('dans 7 j', text)
        self.assertNotIn('Later', text)
        self.assertLess(text.index('Late'), text.index('Today'))
        self.assertLess(text.index('Today'), text.index('Soon'))

    def test_completed_no_date_or_unknown_pet_ignored(self):
        self.assertEqual(render([pet()], [care(completed=True), care(None), care(key='unknown')], interval=0)[1], '')

    def test_unavailable_or_missing_data(self):
        for p, r, state in [([pet()], [care()], 'unavailable'), (None, [], '2'), ([], None, '2'), ([], [], 'unknown')]:
            self.assertEqual(render(p, r, state=state), (False, ''))

    def test_separate_pets(self):
        text = render([pet('One', key='a'), pet('Two', key='b')], [care(key='b')], interval=0)[1]
        self.assertIn('Two :', text)
        self.assertNotIn('One :', text)

    def test_zero_care_lead(self):
        text = render([pet()], [care('2026-11-27', title='Tomorrow'), care(title='Now')], interval=0, lead=0)[1]
        self.assertNotIn('Tomorrow', text)
        self.assertIn('Now', text)
