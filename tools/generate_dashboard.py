#!/usr/bin/env python3
"""Generate native Lovelace configuration from a local HA entity registry.

Read JSON from stdin; output only the card/dashboard, never registry contents.
No network, writes, or third-party packages.
"""
import argparse
import json
import re
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
OPTIONAL = {
    'sensor': ('battery', 'meals_today', 'meals_yesterday', 'portions_today', 'portions_yesterday'),
    'binary_sensor': ('battery_present', 'child_lock', 'camera_enabled', 'manual_enabled'),
    'camera': ('camera_snapshot',),
}


def find_entities(registry, device=None):
    grouped = {}
    for row in registry['data']['entities']:
        if row.get('platform') != DOMAIN or row.get('disabled_by') is not None:
            continue
        eid = row.get('entity_id', '')
        uid = row.get('unique_id', '')
        if not isinstance(eid, str) or not re.fullmatch(r'[a-z0-9_]+\.[a-z0-9_]+', eid):
            continue
        platform = eid.split('.', 1)[0]
        if not isinstance(uid, str):
            continue
        for key in GROUPS.get(platform, ()) + OPTIONAL.get(platform, ()):
            if uid.endswith('_' + key):
                group = row.get('device_id') or row.get('config_entry_id')
                if group:
                    grouped.setdefault(group, {})[key] = eid
                break
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
        raise ValueError('Missing or disabled entities: ' + ', '.join(missing) + '. Check the integration version and enabled entities.')
    return entities


# Labels belong to the generated view only; registry names and IDs are unchanged.
LABELS = {
    'bowl_weight': ('Dans le bol', 'In the bowl'),
    'intake_today': ('Mangé ce jour', 'Eaten today'),
    'intake_yesterday': ('Mangé hier', 'Eaten yesterday'),
    'estimated_distributed': ('Distribué (est.)', 'Dispensed (est.)'),
    'next_meal': ('Prochain repas', 'Next meal'),
    'next_meal_portions': ('Portions du prochain repas', 'Next meal portions'),
    'remaining_portions': ('Portions autonomes restantes', 'Remaining scheduled portions'),
    'simulation': ('Mode simulation', 'Simulation mode'),
    'target': ('Objectif journalier', 'Daily target'),
    'forecast': ('Prévision', 'Forecast'),
    'budget': ('Budget restant', 'Extra budget'),
    'suggested_portions': ('Complément simulé (portions)', 'Simulated extra portions'),
    'decision': ('Décision simulée', 'Simulated decision'),
    'calibration_enabled': ('Calibration passive', 'Passive calibration'),
    'configured_weight': ('Poids nominal par portion', 'Nominal portion weight'),
    'calibration_weight': ('Poids / portion', 'Portion weight'),
    'measured_weight': ('Poids médian calibré par portion', 'Calibrated median portion weight'),
    'calibration_samples': ('Mesures valides', 'Valid samples'),
    'online': ('Connexion', 'Connection'),
    'status_text': ('Distributeur', 'Feeder'),
    'has_warning': ('Alerte active', 'Active warning'),
    'has_fault': ('Défaut actif', 'Active fault'),
    'desiccant_days': ('Dessiccant restant', 'Desiccant remaining life'),
    'manual_state': ('Complément manuel', 'Manual supplement'),
    'manual_pending': ('Commande à vérifier', 'Command needs verification'),
    'manual_result': ('Dernière commande', 'Last command'),
    'battery': ('Batterie', 'Battery'),
    'battery_present': ('Piles présentes', 'Batteries present'),
    'child_lock': ('Verrouillage enfant', 'Child lock'),
    'camera_enabled': ('Caméra activée', 'Camera enabled'),
    'manual_enabled': ('Option manuelle', 'Manual option'),
    'meals_today': ('Prises alimentaires aujourd’hui', 'Eating events today'),
    'meals_yesterday': ('Prises alimentaires hier', 'Eating events yesterday'),
    'portions_today': ('Portions distribuées aujourd’hui', 'Portions dispensed today'),
    'portions_yesterday': ('Portions distribuées hier', 'Portions dispensed yesterday'),
    'camera_snapshot': ('Ouvrir la caméra', 'Open camera'),
}


def _markdown(content, entities):
    return {'type': 'markdown', 'content': content, 'entity_id': entities}


