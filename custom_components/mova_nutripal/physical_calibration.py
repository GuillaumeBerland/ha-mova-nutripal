"""Independent physical weighing series; never changes the configured reference."""
from datetime import date
from math import isfinite
from decimal import Decimal, ROUND_HALF_UP

MAX_SERIES = 10
MAX_TRIALS = 30


def build_series(day, trials, confirmed):
    if confirmed is not True:
        raise ValueError('Confirm independent net weighings without food consumption')
    if type(day) is not date:
        raise ValueError('Invalid weighing date')
    if not isinstance(trials, list) or not 3 <= len(trials) <= MAX_TRIALS:
        raise ValueError('Enter 3 to 30 independent weighings')
    clean = []
    for trial in trials:
        if not isinstance(trial, dict) or set(trial) != {'portions', 'grams'}:
            raise ValueError('Each weighing requires portions and grams')
        n, g = trial['portions'], trial['grams']
        if type(n) not in (int, float) or not 1 <= n <= 100 or not isfinite(n) or n != int(n):
            raise ValueError('Portions must be a whole number from 1 to 100')
        if type(g) not in (int, float) or not 2*n <= g <= 20*n or not isfinite(g):
            raise ValueError('Each net weighing must be between 2 and 20 g per portion')
        clean.append({'portions': int(n), 'grams': float(g)})
    portions = sum(t['portions'] for t in clean)
    grams = sum(Decimal(str(t['grams'])) for t in clean)
    average = grams / portions
    return {'date': day.isoformat(), 'trials': clean, 'total_portions': portions,
            'total_grams': float(grams), 'weighted_mean': float(average.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
            'suggested_reference': float(average.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))}


def valid_series(record):
    try:
        return record == build_series(date.fromisoformat(record['date']), record['trials'], True)
    except (ValueError, KeyError, TypeError, ArithmeticError, OverflowError):
        return False


def append_series(records, record):
    if not valid_series(record) or record in records:
        return False
    records.append(record)
    del records[:-MAX_SERIES]
    return True


def summary(records, reference):
    latest = records[-1] if records else None
    return {'physical_reference': latest['suggested_reference'] if latest else None,
            'physical_series': records,
            'reference_matches_series': bool(latest and reference == latest['suggested_reference'])}
