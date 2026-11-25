"""Experimental mass-balance observations. Never used to authorize feeding."""
from datetime import datetime, date, time
from math import isfinite
from statistics import median

from .calendar_schedule import TZ, current_slots, _unambiguous_start

MAX_RECORDS = 30
MAX_SNAPSHOT_SECONDS = 30
WINDOW_SECONDS = 360  # Pre-meal window and legacy records.
POST_WINDOW_SECONDS = 1800
MIN_FINAL_SECONDS = 1500
STABLE_SECONDS = 300
PEAK_TOLERANCE_GRAMS = 1
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
    if any(b[0] - a[0] <= WINDOW_SECONDS + POST_WINDOW_SECONDS for a, b in zip(result, result[1:])):
        return None
    return result


def observation_window(data, now):
    """Only extend polling for supported, non-overlapping scheduled meals."""
    schedule = _schedule(data, now)
    return bool(schedule and any(-WINDOW_SECONDS <= now.timestamp() - due <= POST_WINDOW_SECONDS
                                 for due, _, _ in schedule))


class CompensatedCalibration:
    """Compare stable bowl + cumulative intake around one autonomous meal.

    Monitor the early bowl peak and require a late, stable mass balance.
    Cloud consistency is not proof of true weight; diagnostics only.
    """
    def __init__(self):
        self.reset()

    def reset(self, status='waiting'):
        self.key = self.previous = self.baseline = self.post = None
        self.status = status
        self.peak = None
        self.last_post = None
        self.stable_start = None
        self.stable_mass = None

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
        nearby = [row for row in schedule if -WINDOW_SECONDS <= stamp - row[0] <= POST_WINDOW_SECONDS]
        if len(nearby) != 1:
            self.reset('waiting'); return None
        due, portions, finished = nearby[0]
        key = (now.astimezone(TZ).date().isoformat(), due, tuple((t, p) for t, p, _ in schedule))
        if self.key != key:
            self.reset(); self.key = key
        if self.status in ('recorded', 'rejected'):
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
        # Track bowl readings even before the counter catches up. A later estimate
        # must not imply less food than the bowl actually held above baseline.
        if self.last_post is None and stamp - due > 180:
            self.reset('missing_early_observation'); return None
        if self.last_post is not None:
            gap = stamp - self.last_post['timestamp']
            if not 0 < gap <= 120 or obs['intake'] < self.last_post['intake'] or obs['count'] < self.last_post['count']:
                self.reset('observation_gap_or_counter_reset'); return None
        self.last_post = obs
        if self.peak is None or obs['bowl'] > self.peak['bowl']:
            self.peak = dict(obs)
        if (not finished or data['device_status'] != 1 or stamp - duration - due < 90
                or obs['count'] != base['count'] + portions):
            self.post = self.stable_start = self.stable_mass = None
            self.status = 'waiting_completion'; return None
        mass = obs['bowl'] + obs['intake']
        if (self.post is None or not _stable(self.post, obs)
                or abs(mass - self.stable_mass) > STABILITY_GRAMS):
            self.stable_start = stamp
            self.stable_mass = mass
        self.post = obs
        if stamp - duration - due < MIN_FINAL_SECONDS:
            self.status = 'consolidating'; return None
        stable = stamp - self.stable_start >= STABLE_SECONDS
        net = mass - base['bowl'] - base['intake']
        lower_bound = max(0, self.peak['bowl'] - base['bowl']) if self.peak else None
        reason = ('missing_peak' if lower_bound is None else
                  'below_observed_peak' if net + PEAK_TOLERANCE_GRAMS < lower_bound else
                  'out_of_range' if not 2 <= net / portions <= 20 else
                  'unstable_mass' if not stable else None)
        # Give late cloud counters another chance until the last minute.
        if reason and stamp - due < POST_WINDOW_SECONDS - 60:
            self.status = reason; return None
        self.status = 'rejected' if reason else 'recorded'
        return {'day': key[0], 'due': due, 'portions': portions,
                'before': dict(base), 'after': obs, 'peak': self.peak,
                'distributed': round(net, 2), 'weight': round(net / portions, 2),
                'method_version': 2, 'quality': 'rejected' if reason else 'accepted',
                'reason': reason, 'stable_since': self.stable_start}


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
        common = (0 < due - before['timestamp'] <= 180
                  and after['count'] - before['count'] == portions and after['intake'] >= before['intake']
                  and type(record['distributed']) in (int, float) and record['distributed'] == round(net, 2)
                  and type(record['weight']) in (int, float) and record['weight'] == round(net / portions, 2))
        if not common:
            return False
        if 'method_version' not in record:
            return 90 <= after['timestamp'] - due <= WINDOW_SECONDS and 2 <= net / portions <= 20
        if record['method_version'] != 2 or not MIN_FINAL_SECONDS <= after['timestamp'] - due <= POST_WINDOW_SECONDS:
            return False
        peak = record['peak']
        if peak is not None:
            if (not _number(peak['bowl']) or not _number(peak['intake'])
                    or not due <= peak['timestamp'] <= after['timestamp']
                    or type(peak['count']) is not int or not before['count'] <= peak['count'] <= after['count']
                    or not before['intake'] <= peak['intake'] <= after['intake']
                    or peak['bowl'] < after['bowl']):
                return False
        since = record['stable_since']
        if type(since) not in (int, float) or not due <= since <= after['timestamp']:
            return False
        lower = max(0, peak['bowl'] - before['bowl']) if peak is not None else None
        reason = ('missing_peak' if lower is None else
                  'below_observed_peak' if net + PEAK_TOLERANCE_GRAMS < lower else
                  'out_of_range' if not 2 <= net / portions <= 20 else
                  'unstable_mass' if after['timestamp'] - since < STABLE_SECONDS else None)
        return (record['reason'] == reason and record['quality'] == ('rejected' if reason else 'accepted')
                and (reason is None or after['timestamp'] - due >= POST_WINDOW_SECONDS - 60))
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
    accepted = [r for r in records if r.get('method_version') == 2 and r.get('quality') == 'accepted' and valid_record(r)]
    return {'compensated_samples': len(accepted),
            'compensated_weight': round(median(r['weight'] for r in accepted), 2) if accepted else None}
