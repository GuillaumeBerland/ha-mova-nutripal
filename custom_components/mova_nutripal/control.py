"""Explicit user-triggered commands only. No automatic actuator."""
from urllib.parse import urlsplit
from math import isfinite


def send_one(cloud, did):
    original = cloud._http
    attempted = False

    def guarded(method, url, headers, body, timeout):
        nonlocal attempted
        path = urlsplit(url).path
        if attempted or not path.endswith('/device/sendCommand') or method != 'POST':
            raise RuntimeError('Duplicate or unexpected actuator request blocked')
        attempted = True
        # Fresh connections do not enter the transport retry path.
        for key in list(cloud._conns):
            cloud._close_conn(key)
        return original(method, url, headers, body, timeout)

    cloud._http = guarded
    try:
        result = cloud.send('action', {'did': str(did), 'siid': 3, 'aiid': 1,
                                      'in': [{'piid': 1, 'value': 1}]}, retry_count=0, timeout=15)
        return attempted and isinstance(result, dict) and type(result.get('code')) is int and result['code'] == 0
    finally:
        cloud._http = original


def manual_allowed(data, options, state, now):
    if not options.get('manual_enabled'):
        return 'disabled'
    if state.get('pending') is not None:
        return 'pending'
    last = state.get('last_attempt', 0)
    if type(last) not in (int, float) or not isfinite(last) or now.timestamp() - last < 1800:
        return 'cooldown'
    if data.get('decision') != 'would_feed' or data.get('suggested_portions', 0) < 1:
        return 'blocked'
    return 'ready'


def confirm_pending(pending, data, now):
    """Confirmation requires ACK, idle, correct day and exact increment.
    A timeout or conflict is never cleared by a later daily rollover.
    """
    if not isinstance(pending, dict) or pending.get('ack') is not True:
        return False
    if pending.get('day') != now.date().isoformat():
        return False
    age = now.timestamp() - pending.get('time', 0)
    if not 0 <= age <= 180:
        return False
    return (data.get('online') is True and data.get('device_status') == 1
            and data.get('warning_mask') == 0 and data.get('fault_mask') == 0
            and type(data.get('portions_today')) is int
            and data['portions_today'] == pending.get('count', -2) + 1)
