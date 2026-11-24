"""Read-only expansion of the supported daily MOVA schedule."""
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
HORIZON_DAYS = 60  # Today plus the next 59 days, never historical reconstruction.
EVENT_DURATION = timedelta(minutes=1)  # Calendar marker, not actual dispensing duration.


class Meal(NamedTuple):
    start: datetime
    end: datetime
    portions: int


def schedule_slots(rows):
    """Return sorted (local time, portions) pairs, or None for unsupported data."""
    if not isinstance(rows, list):
        return None
    slots = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get('status')) is not bool:
            return None
        if not row['status']:
            continue
        if (type(row.get('repeatType')) is not int or row['repeatType'] != 1
                or row.get('expireStatus') is not False
                or type(row.get('planFinishStatus')) is not bool
                or type(row.get('supperFlag')) is not int or row['supperFlag'] != 0
                or type(row.get('portions')) is not int or row['portions'] < 1):
            return None
        try:
            at = time.fromisoformat(row['feedingTime'])
        except (KeyError, TypeError, ValueError):
            return None
        if at.tzinfo is not None:
            return None
        slots[at] = slots.get(at, 0) + row['portions']
    return sorted(slots.items())


def current_slots(data, now):
    """Require a schedule fetched for the current MOVA local day."""
    if (not isinstance(data, dict) or now.utcoffset() is None
            or data.get('online') is not True
            or data.get('schedule_date') != now.astimezone(TZ).date().isoformat()):
        return None
    return schedule_slots(data.get('schedule'))


def _unambiguous_start(day, at):
    wall = datetime.combine(day, at)
    first = wall.replace(tzinfo=TZ, fold=0)
    second = wall.replace(tzinfo=TZ, fold=1)
    # A gap or repeated hour has different offsets. MOVA's DST policy is unknown.
    if first.utcoffset() != second.utcoffset():
        return None
    return first


def meals_in_range(slots, anchor: date, start, end):
    """Expand the current plan only; use inclusive start/exclusive end overlap."""
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError('Calendar range must be timezone-aware')
    start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if end_utc <= start_utc:
        return []
    first = max(anchor, start.astimezone(TZ).date() - timedelta(days=1))
    last = min(anchor + timedelta(days=HORIZON_DAYS - 1), end.astimezone(TZ).date())
    meals = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        for at, portions in slots:
            due = _unambiguous_start(day, at)
            if due is None:
                continue
            due_utc = due.astimezone(timezone.utc)
            finish = due_utc + EVENT_DURATION
            if due_utc < end_utc and finish > start_utc:
                meals.append(Meal(due, finish.astimezone(TZ), portions))
    return sorted(meals, key=lambda meal: meal.start.astimezone(timezone.utc))
