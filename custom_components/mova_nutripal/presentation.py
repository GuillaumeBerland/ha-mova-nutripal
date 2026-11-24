"""Read-only display helpers. Never used to authorize dispensing."""
from datetime import datetime, time, timedelta


def next_scheduled_meal(schedule, now):
    """Return (timestamp, portions) for a supported daily schedule, or None.

    Unknown, expired or overdue-unconfirmed schedules are not extrapolated.
    Only the confirmed daily kibble schedule is supported by this display.
    """
    if not isinstance(schedule, list) or now.tzinfo is None:
        return None
    candidates = []
    for meal in schedule:
        if not isinstance(meal, dict) or type(meal.get('status')) is not bool:
            return None
        if not meal['status']:
            continue
        if (meal.get('repeatType') != 1 or meal.get('expireStatus') is not False
                or type(meal.get('planFinishStatus')) is not bool
                or type(meal.get('portions')) is not int or meal['portions'] < 1
                or meal.get('supperFlag') != 0):
            return None
        try:
            at = time.fromisoformat(meal['feedingTime'])
            if at.tzinfo is not None:
                return None
            due = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
        except (KeyError, TypeError, ValueError):
            return None
        if meal['planFinishStatus']:
            if due > now:
                return None
            due = datetime.combine(now.date() + timedelta(days=1), at, tzinfo=now.tzinfo)
        elif due <= now:
            return None
        candidates.append((due, meal['portions']))
    if not candidates:
        return None
    due = min(row[0] for row in candidates)
    return due, sum(portions for at, portions in candidates if at == due)
