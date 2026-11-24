#!/usr/bin/env python3
"""Generate one native Lovelace card from a local HA entity registry.

Read JSON from stdin; never print registry contents or identifiers other than
entity IDs needed by the card. No network, writes, or third-party packages.
"""
import argparse
import json
import sys

DOMAIN = 'mova_nutripal'
GROUPS = {
    'sensor': ('bowl_weight', 'intake_today', 'intake_yesterday', 'status_text',
               'next_meal', 'next_meal_portions', 'estimated_distributed',
               'forecast', 'target', 'remaining_portions', 'budget', 'decision',
               'suggested_portions', 'calibration_weight', 'measured_weight',
               'calibration_samples', 'configured_weight', 'desiccant_days',
               'manual_state', 'manual_result'),
    'binary_sensor': ('online', 'has_warning', 'has_fault', 'simulation',
                      'manual_pending', 'calibration_enabled'),
}


def find_entities(registry, device=None):
    grouped = {}
    for row in registry['data']['entities']:
        if row.get('platform') != DOMAIN or row.get('disabled_by') is not None:
            continue
        eid = row.get('entity_id', '')
        uid = row.get('unique_id', '')
        platform = eid.split('.', 1)[0]
        if not isinstance(uid, str):
            continue
        for key in GROUPS.get(platform, ()):
            if uid.endswith('_' + key):
                group = row.get('device_id') or row.get('config_entry_id')
                if group:
                    grouped.setdefault(group, {})[key] = eid
    if device is not None:
        if device not in grouped:
            raise ValueError('Requested device not found')
        entities = grouped[device]
    elif len(grouped) != 1:
        raise ValueError('Expected one MOVA feeder; use --device DEVICE_ID for multiple feeders')
    else:
        entities = next(iter(grouped.values()))
    missing = sorted(set(k for keys in GROUPS.values() for k in keys) - entities.keys())
    if missing:
        raise ValueError('Missing or disabled entities: ' + ', '.join(missing) + '. Install 0.2.2 and restart HA first.')
    return entities


def make_card(e, lang='fr'):
    fr = lang == 'fr'
    def tile(key, name, icon):
        return {'type': 'tile', 'entity': e[key], 'name': name, 'icon': icon,
                'tap_action': {'action': 'more-info'}, 'icon_tap_action': {'action': 'more-info'}}
    def rows(title, values):
        return {'type': 'entities', 'title': title, 'show_header_toggle': False,
                'entities': [{'entity': e[key], 'name': label} for key, label in values]}
    return {'type': 'vertical-stack', 'cards': [
        {'type': 'markdown', 'content': ('## 🐾 MOVA NutriPal\nSuivi des croquettes • **Simulation uniquement**' if fr else '## 🐾 MOVA NutriPal\nKibble monitoring • **Simulation only**')},
        {'type': 'grid', 'columns': 2, 'square': False, 'cards': [
            tile('bowl_weight', 'Dans le bol' if fr else 'In the bowl', 'mdi:bowl-mix-outline'),
            tile('intake_today', 'Mangé aujourd’hui' if fr else 'Eaten today', 'mdi:cat'),
            tile('estimated_distributed', 'Distribué (estim.)' if fr else 'Dispensed (est.)', 'mdi:scale'),
            tile('intake_yesterday', 'Mangé hier' if fr else 'Eaten yesterday', 'mdi:history'),
        ]},
        rows('Prochain repas' if fr else 'Next meal', [
            ('next_meal', 'Repas programmé' if fr else 'Scheduled meal'),
            ('next_meal_portions', 'Nombre de portions' if fr else 'Portions'),
            ('remaining_portions', 'Portions restantes aujourd’hui' if fr else 'Remaining scheduled portions today'),
        ]),
        rows('Régulation hybride — simulation' if fr else 'Hybrid regulation — simulation', [
            ('simulation', 'Simulation'), ('target', 'Objectif de distribution' if fr else 'Distribution target'),
            ('forecast', 'Distribution prévue' if fr else 'Forecast distribution'),
            ('budget', 'Budget supplémentaire' if fr else 'Extra budget'),
            ('suggested_portions', 'Portions proposées' if fr else 'Suggested portions'),
            ('decision', 'Décision' if fr else 'Decision'),
        ]),
        rows('Calibration passive' if fr else 'Passive calibration', [
            ('calibration_enabled', 'Calibration'),
            ('configured_weight', 'Poids nominal MOVA' if fr else 'MOVA nominal weight'),
            ('calibration_weight', 'Poids utilisé' if fr else 'Effective weight'),
            ('measured_weight', 'Poids médian mesuré' if fr else 'Measured median weight'),
            ('calibration_samples', 'Mesures valides' if fr else 'Valid samples'),
        ]),
        {'type': 'history-graph', 'title': 'Poids dans le bol — 24 h' if fr else 'Bowl weight — 24 h',
         'hours_to_show': 24, 'entities': [e['bowl_weight']]},
        rows('État et entretien' if fr else 'Status and maintenance', [
            ('online', 'Connexion' if fr else 'Connection'),
            ('status_text', 'Distributeur' if fr else 'Feeder'),
            ('has_warning', 'Alerte' if fr else 'Warning'), ('has_fault', 'Défaut' if fr else 'Fault'),
            ('desiccant_days', 'Dessiccant' if fr else 'Desiccant'),
            ('manual_state', 'Complément manuel' if fr else 'Manual supplement'),
            ('manual_pending', 'Commande à vérifier' if fr else 'Command needs verification'),
            ('manual_result', 'Dernière commande' if fr else 'Last command'),
        ]),
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('fr', 'en'), default='fr')
    parser.add_argument('--device', help='HA device registry ID (only required for multiple feeders)')
    args = parser.parse_args()
    try:
        card = make_card(find_entities(json.load(sys.stdin), args.device), args.language)
    except (ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Cannot generate dashboard: {exc}\n')
    # JSON is valid YAML 1.2, and can be pasted into the HA manual card editor.
    print(json.dumps(card, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
