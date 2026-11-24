"""Conservative passive estimator; observations are not certified weights."""
from math import isfinite
from statistics import median
from datetime import time, datetime


def number(v):
    return type(v) in (int, float) and isfinite(v) and v >= 0


def near_meal(data, now, window=360):
    for row in data.get('schedule') or []:
        if not isinstance(row, dict) or row.get('status') is not True:
            continue
        try:
            due = datetime.combine(now.date(), time.fromisoformat(row['feedingTime']), tzinfo=now.tzinfo)
            if abs((due - now).total_seconds()) <= window:
                return True
        except (TypeError, ValueError, KeyError):
            pass
    return False


def effective_weight(samples, reference, enabled=True):
    valid = [v for v in samples if number(v) and 2 <= v <= 20]
    return round(median(valid), 2) if enabled and len(valid) >= 3 else reference


class Calibration:
    """Requires two stable pre-readings, counter increment, stable post-readings,
    and unchanged intake/count over a delayed confirmation interval.
    Discard on missing data, faults, day change, or competing observations.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = self.baseline = self.candidate = None

    def observe(self, data, now):
        if (data.get('online') is not True or data.get('warning_mask') != 0
                or data.get('fault_mask') != 0 or data.get('device_status') not in (1, 2)
                or not all(number(data.get(k)) for k in ('bowl_weight','intake_today','meals_today','portions_today'))
                or type(data['portions_today']) is not int):
            self.reset(); return None
        # Samples are accepted only while idle. In-progress readings cannot establish stability.
        if data['device_status'] != 1:
            self.previous = None
            return None
        obs = (now.timestamp(), now.date(), data['portions_today'], data['intake_today'], data['meals_today'], data['bowl_weight'])
        if self.baseline and (obs[1] != self.baseline[1] or obs[0] - self.baseline[0] > 240):
            self.reset()
        prev = self.previous
        stable = bool(prev and 10 <= obs[0]-prev[0] <= 100 and obs[1:] == prev[1:])
        self.previous = obs
        base = self.baseline
        if base is None:
            if stable: self.baseline = obs
            return None
        if obs[1] != base[1] or obs[3:5] != base[3:5] or obs[2] < base[2]:
            self.reset(); self.previous = obs; return None
        delta = obs[2] - base[2]
        if delta == 0:
            if obs[5] != base[5]:
                self.baseline = self.candidate = None
            elif stable:
                self.baseline = obs
            return None
        if not 1 <= delta <= 10:
            self.reset(); return None
        if self.candidate and obs[2] != self.candidate[2]:
            self.reset(); return None
        if not stable:
            if self.candidate and obs[5] != self.candidate[5]: self.candidate = None
            return None
        value = (obs[5] - base[5]) / delta
        if not 2 <= value <= 20:
            self.reset(); return None
        if self.candidate is None:
            # The first stable post-distribution reading must be close to the baseline.
            if obs[0] - base[0] > 150:
                self.reset(); return None
            self.candidate = obs
            return None
        if obs[0] - self.candidate[0] >= 60 and obs[1:] == self.candidate[1:]:
            self.reset(); self.previous = obs
            return round(value, 2)
        return None
