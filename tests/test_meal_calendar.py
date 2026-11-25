"""Offline tests for the calendar projection and optional dashboard view."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from test_dashboard_layout import dashboard, registry

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calendar_schedule', ROOT / 'custom_components/mova_nutripal/calendar_schedule.py')
calendar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calendar)


def meal(at='21:00', portions=5, **changes):
    return dict(status=True, repeatType=1, expireStatus=False, supperFlag=0,
                planFinishStatus=False, feedingTime=at, portions=portions) | changes


class MealCalendarTests(unittest.TestCase):
    now = datetime(2026, 11, 24, 12, tzinfo=calendar.TZ)

    def data(self, rows):
        return dict(schedule=rows, online=True, schedule_date=self.now.date().isoformat())

    def events(self, rows, start=None, end=None):
        return calendar.meals_in_range(calendar.schedule_slots(rows), self.now.date(),
                                       start or self.now, end or self.now + timedelta(days=2))

    def test_daily_projection_and_order(self):
        events = self.events([meal(), meal('06:50', 6, planFinishStatus=True)])
        self.assertEqual([(m.start.strftime('%d %H:%M'), m.portions) for m in events],
                         [('24 21:00', 5), ('25 06:50', 6), ('25 21:00', 5), ('26 06:50', 6)])
        self.assertTrue(all(m.end - m.start == timedelta(minutes=1) for m in events))

    def test_same_time_merged_and_disabled_omitted(self):
        events = self.events([meal(portions=2), meal(portions=3), meal('15:00', status=False)])
        self.assertEqual([m.portions for m in events], [5, 5])
        self.assertEqual(calendar.schedule_slots([meal(status=False)]), [])

    def test_invalid_active_rows_never_partially_projected(self):
        for invalid in [None, meal(repeatType=2), meal(repeatType=True), meal(expireStatus=True),
                        meal(planFinishStatus=None), meal(supperFlag=1), meal(portions=True),
                        meal(portions=0), meal('bad'), meal('21:00+01:00'), meal(status=1)]:
            with self.subTest(invalid=invalid):
                self.assertIsNone(calendar.schedule_slots([meal(), invalid]))
        self.assertIsNone(calendar.schedule_slots(None))

    def test_no_history_before_snapshot_and_bounded_future(self):
        events = self.events([meal()], self.now - timedelta(days=1000), self.now + timedelta(days=1000))
        self.assertEqual(len(events), calendar.HORIZON_DAYS)
        self.assertEqual(events[0].start.date(), self.now.date())
        self.assertEqual(events[-1].start.date(), self.now.date() + timedelta(days=59))

    def test_exclusive_end_and_overlap(self):
        due = self.now.replace(hour=21)
        self.assertEqual(self.events([meal()], due - timedelta(hours=1), due), [])
        self.assertEqual(len(self.events([meal()], due + timedelta(seconds=30), due + timedelta(minutes=2))), 1)
        self.assertEqual(self.events([meal()], due + timedelta(minutes=1), due + timedelta(minutes=2)), [])
        self.assertEqual(self.events([meal()], due, due), [])

    def test_stale_offline_and_empty_schedule(self):
        data = self.data([meal()])
        self.assertIsNotNone(calendar.current_slots(data, self.now))
        self.assertIsNone(calendar.current_slots(data, self.now + timedelta(days=1)))
        self.assertIsNone(calendar.current_slots(dict(data, online=False), self.now))
        self.assertIsNone(calendar.current_slots(dict(data, schedule_date=None), self.now))
        self.assertEqual(calendar.current_slots(self.data([]), self.now), [])

    def test_timezone_and_daylight_saving(self):
        start = datetime(2026, 3, 28, tzinfo=calendar.TZ)
        slots = calendar.schedule_slots([meal('06:50'), meal('02:30')])
        events = calendar.meals_in_range(slots, start.date(), start, start + timedelta(days=3))
        self.assertEqual(len(events), 5)  # Missing 02:30 on spring-forward day.
        self.assertEqual([m.start.utcoffset() for m in events if m.start.hour == 6],
                         [timedelta(hours=1), timedelta(hours=2), timedelta(hours=2)])
        fall = datetime(2026, 10, 25, tzinfo=calendar.TZ)
        self.assertEqual(len(calendar.meals_in_range(slots, fall.date(), fall, fall + timedelta(days=1))), 1)
        utc = self.now.astimezone(timezone.utc)
        self.assertEqual(self.events([meal()], utc, utc + timedelta(days=1))[0].start.hour, 21)

    def test_midnight_overlap(self):
        end = self.now.replace(hour=0) + timedelta(days=1, seconds=15)
        start = end - timedelta(seconds=30)
        events = self.events([meal('23:59:30')], start, end)
        self.assertEqual(len(events), 1)

    def test_calendar_view_optional_and_language(self):
        e = dashboard.find_entities(registry())
        for lang, title in [('fr', 'Repas programmés'), ('en', 'Scheduled meals')]:
            result = dashboard.make_dashboard(e, lang)
            self.assertEqual(len(result['views']), 3)
            view = result['views'][1]
            self.assertEqual(view['title'], title)
            self.assertEqual(view['cards'][0]['entities'], [e['meal_calendar']])
            self.assertEqual(view['cards'][0]['type'], 'calendar')
        self.assertEqual(len(dashboard.make_dashboard(dashboard.find_entities(registry(False)))['views']), 1)

    def test_disabled_calendar_not_included(self):
        r = registry()
        for row in r['data']['entities']:
            if row['entity_id'].startswith('calendar.'):
                row['disabled_by'] = 'user'
        self.assertEqual([v['path'] for v in dashboard.make_dashboard(dashboard.find_entities(r))['views']], ['feeding', 'feeding-history'])


class CalendarEntityTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the thin HA adapter with offline stubs, not a live HA instance."""

    def setUp(self):
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch
        from dataclasses import dataclass

        package = ModuleType('calendar_test_package')
        package.__path__ = []
        ha = ModuleType('homeassistant.components.calendar')
        exceptions = ModuleType('homeassistant.exceptions')
        entity = ModuleType('calendar_test_package.entity')
        const = ModuleType('calendar_test_package.const')

        class CalendarEntity:
            pass

        @dataclass
        class CalendarEvent:
            start: datetime
            end: datetime
            summary: str
            description: str
            uid: str

        class HomeAssistantError(Exception):
            pass

        class NutriPalEntity:
            def __init__(self, coordinator, key):
                self.coordinator = coordinator
                self.key = key
                self.hass = SimpleNamespace(config=SimpleNamespace(language='fr'))

        ha.CalendarEntity, ha.CalendarEvent = CalendarEntity, CalendarEvent
        exceptions.HomeAssistantError = HomeAssistantError
        entity.NutriPalEntity = NutriPalEntity
        const.DOMAIN = 'mova_nutripal'
        self.error = HomeAssistantError
        self.enterContext(patch.dict(sys.modules, {
            'homeassistant.components.calendar': ha,
            'homeassistant.exceptions': exceptions,
            'calendar_test_package': package,
            'calendar_test_package.entity': entity,
            'calendar_test_package.const': const,
            'calendar_test_package.calendar_schedule': calendar,
        }))
        spec = importlib.util.spec_from_file_location('calendar_test_package.calendar', ROOT / 'custom_components/mova_nutripal/calendar.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        now = MealCalendarTests.now
        clock = self.enterContext(patch.object(module, 'datetime'))
        clock.now.return_value = now
        self.coordinator = SimpleNamespace(last_update_success=True, stopping=False,
            data=dict(online=True, schedule_date=now.date().isoformat(), schedule=[meal()]))
        self.entity = module.NutriPalCalendar(self.coordinator)
        self.now = now

    async def test_entity_returns_next_and_range_events(self):
        self.assertTrue(self.entity.available)
        event = self.entity.event
        self.assertEqual(event.summary, 'Repas programmé · 5 portions')
        self.assertEqual(event.start.hour, 21)
        self.assertIn('Ne confirme pas', event.description)
        events = await self.entity.async_get_events(self.entity.hass, self.now, self.now + timedelta(days=2))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], event)
        self.entity.hass.config.language = 'en'
        self.assertEqual(self.entity.event.summary, 'Scheduled meal · 5 portions')

    async def test_unavailable_and_empty_are_distinct(self):
        self.coordinator.last_update_success = False
        self.assertFalse(self.entity.available)
        self.assertIsNone(self.entity.event)
        with self.assertRaises(self.error):
            await self.entity.async_get_events(self.entity.hass, self.now, self.now + timedelta(days=1))
        self.coordinator.last_update_success = True
        self.coordinator.data['schedule'] = []
        self.assertTrue(self.entity.available)
        self.assertIsNone(self.entity.event)
        self.assertEqual(await self.entity.async_get_events(self.entity.hass, self.now, self.now + timedelta(days=1)), [])