def distribution_progress(e, lang):
    """Live estimate only; never use missing values as zero or cap the number."""
    fr = lang == 'fr'
    title = 'Distribution du jour (est.)' if fr else 'Today’s dispensing (est.)'
    missing = 'Données indisponibles' if fr else 'Data unavailable'
    distributed, target = e['estimated_distributed'], e['target']
    content = "\n".join([
        "{% set d = states('" + distributed + "') %}",
        "{% set t = states('" + target + "') %}",
        "{% set du = state_attr('" + distributed + "', 'unit_of_measurement') %}",
        "{% set tu = state_attr('" + target + "', 'unit_of_measurement') %}",
        f'**{title}**',
        "{% if is_number(d) and is_number(t) and d|float >= 0 and t|float > 0 and du and du == tu %}",
        "{% set percent = (100 * (d|float) / (t|float)) %}",
        "{% set filled = [[(percent / 10)|int, 0]|max, 10]|min %}",
        "### {{ '%g'|format(d|float) }} / {{ '%g'|format(t|float) }} {{ du }}",
        "{{ '▰' * filled }}{{ '▱' * (10 - filled) }} **{{ percent|round(0)|int }} %**",
        "{% else %}", missing, "{% endif %}",
    ])
    return _markdown(content, [distributed, target])


def next_meal_card(e, lang):
    """Show the actual HA-local date/time and a countdown, without guessing."""
    fr = lang == 'fr'
    meal, portions = e['next_meal'], e['next_meal_portions']
    title = 'Prochain repas programmé' if fr else 'Next scheduled meal'
    date_format = '%d/%m %H:%M' if fr else '%Y-%m-%d %H:%M'
    unavailable = 'Programme indisponible' if fr else 'Schedule unavailable'
    overdue = 'Horaire dépassé — à vérifier' if fr else 'Scheduled time passed — check feeder'
    countdown = "Dans {{ minutes // 60 }} h {{ '%02d'|format(minutes % 60) }} min" if fr else "In {{ minutes // 60 }} h {{ '%02d'|format(minutes % 60) }} min"
    shortly = 'Dans {{ minutes }} min' if fr else 'In {{ minutes }} min'
    portions_unknown = 'Quantité indisponible' if fr else 'Portions unavailable'
    content = "\n".join([
        "{% set meal = as_datetime(states('" + meal + "'), default=none) %}",
        "{% set portions = states('" + portions + "') %}",
        '<ha-icon icon="mdi:calendar-clock"></ha-icon> **' + title + '**',
        "{% if meal is not none %}",
        "{% set local = as_local(meal) %}",
        "{% set seconds = as_timestamp(meal) - as_timestamp(now()) %}",
        "### {{ local.strftime('" + date_format + "') }}",
        "{% if seconds >= 0 %}",
        "{% set minutes = ((seconds + 59) // 60)|int %}",
        "{% if minutes >= 60 %}" + countdown + "{% else %}" + shortly + "{% endif %}",
        "{% else %}" + overdue + "{% endif %}",
        "{% if is_number(portions) and portions|float > 0 and portions|float == portions|int %}",
        " · **{{ portions|int }} portion{% if portions|int != 1 %}s{% endif %}**",
        "{% else %} · " + portions_unknown + "{% endif %}",
        "{% else %}", unavailable, "{% endif %}",
    ])
    # No entity_id restriction here: now() must also refresh the countdown.
    return {'type': 'markdown', 'content': content}


def health_card(e, lang):
    """Unknown/disconnected data must never be reported as healthy."""
    fr = lang == 'fr'
    online, warning, fault = (e[key] for key in ('online', 'has_warning', 'has_fault'))
    def message(icon, french, english):
        return f'<ha-icon icon="mdi:{icon}"></ha-icon> **{french if fr else english}**'
    content = "\n".join([
        "{% set online = states('" + online + "') %}",
        "{% set warning = states('" + warning + "') %}",
        "{% set fault = states('" + fault + "') %}",
        "{% if online == 'off' %}", message('wifi-off', 'Hors ligne', 'Offline'),
        "{% elif online != 'on' %}", message('help-circle-outline', 'État indisponible', 'Status unavailable'),
        "{% elif fault == 'on' %}", message('alert-octagon', 'Défaut actif', 'Active fault'),
        "{% elif warning == 'on' %}", message('alert', 'Alerte active', 'Active warning'),
        "{% elif fault == 'off' and warning == 'off' %}", message('shield-check-outline', 'En ligne · aucune alerte ni défaut', 'Online · no warning or fault'),
        "{% else %}", message('help-circle-outline', 'État à vérifier', 'Status needs checking'),
        "{% endif %}",
    ])
    return _markdown(content, [online, warning, fault])


