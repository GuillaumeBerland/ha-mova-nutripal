"""Read-only daily mass balance. Not an input to dispensing or calibration."""
from copy import deepcopy
from datetime import datetime, date, timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import json

TZ = ZoneInfo('Europe/Paris')  # Same day boundary as the cloud counters.
MAX_BOUNDARY_SECONDS = 360
MAX_DAYS = 30
RETRY_BOUNDARY_SECONDS = 900


def near_midnight(now):
    local = now.astimezone(TZ)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return seconds >= 86400 - 600 or seconds <= RETRY_BOUNDARY_SECONDS


def _weight(v):
    return type(v) in (int, float) and isfinite(v) and 0 <= v <= 100000


def _count(v):
    return type(v) is int and 0 <= v <= 10000


def _day(v):
    return isinstance(v, str) and date.fromisoformat(v).isoformat() == v


def _observation_valid(o):
    return (isinstance(o, dict) and _day(o.get('day'))
            and _weight(o.get('bowl')) and _weight(o.get('intake'))
            and _count(o.get('portions')) and _weight(o.get('reference'))
            and o['reference'] > 0 and _weight(o.get('target')) and o['target'] > 0
            and type(o.get('ts')) in (int, float) and isfinite(o['ts'])
            and datetime.fromtimestamp(o['ts'], TZ).date().isoformat() == o['day'])


def _record(day, intake, portions, opening, closing, reference, target, status):
    mass = None if opening is None or closing is None or intake is None else round(intake + closing - opening, 2)
    if mass is not None and (mass < 0 or (portions == 0 and abs(mass) > 1)):
        status = 'inconsistent'
    if status != 'reconstructed':
        mass = None
    theoretical = round(portions * reference, 2) if portions is not None and reference is not None else None
    return dict(day=day, consumed=intake, portions=portions, opening=opening, closing=closing,
                reference=reference, target=target, reconstructed=mass, theoretical=theoretical,
                difference=round(mass-theoretical, 2) if mass is not None and theoretical is not None else None,
                portion_weight=round(mass/portions, 2) if mass is not None and portions else None,
                quality=status)


