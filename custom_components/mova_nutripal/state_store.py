"""Small durable local state for actuator interlock and calibration."""
import json
import os
import tempfile
from pathlib import Path
from math import isfinite


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
