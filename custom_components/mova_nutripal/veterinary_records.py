"""User-entered care records. Dates are declarations, never treatment advice."""
from datetime import date
from uuid import uuid4
import re

MAX_RECORDS = 500
CATEGORIES = frozenset({'consultation', 'vaccination', 'deworming', 'parasite_control',
                        'treatment', 'observation', 'other'})
_ID = re.compile(r'[0-9a-f]{32}')


def _day(value, today=None):
    if not isinstance(value, str):
        raise ValueError('Expected an ISO date')
    day = date.fromisoformat(value)
    if day.isoformat() != value or (today is not None and day > today):
        raise ValueError('Invalid or future event date')
    return value


def _text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('Invalid record text')
    value = value.strip()
    if required and not value:
        raise ValueError('Record title is required')
    return value


def _record(row, pets, today=None):
    if not isinstance(row, dict) or not {'pet_id', 'date', 'category', 'title'} <= row.keys() or set(row) - {'pet_id', 'date', 'category', 'title', 'notes', 'due_date', 'completed'}:
        raise ValueError('Invalid care record fields')
    if not isinstance(row['pet_id'], str) or row['pet_id'] not in pets:
        raise ValueError('Unknown pet ID')
    day = _day(row['date'], today)
    category = row['category']
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError('Unknown care category')
    due = row.get('due_date')
    if due is not None:
        due = _day(due)
        if due < day:
            raise ValueError('Follow-up date cannot precede event date')
    completed = row.get('completed', False)
    if type(completed) is not bool or (completed and due is None):
        raise ValueError('Completion requires a follow-up date')
    return dict(pet_id=row['pet_id'], date=day, category=category,
                title=_text(row['title'], 100, True), notes=_text(row.get('notes', ''), 500),
                due_date=due, completed=completed)


def load_records(rows, pets):
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise ValueError('Invalid care record history')
    result = []
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('record_id'), str) or not _ID.fullmatch(row['record_id']) or row['record_id'] in ids:
            raise ValueError('Invalid or duplicate care record ID')
        key = row['record_id']
        record = _record({k: v for k, v in row.items() if k != 'record_id'}, pets)
        ids.add(key)
        result.append(dict(record_id=key, **record))
    return sorted(result, key=lambda r: (r['date'], r['record_id']))


def record_care(rows, pets, record, today, record_id=None, replace_existing=False):
    if type(replace_existing) is not bool:
        raise ValueError('Invalid replacement flag')
    candidate = _record(record, pets, today)
    if record_id is not None:
        if not isinstance(record_id, str) or not _ID.fullmatch(record_id):
            raise ValueError('Invalid care record ID')
        old = next((r for r in rows if r['record_id'] == record_id), None)
        if old is None or old['pet_id'] != candidate['pet_id']:
            raise ValueError('Unknown record for this pet')
        if old == dict(record_id=record_id, **candidate):
            return rows
        if not replace_existing:
            raise ValueError('Explicit replacement required')
        result = [r for r in rows if r['record_id'] != record_id]
    else:
        if replace_existing:
            raise ValueError('Select an existing record to replace')
        if any({k:v for k,v in r.items() if k != 'record_id'} == candidate for r in rows):
            return rows
        if len(rows) >= MAX_RECORDS:
            raise ValueError('Care record limit reached; nothing deleted')
        record_id = uuid4().hex
        result = list(rows)
    result.append(dict(record_id=record_id, **candidate))
    return sorted(result, key=lambda r: (r['date'], r['record_id']))