class DailyBalance:
    def __init__(self, state=None):
        self.last = None
        self.opening = None
        self.inconsistent = False
        self.history = []
        self.excluded_days = {}
        self.boundary = {}
        if state is not None:
            # Diagnostic data are isolated from the actuator interlock.
            last = state['last']
            if last is not None and not _observation_valid(last):
                raise ValueError('Invalid daily observation')
            opening = state['opening']
            if opening is not None and (last is None or not _weight(opening)):
                raise ValueError('Invalid daily opening')
            if type(state['inconsistent']) is not bool or not isinstance(state['history'], list):
                raise ValueError('Invalid daily state')
            history = []
            for r in state['history'][-MAX_DAYS:]:
                if (not isinstance(r, dict) or not _day(r.get('day'))
                    or r.get('quality') not in ('reconstructed', 'missing_boundary', 'inconsistent')
                    or any(r.get(k) is not None and not _weight(r[k]) for k in ('consumed','opening','closing','reference','target'))
                    or (r.get('portions') is not None and not _count(r['portions']))):
                    raise ValueError('Invalid archived day')
                history.append(_record(r['day'], r['consumed'], r['portions'], r['opening'], r['closing'], r['reference'], r['target'], r['quality']))
            if len({r['day'] for r in history}) != len(history) or any(last and r['day'] >= last['day'] for r in history):
                raise ValueError('Invalid archived dates')
            self.last, self.opening, self.inconsistent = deepcopy(last), opening, state['inconsistent']
            self.history = sorted(history, key=lambda r: r['day'])

            marks = state.get('excluded_days', {})
            if (not isinstance(marks, dict) or len(marks) > MAX_DAYS + 1
                    or any(not _day(day) or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 120
                           for day, reason in marks.items())):
                raise ValueError('Invalid excluded days')
            self.excluded_days = deepcopy(marks)
            diagnostic = state.get('boundary', {})
            if diagnostic:
                if (not isinstance(diagnostic, dict)
                        or diagnostic.get('status') not in ('confirmed', 'retry', 'failed')
                        or not _observation_valid(diagnostic.get('before'))
                        or not _observation_valid(diagnostic.get('after'))
                        or not isinstance(diagnostic.get('reasons'), list)):
                    raise ValueError('Invalid boundary diagnostic')
                self.boundary = deepcopy(diagnostic)

    def mark_day(self, day, today, reason):
        """Flag a non-representative day without changing raw observations."""
        if type(day) is not date or not today - timedelta(days=MAX_DAYS) <= day <= today:
            raise ValueError('Date must be within the last 30 days')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 120:
            raise ValueError('Enter a reason of 1 to 120 characters')
        key = day.isoformat()
        changed = self.excluded_days.get(key) != reason.strip()
        self.excluded_days[key] = reason.strip()
        self.prune_marks(today)
        return changed

    def prune_marks(self, today):
        cutoff = (today - timedelta(days=MAX_DAYS)).isoformat()
        self.excluded_days = {k:v for k,v in self.excluded_days.items() if cutoff <= k <= today.isoformat()}

    def export(self):
        return deepcopy(dict(last=self.last, opening=self.opening, inconsistent=self.inconsistent,
                             history=self.history, excluded_days=self.excluded_days, boundary=self.boundary))

    def observe(self, data, now, duration, reference, target):
        """Return True when a fresh observation can be persisted.

        A midnight boundary is inferred only from matching observations on both
        sides, within six minutes, with unchanged bowl and verified daily counters.
        No retroactive filling of unobserved opening or closing weights.
        """
        now = now.astimezone(TZ)
        o = dict(day=now.date().isoformat(), ts=now.timestamp(), bowl=data.get('bowl_weight'),
                 intake=data.get('intake_today'), portions=data.get('portions_today'),
                 reference=reference, target=target)
        if (data.get('online') is not True or data.get('device_status') != 1
                or data.get('warning_mask') != 0 or data.get('fault_mask') != 0
                or not 0 <= duration <= 30 or not _observation_valid(o)):
            return False
        prev = self.last
        if prev and o['ts'] <= prev['ts']:
            return False
        if prev and o['day'] != prev['day']:
            adjacent = date.fromisoformat(o['day']) - date.fromisoformat(prev['day']) == timedelta(days=1)
            midnight = datetime.combine(now.date(), datetime.min.time(), TZ).timestamp()
            yesterday_intake, yesterday_portions = data.get('intake_yesterday'), data.get('portions_yesterday')
            checks = {
                'non_adjacent_day': adjacent,
                'before_outside_window': 0 <= midnight-prev['ts'] <= MAX_BOUNDARY_SECONDS,
                'after_outside_window': 0 <= o['ts']-midnight <= MAX_BOUNDARY_SECONDS,
                'yesterday_intake_mismatch': _weight(yesterday_intake) and yesterday_intake == prev['intake'],
                'yesterday_portions_mismatch': _count(yesterday_portions) and yesterday_portions == prev['portions'],
                'today_counters_not_zero': o['intake'] == 0 and o['portions'] == 0,
                'bowl_changed': o['bowl'] == prev['bowl'],
            }
            reasons = [key for key, ok in checks.items() if not ok]
            boundary = not reasons
            # Retry ONLY delayed yesterday totals: today's counters must already be zero,
            # the bowl unchanged, and both original observations within six minutes.
            retry = (bool(reasons) and set(reasons) <= {'yesterday_intake_mismatch', 'yesterday_portions_mismatch'}
                     and (not _weight(yesterday_intake) or yesterday_intake <= prev['intake'])
                     and (not _count(yesterday_portions) or yesterday_portions <= prev['portions']))
            self.boundary = dict(status='confirmed' if boundary else 'retry' if retry else 'failed',
                                 reasons=reasons, before=deepcopy(prev), after=deepcopy(o),
                                 yesterday_intake=yesterday_intake if _weight(yesterday_intake) else None,
                                 yesterday_portions=yesterday_portions if _count(yesterday_portions) else None)
            complete = boundary and self.opening is not None and not self.inconsistent
            # Yesterday's counters are only attributable to the immediately preceding day.
            intake = yesterday_intake if adjacent and _weight(yesterday_intake) else None
            portions = yesterday_portions if adjacent and _count(yesterday_portions) else None
            status = 'inconsistent' if self.inconsistent else 'reconstructed' if complete else 'missing_boundary'
            self.history.append(_record(prev['day'], intake, portions, self.opening,
                                        prev['bowl'] if boundary else None, prev['reference'], prev['target'], status))
            cutoff = (now.date()-timedelta(days=MAX_DAYS)).isoformat()
            self.history = [r for r in self.history if r['day'] >= cutoff][-MAX_DAYS:]
            self.opening = o['bowl'] if boundary else None
            self.inconsistent = False
        elif prev:
            self._retry_boundary(o, prev, data, now)
            if o['portions'] < prev['portions'] or o['intake'] < prev['intake']:
                self.inconsistent = True
        self.last = o
        self.prune_marks(now.date())
        return True

    def _retry_boundary(self, o, prev, data, now):
        b = self.boundary
        if b.get('status') != 'retry':
            return
        before, first = b['before'], b['after']
        midnight = datetime.combine(now.date(), datetime.min.time(), TZ).timestamp()
        yi, yp = data.get('intake_yesterday'), data.get('portions_yesterday')
        b['yesterday_intake'] = yi if _weight(yi) else None
        b['yesterday_portions'] = yp if _count(yp) else None
        # Check the original evidence again, including when restored after a restart.
        safe = (first['day'] == o['day'] == prev['day']
                and date.fromisoformat(o['day']) - date.fromisoformat(before['day']) == timedelta(days=1)
                and 0 <= midnight-before['ts'] <= MAX_BOUNDARY_SECONDS
                and 0 <= first['ts']-midnight <= MAX_BOUNDARY_SECONDS
                and 0 <= o['ts']-midnight <= RETRY_BOUNDARY_SECONDS
                and 0 < o['ts']-prev['ts'] <= MAX_BOUNDARY_SECONDS
                and before['bowl'] == first['bowl'] == prev['bowl'] == o['bowl']
                and first['intake'] == first['portions'] == prev['intake'] == prev['portions'] == o['intake'] == o['portions'] == 0
                and not self.inconsistent and self.opening is None
                and self.history and self.history[-1]['day'] == before['day'])
        if not safe:
            b.update(status='failed', reasons=['retry_window_or_observations_changed'])
            return
        if (_weight(yi) and yi > before['intake']) or (_count(yp) and yp > before['portions']):
            b.update(status='failed', reasons=['yesterday_counters_changed'])
            return
        if not (_weight(yi) and yi == before['intake'] and _count(yp) and yp == before['portions']):
            return
        row = self.history[-1]
        # A valid closing observation still does not repair a missing opening or a prior inconsistency.
        status = 'inconsistent' if row['quality'] == 'inconsistent' else 'reconstructed' if row['opening'] is not None else 'missing_boundary'
        self.history[-1] = _record(row['day'], yi, yp, row['opening'], before['bowl'],
                                   row['reference'], row['target'], status)
        self.opening = o['bowl']
        b.update(status='confirmed', reasons=[], confirmed_at=o['ts'])

    def summary(self, data, now, fresh=True):
        """Publish only if the current raw snapshot matches the saved observation."""
        o = self.last
        current = (fresh and o is not None and o['day'] == now.astimezone(TZ).date().isoformat()
                   and data.get('online') is True and data.get('device_status') == 1
                   and data.get('warning_mask') == 0 and data.get('fault_mask') == 0
                   and (data.get('bowl_weight'), data.get('intake_today'), data.get('portions_today'))
                       == (o['bowl'], o['intake'], o['portions']))
        r = _record(o['day'], o['intake'], o['portions'], self.opening, o['bowl'], o['reference'], o['target'],
                    'inconsistent' if self.inconsistent else 'missing_boundary' if self.opening is None else 'reconstructed') if current else {}
        # Preserve the raw history; never advertise an excluded day as representative.
        day = now.astimezone(TZ).date().isoformat()
        excluded = day in self.excluded_days
        if excluded:
            r.update(quality='excluded', excluded_reason=self.excluded_days[day])
        mass = None if excluded else r.get('reconstructed')
        theoretical, forecast = data.get('estimated_distributed'), data.get('forecast')
        corrected = (round(mass+forecast-theoretical, 2) if mass is not None and _weight(theoretical)
                     and _weight(forecast) and forecast >= theoretical
                     and data.get('decision') not in ('schedule_uncertain', 'unavailable') else None)
        return dict(daily_reconstructed=mass, daily_portion_weight=None if excluded else r.get('portion_weight'),
                    daily_difference=round(mass-theoretical, 2) if mass is not None and _weight(theoretical) else None,
                    daily_corrected_forecast=corrected, daily_quality=r.get('quality', 'unavailable'),
                    daily_history_count=len(self.history),
                    daily_history=[dict(deepcopy(row), excluded_reason=self.excluded_days.get(row['day']))
                                   for row in self.history], daily_current=r, daily_boundary=deepcopy(self.boundary),
                    daily_excluded_days=deepcopy(self.excluded_days),
                    daily_yesterday_excluded=(now.astimezone(TZ).date()-timedelta(days=1)).isoformat() in self.excluded_days)


def load_daily(path):
    try:
        with Path(path).open(encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return DailyBalance()
    if raw['version'] != 1:
        raise ValueError('Unsupported daily state')
    return DailyBalance(raw['state'])
