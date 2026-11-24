"""Experimental mass-balance observations. Never used to authorize feeding."""
from datetime import datetime, date, time
from math import isfinite
from statistics import median

from .calendar_schedule import TZ, current_slots, _unambiguous_start

MAX_RECORDS = 30
MAX_SNAPSHOT_SECONDS = 30
WINDOW_SECONDS = 360
STABILITY_GRAMS = 1


def _number(value):
    return type(value) in (int, float) and isfinite(value) and 0 <= value <= 10000


def _stable(first, second):
    return (20 <= second['timestamp'] - first['timestamp'] <= 120
            and first['count'] == second['count']
            and second['intake'] >= first['intake']
            and abs(first['bowl'] + first['intake'] - second['bowl'] - second['intake']) <= STABILITY_GRAMS)


def _schedule(data, now):
    slots = current_slots(data, now)
    if slots is None:
        return None
    # Do not accept simultaneous meals or overlapping observation windows.
    rows = [row for row in data['schedule'] if row['status']]
    if len(rows) != len(slots):
        return None
    result = []
    for (at, portions) in slots:
        due = _unambiguous_start(now.astimezone(TZ).date(), at)
        if due is None:
            return None
        row = next(row for row in rows if time.fromisoformat(row['feedingTime']) == at)
        result.append((due.timestamp(), portions, row['planFinishStatus']))
    if any(b[0] - a[0] <= 2 * WINDOW_SECONDS for a, b in zip(result, result[1:])):
        return None
    return result


class CompensatedCalibration:
    """Compare stable bowl + cumulative intake around one autonomous meal.

    Two pre- and two post-readings reduce, but cannot eliminate, cloud skew.
    A post-reading is only considered after the plan reports completion.
    """
    def __init__(self):
        self.reset()

    def reset(self, status='waiting'):
        self.key = self.previous = self.baseline = self.post = None
        self.status = status

    def observe(self, data, now, duration):
        if (now.utcoffset() is None or not _number(duration) or duration > MAX_SNAPSHOT_SECONDS
                or data.get('device_status') not in (1, 2)
                or data.get('warning_mask') != 0 or data.get('fault_mask') != 0
                or not all(_number(data.get(k)) for k in ('bowl_weight', 'intake_today'))
                or type(data.get('portions_today')) is not int
                or not 0 <= data['portions_today'] <= 10000):
            self.reset('invalid_reading'); return None
        schedule = _schedule(data, now)
        if schedule is None:
            self.reset('unsupported_schedule'); return None
        stamp = now.timestamp()
        nearby = [row for row in schedule if abs(stamp - row[0]) <= WINDOW_SECONDS]
        if len(nearby) != 1:
            self.reset('waiting'); return None
        due, portions, finished = nearby[0]
        key = (now.astimezone(TZ).date().isoformat(), due, tuple((t, p) for t, p, _ in schedule))
        if self.key != key:
            self.reset(); self.key = key
        if self.status == 'recorded':
            return None
        if any((t < due and not done) or (t > due and done) for t, _, done in schedule):
            self.reset('inconsistent_schedule'); return None
        obs = {'timestamp': stamp, 'count': data['portions_today'],
               'bowl': data['bowl_weight'], 'intake': data['intake_today']}
        if stamp < due:
            # The pre-snapshot must finish before the scheduled time.
            if finished or data['device_status'] != 1:
                self.reset('inconsistent_schedule'); return None
            if self.previous and _stable(self.previous, obs):
                self.baseline = obs
                self.status = 'baseline_ready'
            else:
                self.baseline = None
                self.status = 'collecting_baseline'
            self.previous = obs
            return None
        base = self.baseline
        if base is None or due - base['timestamp'] > 180:
            self.reset('missing_baseline'); return None
        if (obs['intake'] < base['intake'] or obs['count'] < base['count']
                or obs['count'] > base['count'] + portions):
            self.reset('counter_inconsistent'); return None
        if (not finished or data['device_status'] != 1 or stamp - due < 90
                or obs['count'] != base['count'] + portions):
            self.post = None; self.status = 'waiting_completion'; return None
        # Do not use a snapshot spanning the first 90 seconds after dispensing.
        if stamp - duration - due < 90:
            self.post = None; self.status = 'waiting_completion'; return None
        if self.post is not None and obs['intake'] < self.post['intake']:
            self.reset('counter_inconsistent'); return None
        if self.post is None or not _stable(self.post, obs):
            self.post = obs; self.status = 'collecting_post'; return None
        net = obs['bowl'] - base['bowl'] + obs['intake'] - base['intake']
        weight = net / portions
        if not 2 <= weight <= 20:
            self.reset('out_of_range'); return None
        self.status = 'recorded'
        return {'day': key[0], 'due': due, 'portions': portions,
                'before': dict(base), 'after': obs,
                'distributed': round(net, 2), 'weight': round(weight, 2)}


def valid_record(record):
    """Validate persisted diagnostic records independently of safety samples."""
    try:
        day = date.fromisoformat(record['day'])
        due, portions = record['due'], record['portions']
        before, after = record['before'], record['after']
        if (type(due) not in (int, float) or not isfinite(due)
                or datetime.fromtimestamp(due, TZ).date() != day
                or type(portions) is not int or not 1 <= portions <= 10000):
            return False
        for obs in (before, after):
            if (type(obs['timestamp']) not in (int, float) or not isfinite(obs['timestamp'])
                    or datetime.fromtimestamp(obs['timestamp'], TZ).date() != day
                    or type(obs['count']) is not int or not 0 <= obs['count'] <= 10000
                    or not _number(obs['bowl']) or not _number(obs['intake'])):
                return False
        net = after['bowl'] - before['bowl'] + after['intake'] - before['intake']
        return (0 < due - before['timestamp'] <= 180 and 90 <= after['timestamp'] - due <= WINDOW_SECONDS
                and after['count'] - before['count'] == portions and after['intake'] >= before['intake']
                and _number(record['distributed']) and record['distributed'] == round(net, 2)
                and _number(record['weight']) and 2 <= net / portions <= 20
                and record['weight'] == round(net / portions, 2))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def append_observation(records, record):
    if not valid_record(record):
        return False
    if any(old['day'] == record['day'] and (old['due'] == record['due']
           or old['before']['count'] < record['after']['count']
           and record['before']['count'] < old['after']['count']) for old in records):
        return False
    records.append(record)
    del records[:-MAX_RECORDS]
    return True


def diagnostic_summary(records):
    return {'compensated_samples': len(records),
            'compensated_weight': round(median(r['weight'] for r in records), 2) if records else None}