def _groups(e, lang):
    """Return reusable sections without write actions or automatic camera requests."""
    fr = lang == 'fr'
    def tr(french, english):
        return french if fr else english
    def name(key):
        return LABELS[key][0 if fr else 1]
    def tile(key):
        # Do not override the integration's state-based icons or theme colors.
        card = {'type': 'tile', 'entity': e[key], 'name': name(key),
                'tap_action': {'action': 'more-info'}, 'icon_tap_action': {'action': 'more-info'}}
        if key == 'camera_snapshot':
            card['show_entity_picture'] = False
            card['hide_state'] = True
            card['icon'] = 'mdi:cctv'
        return card
    def grid(keys):
        return {'type': 'grid', 'columns': 2, 'square': False,
                'cards': [tile(key) for key in keys if key in e]}
    def rows(keys):
        return {'type': 'entities', 'show_header_toggle': False,
                'entities': [{'entity': e[key], 'name': name(key)} for key in keys if key in e]}
    def history(title, hours, keys):
        return {'type': 'history-graph', 'title': title, 'hours_to_show': hours,
                'entities': [{'entity': e[key], 'name': name(key)} for key in keys]}
    feeder = []
    if 'camera_snapshot' in e:
        feeder.append(tile('camera_snapshot'))
    feeder += [health_card(e, lang), grid(('online', 'status_text', 'has_warning', 'has_fault')),
               rows(('desiccant_days', 'battery_present', 'battery', 'child_lock', 'camera_enabled'))]
    return [
        (tr('Alimentation', 'Feeding'), 'mdi:bowl-mix-outline', [
            grid(('bowl_weight', 'intake_today', 'estimated_distributed', 'intake_yesterday')),
            next_meal_card(e, lang), distribution_progress(e, lang),
            rows(('remaining_portions', 'meals_today', 'portions_today')),
        ]),
        (tr('Distributeur', 'Feeder'), 'mdi:cctv' if 'camera_snapshot' in e else 'mdi:shield-check-outline', feeder),
        (tr('Régulation hybride — simulation', 'Hybrid regulation — simulation'), 'mdi:flask-outline', [
            {'type': 'markdown', 'content': tr('**Simulation uniquement.** Objectif de distribution totale, pas de consommation individuelle.', '**Simulation only.** Total dispensing target, not individual intake.')},
            grid(('simulation', 'target', 'forecast', 'budget')),
            rows(('suggested_portions', 'decision')),
            {'type': 'markdown', 'content': tr('### Calibration passive', '### Passive calibration'), 'text_only': True},
            grid(('calibration_weight', 'calibration_samples')),
            rows(('calibration_enabled', 'configured_weight', 'measured_weight')),
        ]),
        (tr('Historique', 'History'), 'mdi:chart-line', [
            history(tr('Poids du bol · 24 h', 'Bowl weight · 24 h'), 24, ('bowl_weight',)),
            history(tr('Croquettes · 48 h', 'Kibble · 48 h'), 48, ('intake_today', 'estimated_distributed')),
        ]),
        (tr('Complément manuel', 'Manual supplement'), 'mdi:shield-check-outline', [
            rows(('manual_enabled', 'manual_state', 'manual_pending', 'manual_result')),
        ]),
    ]


def make_card(e, lang='fr'):
    """Keep the legacy single-card entry point and output type."""
    cards = [{'type': 'markdown', 'content': '## MOVA NutriPal'}]
    for title, _, contents in _groups(e, lang):
        cards.append({'type': 'markdown', 'content': '### ' + title})
        cards.extend(contents)
    return {'type': 'vertical-stack', 'cards': cards}


def make_dashboard(e, lang='fr', title='MOVA NutriPal'):
    """Three balanced sections, then two graphs and manual status."""
    sections = []
    for heading, icon, cards in _groups(e, lang):
        history = bool(cards) and all(card['type'] == 'history-graph' for card in cards)
        section = {'type': 'grid', 'cards': [
            {'type': 'heading', 'heading': heading, 'icon': icon},
            *[dict(card, grid_options={'columns': 12 if history else 'full'}) for card in cards],
        ]}
        if history:
            # Native section grid: 12 columns per section; on a narrow screen
            # the two full-width graphs stack instead of shrinking their axes.
            section['column_span'] = 2
        sections.append(section)
    return {'title': title, 'views': [{
        'title': 'Alimentation' if lang == 'fr' else 'Feeding',
        'path': 'feeding', 'icon': 'mdi:paw', 'type': 'sections',
        'max_columns': 3, 'sections': sections,
    }]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('fr', 'en'), default='fr')
    parser.add_argument('--device', help='HA device registry ID (only required for multiple feeders)')
    parser.add_argument('--format', choices=('card', 'dashboard'), default='card', help='Single manual card or complete Sections dashboard')
    parser.add_argument('--title', default='MOVA NutriPal', help='Title of a complete dashboard')
    args = parser.parse_args()
    try:
        entities = find_entities(json.load(sys.stdin), args.device)
        config = make_dashboard(entities, args.language, args.title) if args.format == 'dashboard' else make_card(entities, args.language)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f'Cannot generate dashboard: {exc}\n')
    # JSON is valid YAML 1.2; no third-party YAML dependency required.
    print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
