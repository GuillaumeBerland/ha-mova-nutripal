"""Dated, shared feeder diets. Descriptive only; never an input to feeding."""
from copy import deepcopy
from decimal import Decimal
from math import isfinite

MAX_FOOD_PERIODS = 365
MAX_COMPONENTS = 10


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid food name')
    return value.strip()


def _number(value, low, high):
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid food quantity')
    n = Decimal(str(value))
    if n != n.quantize(Decimal('0.01')):
        raise ValueError('Food quantities allow at most two decimal places')
    return float(n)


def validate_period(row, today=None):
    from .pet_health import _date
    if not isinstance(row, dict) or not {'start_date', 'name', 'components'} <= row.keys() or set(row) - {'start_date', 'name', 'components', 'ration_g', 'portion_g'}:
        raise ValueError('Invalid food period fields')
    components = row['components']
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError('Provide one to ten foods')
    clean = []
    for c in components:
        if not isinstance(c, dict) or not {'name', 'percent'} <= c.keys() or set(c) - {'name', 'percent', 'kcal_per_100g'}:
            raise ValueError('Invalid food component')
        energy = c.get('kcal_per_100g')
        clean.append(dict(name=_text(c['name']), percent=_number(c['percent'], .01, 100),
                          kcal_per_100g=None if energy is None else _number(energy, .01, 900)))
    if sum(Decimal(str(c['percent'])) for c in clean) != 100:
        raise ValueError('Food percentages by weight must total 100')
    if len({c['name'].casefold() for c in clean}) != len(clean):
        raise ValueError('Duplicate food component')
    ration, portion = row.get('ration_g'), row.get('portion_g')
    return dict(start_date=_date(row['start_date'], today), name=_text(row['name']), components=clean,
                ration_g=None if ration is None else _number(ration, .01, 10000),
                portion_g=None if portion is None else _number(portion, .01, 100))


def load_periods(rows):
    if not isinstance(rows, list) or len(rows) > MAX_FOOD_PERIODS:
        raise ValueError('Invalid food history')
    result = [validate_period(r) for r in rows]
    if len({r['start_date'] for r in result}) != len(result):
        raise ValueError('Duplicate food period date')
    return sorted(result, key=lambda r: r['start_date'])


def record_period(rows, period, today, replace_existing=False):
    if type(replace_existing) is not bool:
        raise ValueError('Invalid replacement confirmation')
    row = validate_period(period, today)
    by_date = {r['start_date']: r for r in rows}
    previous = by_date.get(row['start_date'])
    if previous is not None and previous != row and not replace_existing:
        raise ValueError('Food period already exists on this date; explicit replacement required')
    by_date[row['start_date']] = row
    return load_periods(list(by_date.values()))


def describe_period(row):
    """No calorie estimate unless every component has a declared energy value."""
    r = deepcopy(row)
    energy = None
    if all(c['kcal_per_100g'] is not None for c in r['components']):
        energy = sum(Decimal(str(c['percent'])) * Decimal(str(c['kcal_per_100g'])) / 100 for c in r['components'])
    r['kcal_per_100g'] = round(float(energy), 2) if energy is not None else None
    r['ration_kcal'] = round(float(energy * Decimal(str(r['ration_g'])) / 100), 2) if energy is not None and r['ration_g'] is not None else None
    return r
