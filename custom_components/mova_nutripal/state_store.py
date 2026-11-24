"""Small durable local state for actuator interlock and calibration."""
import json
import os
import tempfile
from pathlib import Path
from math import isfinite
from datetime import date, timedelta
from copy import deepcopy
from .compensated import MAX_RECORDS, append_observation


MAX_SAMPLES = 15


def _valid_weight(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _validate_detail(detail, sample):
    if detail is None:  # Pre-assisted calibration records have no event identity.
        return
    if not isinstance(detail, dict) or detail.get('source') not in ('passive', 'assisted'):
        raise ValueError('Invalid calibration source')
    try:
        day = date.fromisoformat(detail['day'])
        start, end = detail['start_count'], detail['end_count']
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid calibration event') from None
    if day.isoformat() != detail['day'] or type(start) is not int or type(end) is not int or not 0 <= start < end <= 10000:
        raise ValueError('Invalid calibration counters')
    if detail['source'] == 'assisted':
        before, after = detail.get('before'), detail.get('after')
        if not _valid_weight(before) or not _valid_weight(after) or not before < after <= 10000:
            raise ValueError('Invalid assisted weighing')
        if round((after - before) / (end - start), 2) != sample:
            raise ValueError('Assisted weighing does not match sample')


def sample_details(state):
    """Preserve legacy samples without claiming their unknown provenance."""
    return state.get('sample_details', [None] * len(state['samples']))


def assisted_measurement(day, today, portions, daily_counter, weight_before, weight_after, confirmed):
    """Build a sample from an explicit, independently checked weighing."""
    if confirmed is not True:
        raise ValueError('Confirm no food was eaten, added or removed during weighing')
    if type(day) is not date or not today - timedelta(days=30) <= day <= today:
        raise ValueError('Measurement date must be within the last 30 days')
    if type(portions) is not int or not 1 <= portions <= 100:
        raise ValueError('Portions must be an integer from 1 to 100')
    if type(daily_counter) is not int or not portions <= daily_counter <= 10000:
        raise ValueError('Invalid daily portions counter after dispensing')
    if not _valid_weight(weight_before) or not _valid_weight(weight_after) or not weight_before < weight_after <= 10000:
        raise ValueError('Invalid bowl weights')
    weight = (weight_after - weight_before) / portions
    if not 2 <= weight <= 20:
        raise ValueError('Measured portion must be between 2 and 20 g')
    return round(weight, 2), {'source': 'assisted', 'day': day.isoformat(),
                              'start_count': daily_counter - portions, 'end_count': daily_counter,
                              'before': weight_before, 'after': weight_after}


def append_sample(state, value, detail):
    """Reject overlapping identified dispensing events, regardless of source."""
    if not _valid_weight(value) or not 2 <= value <= 20:
        raise ValueError('Invalid calibration sample')
    _validate_detail(detail, value)
    details = sample_details(state)
    if detail is not None and any(
        old is not None and old['day'] == detail['day']
        and old['start_count'] < detail['end_count']
        and detail['start_count'] < old['end_count'] for old in details
    ):
        return False
    state['samples'] = (state['samples'] + [value])[-MAX_SAMPLES:]
    state['sample_details'] = (details + [detail])[-MAX_SAMPLES:]
    return True


def calibration_history(state):
    return [{'weight': weight, **(deepcopy(detail) if detail is not None else {'source': 'legacy'})}
            for weight, detail in zip(state['samples'], sample_details(state))]


def load_state(path):
    try:
        with Path(path).open('r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported safety state')
    state = data.get('state')
    if not isinstance(state, dict) or not {'samples','pending','last_attempt','last_result'} <= state.keys():
        raise ValueError('Incomplete safety state')
    if (not isinstance(state['samples'], list) or len(state['samples']) > 15
        or any(type(x) not in (int,float) or not isfinite(x) or not 2 <= x <= 20 for x in state['samples'])):
        raise ValueError('Invalid calibration')
    if 'sample_details' in state:
        details = state['sample_details']
        if not isinstance(details, list) or len(details) != len(state['samples']):
            raise ValueError('Invalid calibration details')
        for value, detail in zip(state['samples'], details):
            _validate_detail(detail, value)
        identified = [d for d in details if d is not None]
        for i, a in enumerate(identified):
            for b in identified[:i]:
                if a['day'] == b['day'] and a['start_count'] < b['end_count'] and b['start_count'] < a['end_count']:
                    raise ValueError('Overlapping calibration events')
    if type(state['last_attempt']) not in (int,float) or not isfinite(state['last_attempt']) or state['last_attempt'] < 0:
        raise ValueError('Invalid last attempt')
    pending = state['pending']
    if pending is not None and (not isinstance(pending, dict) or type(pending.get('ack')) is not bool
        or type(pending.get('count')) is not int or pending['count'] < 0
        or type(pending.get('time')) not in (int,float) or not isfinite(pending['time'])
        or not isinstance(pending.get('day'),str)):
        raise ValueError('Invalid pending command')
    if state['last_result'] not in ('none','pending','confirmed','uncertain','acknowledged'):
        raise ValueError('Invalid command state')
    # Bad experimental diagnostics must not invalidate the actuator interlock.
    if 'compensated_records' in state:
        records = state['compensated_records']
        clean = []
        if isinstance(records, list):
            for record in records[-MAX_RECORDS:]:
                append_observation(clean, record)
        state['compensated_records'] = clean
    return state


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'version':1,'state':state}, f, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
    finally:
        if os.path.exists(temp): os.unlink(temp)
