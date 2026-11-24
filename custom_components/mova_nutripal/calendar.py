"""Native read-only calendar for scheduled kibble meals."""
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.exceptions import HomeAssistantError

from .calendar_schedule import HORIZON_DAYS, TZ, current_slots, meals_in_range
from .const import DOMAIN
from .entity import NutriPalEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NutriPalCalendar(coordinator)])


class NutriPalCalendar(NutriPalEntity, CalendarEntity):
    """Expose the current supported schedule, never a feeding command."""

    def __init__(self, coordinator):
        super().__init__(coordinator, 'meal_calendar')

    def _slots(self, now):
        if not self.coordinator.last_update_success or self.coordinator.stopping:
            return None
        return current_slots(self.coordinator.data, now)

    @property
    def available(self):
        return self._slots(datetime.now(TZ)) is not None

    def _event(self, meal):
        fr = self.hass.config.language.split('-')[0] == 'fr'
        quantity = f"{meal.portions} portion{'s' if meal.portions != 1 else ''}"
        summary = f'Repas programmé · {quantity}' if fr else f'Scheduled meal · {quantity}'
        description = (
            'Projection du programme quotidien MOVA actuel, en lecture seule. '
            'Ne confirme pas une distribution réelle. Durée graphique : 1 minute.' if fr else
            'Projection of the current daily MOVA schedule, read-only. '
            'Does not confirm actual dispensing. Calendar marker: 1 minute.'
        )
        return CalendarEvent(start=meal.start, end=meal.end, summary=summary,
                             description=description, uid=meal.start.isoformat())

    @property
    def event(self):
        now = datetime.now(TZ)
        slots = self._slots(now)
        if not slots:
            return None
        meals = meals_in_range(slots, now.date(), now, now + timedelta(days=HORIZON_DAYS))
        return self._event(meals[0]) if meals else None

    async def async_get_events(self, hass, start_date, end_date):
        now = datetime.now(TZ)
        slots = self._slots(now)
        if slots is None:
            raise HomeAssistantError('Current supported MOVA schedule unavailable')
        return [self._event(meal) for meal in meals_in_range(slots, now.date(), start_date, end_date)]
