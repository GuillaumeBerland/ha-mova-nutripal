"""Local pet profiles and dated weights, isolated from feeding and cloud data."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from math import isfinite
from pathlib import Path
import json
import re

from .state_store import save_state
from .food_profiles import load_periods, record_period, describe_period
from .veterinary_records import load_records, record_care

MAX_PETS = 20
MAX_WEIGHTS = 1000
_ID = re.compile(r'[a-z0-9][a-z0-9_]{0,31}')


def _pet_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Invalid pet ID (use 1-32 lowercase letters, digits or underscores)')
    return value


def _date(value, today=None):
    if type(value) is date:
        value = value.isoformat()
    if not isinstance(value, str):
        raise ValueError('Expected an ISO date')
    day = date.fromisoformat(value)
    if day.isoformat() != value or (today is not None and day > today):
        raise ValueError('Invalid or future date')
    return value


def _grams(value, minimum=1, maximum=30000):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError('Expected finite weight in kg')
    grams = Decimal(str(value)) * 1000
    if grams != grams.to_integral_value() or not minimum <= grams <= maximum:
        raise ValueError('Invalid weight (maximum three decimal places in kg)')
    return int(grams)


def _integer_grams(value, minimum=1, maximum=30000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid stored weight')
    return value


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 64 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid pet name')
    return value.strip()


def _profile_color(value):
    if not isinstance(value, str) or (value and not re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
        raise ValueError('Use a color in #RRGGBB format or an empty string')
    return value.lower()


def _profile_photo(value):
    if not isinstance(value, str) or (value and (len(value) > 200 or not re.fullmatch(
            r'/local/pets/[a-zA-Z0-9_-]+\.(?i:jpg|jpeg|png|webp)', value))):
        raise ValueError('Use a local photo under /local/pets/ (jpg, jpeg, png or webp)')
    return value


def _measurement(row, today):
    if not isinstance(row, dict) or not {'date', 'source'} <= row.keys():
        raise ValueError('Each measurement requires a date and source')
    day = _date(row['date'], today)
    source = row['source']
    if source not in ('home', 'veterinarian', 'other'):
        raise ValueError('Invalid measurement source')
    keys = set(row) - {'date', 'source'}
    if keys == {'weight_kg'}:
        return dict(date=day, source=source, method='direct', grams=_grams(row['weight_kg']))
    if keys == {'gross_kg', 'cage_kg'}:
        gross = _grams(row['gross_kg'], maximum=60000)
        cage = _grams(row['cage_kg'])
        net = _integer_grams(gross - cage)
        return dict(date=day, source=source, method='cage', grams=net, gross_grams=gross, cage_grams=cage)
    raise ValueError('Provide either weight_kg or both gross_kg and cage_kg')


def _validate_stored_row(row):
    if not isinstance(row, dict):
        raise ValueError('Invalid stored measurement')
    day = _date(row['date'])
    source = row['source']
    if source not in ('home', 'veterinarian', 'other'):
        raise ValueError('Invalid stored source')
    net = _integer_grams(row['grams'])
    if row['method'] == 'direct' and set(row) == {'date', 'source', 'method', 'grams'}:
        return dict(date=day, source=source, method='direct', grams=net)
    if row['method'] == 'cage' and set(row) == {'date', 'source', 'method', 'grams', 'gross_grams', 'cage_grams'}:
        gross = _integer_grams(row['gross_grams'], maximum=60000)
        cage = _integer_grams(row['cage_grams'])
        if gross - cage == net:
            return dict(date=day, source=source, method='cage', grams=net, gross_grams=gross, cage_grams=cage)
    raise ValueError('Invalid stored measurement method or net weight')


class PetHealth:
    """Pure model: callers save a candidate before publishing it to entities."""
    def __init__(self, state=None):
        self.pets = {}
        self.food_periods = []
        self.care_records = []
        if state is None:
            return
        if not isinstance(state, dict) or not {'pets'} <= state.keys() or set(state) - {'pets', 'food_periods', 'care_records'} or not isinstance(state['pets'], dict) or len(state['pets']) > MAX_PETS:
            raise ValueError('Invalid pet health state')
        self.food_periods = load_periods(state.get('food_periods', []))
        for key, profile in state['pets'].items():
            _pet_id(key)
            required = {'name', 'target_grams', 'baseline_date', 'measurements'}
            if not isinstance(profile, dict) or not required <= profile.keys() or set(profile) - required - {'color', 'photo_url'}:
                raise ValueError('Invalid pet profile')
            target = profile['target_grams']
            baseline = profile['baseline_date']
            rows = profile['measurements']
            if not isinstance(rows, list) or len(rows) > MAX_WEIGHTS:
                raise ValueError('Invalid measurement history')
            rows = [_validate_stored_row(row) for row in rows]
            if len({row['date'] for row in rows}) != len(rows):
                raise ValueError('Duplicate stored measurement date')
            self.pets[key] = dict(name=_name(profile['name']),
                target_grams=None if target is None else _integer_grams(target),
                baseline_date=None if baseline is None else _date(baseline),
                measurements=sorted(rows, key=lambda row: row['date']))
            for field, validate in (('color', _profile_color), ('photo_url', _profile_photo)):
                if field in profile:
                    value = validate(profile[field])
                    if value:
                        self.pets[key][field] = value

        self.care_records = load_records(state.get('care_records', []), self.pets)

    def record_care(self, *, record, today, record_id=None, replace_existing=False):
        self.care_records = record_care(self.care_records, self.pets, record, today, record_id, replace_existing)

    def export(self):
        return {'pets': deepcopy(self.pets), 'food_periods': deepcopy(self.food_periods), 'care_records': deepcopy(self.care_records)}

    def record_food_period(self, *, period, today, replace_existing=False):
        self.food_periods = record_period(self.food_periods, period, today, replace_existing)

    def food_summary(self, today):
        history = [describe_period(row) for row in self.food_periods if row['start_date'] <= today.isoformat()]
        return {'current': history[-1] if history else None, 'history': history, 'used_for_feeding': False}

    def save_profile(self, *, pet_id, name, today, target_kg=None, baseline_date=None,
                     color=None, photo_url=None):
        key = _pet_id(pet_id)
        old = self.pets.get(key)
        if old is None and len(self.pets) >= MAX_PETS:
            raise ValueError('Pet profile limit reached')
        # Omitted optional fields preserve the existing values on update.
        target = (old['target_grams'] if old else None) if target_kg is None else _grams(target_kg)
        baseline = (old['baseline_date'] if old else None) if baseline_date is None else _date(baseline_date, today)
        profile = dict(name=_name(name), target_grams=target, baseline_date=baseline,
                       measurements=deepcopy(old['measurements']) if old else [])
        # Omission preserves the setting; an explicit empty string clears it.
        for field, value, validate in (('color', color, _profile_color),
                                       ('photo_url', photo_url, _profile_photo)):
            value = (old or {}).get(field, '') if value is None else validate(value)
            if value:
                profile[field] = value
        self.pets[key] = profile

    def record_weights(self, *, pet_id, measurements, today, replace_existing=False):
        key = _pet_id(pet_id)
        if key not in self.pets:
            raise ValueError('Unknown pet ID')
        if type(replace_existing) is not bool or not isinstance(measurements, list) or not 1 <= len(measurements) <= MAX_WEIGHTS:
            raise ValueError('Invalid measurement batch')
        incoming = [_measurement(row, today) for row in measurements]
        if len({row['date'] for row in incoming}) != len(incoming):
            raise ValueError('Duplicate date within measurement batch')
        rows = {row['date']: row for row in self.pets[key]['measurements']}
        for row in incoming:
            old = rows.get(row['date'])
            if old is not None and old != row and not replace_existing:
                raise ValueError('Measurement already exists on this date; explicit replacement required')
            rows[row['date']] = row
        if len(rows) > MAX_WEIGHTS:
            raise ValueError('Measurement limit reached; no existing measurement deleted')
        self.pets[key]['measurements'] = sorted(rows.values(), key=lambda row: row['date'])

    def summary(self, pet_id):
        p = self.pets[pet_id]
        rows = p['measurements']
        latest = rows[-1] if rows else None
        baseline = (next((r for r in rows if r['date'] == p['baseline_date']), None)
                    if p['baseline_date'] else (rows[0] if rows else None))
        if latest and baseline and latest['date'] < baseline['date']:
            baseline = None
        target = p['target_grams']
        delta = latest['grams'] - baseline['grams'] if latest and baseline else None
        return dict(pet_id=pet_id, name=p['name'], target_kg=target/1000 if target is not None else None,
            color=p.get('color'), photo_url=p.get('photo_url'),
            baseline_date=baseline['date'] if baseline else p['baseline_date'],
            baseline_kg=baseline['grams']/1000 if baseline else None,
            latest_date=latest['date'] if latest else None,
            weight_kg=latest['grams']/1000 if latest else None,
            latest_source=latest['source'] if latest else None,
            change_grams=delta, change_percent=round(100*delta/baseline['grams'], 2) if delta is not None else None,
            difference_to_target_grams=latest['grams']-target if latest and target is not None else None,
            measurement_count=len(rows))


def load_health(path):
    try:
        with Path(path).open(encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return PetHealth()
    if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1:
        raise ValueError('Unsupported pet health storage version')
    return PetHealth(raw['state'])


def save_health(path, health):
    save_state(path, health.export())
