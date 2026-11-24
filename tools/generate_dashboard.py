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
    'calendar': ('meal_calendar',),
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
    'intake_today': ('Mangé aujourd’hui', 'Eaten today'),
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
    """Show actual estimate and reserved scheduled estimate, not intake."""
    fr = lang == 'fr'
    d, f, t, mode = (e[key] for key in ('estimated_distributed', 'forecast', 'target', 'simulation'))
    def tr(french, english):
        return french if fr else english
    content = "\n".join([
        "{% set d = states('" + d + "') | float(none) %}",
        "{% set f = states('" + f + "') | float(none) %}",
        "{% set t = states('" + t + "') | float(none) %}",
        "{% set du = state_attr('" + d + "', 'unit_of_measurement') %}",
        "{% set fu = state_attr('" + f + "', 'unit_of_measurement') %}",
        "{% set tu = state_attr('" + t + "', 'unit_of_measurement') %}",
        "{% if is_state('" + mode + "', 'on') %}",
        tr('**Simulation uniquement** · Distribution totale', '**Simulation only** · Total dispensing'),
        "{% else %}", tr('⚠️ **Mode simulation non confirmé**', '⚠️ **Simulation mode not confirmed**'), "{% endif %}",
        "{% if is_number(d) and is_number(t) and d >= 0 and t > 0 and du and du == tu %}",
        "\n## {{ '%g'|format(d|round(1)) }} / {{ '%g'|format(t|round(1)) }} {{ du }}\n",
        "{% set blue = [[(10 * d / t)|int, 0]|max, 10]|min %}",
        "{% if is_number(f) and f >= d and fu == du %}",
        "{% set filled = [[(10 * f / t)|int, blue]|max, 10]|min %}",
        "{{ '🟦' * blue }}{{ '🟧' * (filled - blue) }}{{ '⬜' * (10 - filled) }}\n",
        tr('🟦 Déjà distribué (est.) :', '🟦 Already dispensed (est.):') + " **{{ '%g'|format(d|round(1)) }} {{ du }}**\n",
        tr('🟧 Repas restants (est.) :', '🟧 Remaining meals (est.):') + " **{{ '%g'|format((f - d)|round(1)) }} {{ du }}**\n",
        tr('Prévision :', 'Forecast:') + " **{{ '%g'|format(f|round(1)) }} {{ du }} ({{ (100 * f / t)|round(0)|int }} %)**\n",
        "{% if f > t %}", tr('⚠️ Objectif dépassé en prévision de **{{ (f - t)|round(1) }} {{ du }}**.', '⚠️ Forecast exceeds target by **{{ (f - t)|round(1) }} {{ du }}**.'),
        "{% elif f < t %}", tr('Écart restant à l’objectif : **{{ (t - f)|round(1) }} {{ du }}**.', 'Remaining gap to target: **{{ (t - f)|round(1) }} {{ du }}**.'),
        "{% else %}", tr('Objectif atteint en prévision.', 'Forecast meets target.'), "{% endif %}",
        "{% else %}", "{{ '🟦' * blue }}{{ '⬜' * (10 - blue) }}\n", tr('Prévision indisponible.', 'Forecast unavailable.'), "{% endif %}",
        "{% else %}", tr('Données indisponibles ou incohérentes.', 'Data unavailable or inconsistent.'), "{% endif %}",
    ])
    return dict(_markdown(content, [d, f, t, mode]), title=tr('Distribution journalière', 'Daily dispensing'))


def next_meal_card(e, lang):
    """Scheduled time and estimated grams, with no invented missing values."""
    fr = lang == 'fr'
    meal, portions, weight = (e[key] for key in ('next_meal', 'next_meal_portions', 'calibration_weight'))
    def tr(french, english):
        return french if fr else english
    date_format = '%d/%m %H:%M' if fr else '%Y-%m-%d %H:%M'
    content = "\n".join([
        "{% set meal = as_datetime(states('" + meal + "'), default=none) %}",
        "{% set portions = states('" + portions + "') | float(none) %}",
        "{% set weight = states('" + weight + "') | float(none) %}",
        "{% set unit = state_attr('" + weight + "', 'unit_of_measurement') %}",
        "{% if meal is not none %}",
        "{% set local = as_local(meal) %}",
        "{% set seconds = as_timestamp(meal) - as_timestamp(now()) %}",
        "## 🕒 {{ local.strftime('" + date_format + "') }}\n",
        "{% if seconds >= 0 %}",
        "{% set minutes = ((seconds + 59) // 60)|int %}",
        "{% if minutes >= 60 %}" + tr("Dans {{ minutes // 60 }} h {{ '%02d'|format(minutes % 60) }} min", "In {{ minutes // 60 }} h {{ '%02d'|format(minutes % 60) }} min") + "{% else %}" + tr('Dans {{ minutes }} min', 'In {{ minutes }} min') + "{% endif %}\n",
        "{% else %}", tr('⚠️ Horaire dépassé — à vérifier', '⚠️ Scheduled time passed — check feeder'), "{% endif %}",
        "{% if is_number(portions) and portions > 0 and portions == portions|int %}",
        "**{{ portions|int }} portion{% if portions|int != 1 %}s{% endif %}**{% if is_number(weight) and weight > 0 and unit == 'g' %} · **{{ '%g'|format((portions * weight)|round(1)) }} g** " + tr('estimés', 'estimated') + "{% endif %}",
        "{% else %}", tr('Quantité indisponible', 'Portions unavailable'), "{% endif %}",
        "{% else %}", tr('Programme indisponible', 'Schedule unavailable'), "{% endif %}",
    ])
    # now() must refresh the countdown; do not restrict updates to entities.
    return {'type': 'markdown', 'title': tr('Prochain repas', 'Next meal'), 'content': content}


def calibration_card(e, lang):
    """Initial three-sample threshold; never imply calibration if disabled."""
    fr = lang == 'fr'
    samples, enabled, measured = (e[key] for key in ('calibration_samples', 'calibration_enabled', 'measured_weight'))
    def tr(french, english):
        return french if fr else english
    content = "\n".join([
        "{% set n = states('" + samples + "') | int(none) %}",
        "{% set enabled = states('" + enabled + "') %}",
        "{% set measured = states('" + measured + "') | float(none) %}",
        "{% if enabled == 'off' %}", tr('**Calibration désactivée**', '**Calibration disabled**'),
        "{% elif enabled != 'on' %}", tr('État de calibration indisponible.', 'Calibration status unavailable.'),
        "{% elif n is none or n < 0 %}", tr('Nombre de mesures indisponible.', 'Sample count unavailable.'),
        "{% elif n < 3 %}",
        tr('## {{ n }} / 3 mesures initiales', '## {{ n }} / 3 initial samples') + "\n",
        "{{ '🟪' * n }}{{ '⬜' * (3 - n) }}\n",
        tr('Poids de référence utilisé en attendant trois mesures valides.', 'Reference weight used until three valid samples.'),
        "{% elif is_number(measured) and measured > 0 %}",
        tr('## {{ n }} mesures valides', '## {{ n }} valid samples') + "\n",
        tr('🟪🟪🟪 · Minimum initial atteint', '🟪🟪🟪 · Initial minimum reached') + "\n",
        tr('Médiane mesurée :', 'Measured median:') + " **{{ '%g'|format(measured|round(2)) }} g**",
        "{% else %}", tr('Minimum initial atteint · médiane indisponible.', 'Initial minimum reached · median unavailable.'), "{% endif %}",
    ])
    return dict(_markdown(content, [samples, enabled, measured]), title=tr('Calibration passive', 'Passive calibration'))


def health_card(e, lang):
    """Unknown/disconnected data must never be reported as healthy."""
    fr = lang == 'fr'
    online, warning, fault, pending = (e[key] for key in ('online', 'has_warning', 'has_fault', 'manual_pending'))
    def message(symbol, french, english):
        return f'{symbol} **{french if fr else english}**'
    content = "\n".join([
        "{% set online = states('" + online + "') %}",
        "{% set warning = states('" + warning + "') %}",
        "{% set fault = states('" + fault + "') %}",
        "{% set pending = states('" + pending + "') %}",
        "{% if pending == 'on' %}", message('🔴', 'Commande à vérifier', 'Command needs verification'),
        "{% elif fault == 'on' %}", message('🔴', 'Défaut actif', 'Active fault'),
        "{% elif online == 'off' %}", message('🟠', 'Hors ligne', 'Offline'),
        "{% elif warning == 'on' %}", message('🟠', 'Alerte active', 'Active warning'),
        "{% elif online == 'on' and fault == 'off' and warning == 'off' and pending == 'off' %}", message('🟢', 'En ligne — aucune alerte ni défaut', 'Online — no warning or fault'),
        "{% else %}", message('⚪', 'État à vérifier', 'Status needs checking'),
        "{% endif %}",
    ])
    return dict(_markdown(content, [online, warning, fault, pending]), title='État du distributeur' if fr else 'Feeder status')


def _groups(e, lang):
    """Three thematic columns, with visual summaries and read-only details."""
    fr = lang == 'fr'
    def tr(french, english):
        return french if fr else english
    def name(key):
        return LABELS[key][0 if fr else 1]
    def tile(key):
        card = {'type': 'tile', 'entity': e[key], 'name': name(key),
                'tap_action': {'action': 'more-info'}, 'icon_tap_action': {'action': 'more-info'}}
        if key == 'camera_snapshot':
            card.update(show_entity_picture=False, hide_state=True, icon='mdi:cctv')
        return card
    def grid(keys):
        return {'type': 'grid', 'columns': 2, 'square': False,
                'cards': [tile(key) for key in keys if key in e]}
    def rows(keys, title=None):
        card = {'type': 'entities', 'show_header_toggle': False,
                'entities': [{'entity': e[key], 'name': name(key)} for key in keys if key in e]}
        if title:
            card['title'] = title
        return card
    def history(title, hours, keys):
        return {'type': 'history-graph', 'title': title, 'hours_to_show': hours,
                'entities': [{'entity': e[key], 'name': name(key)} for key in keys]}
    feeding = [grid(('bowl_weight', 'intake_today', 'estimated_distributed', 'intake_yesterday')),
               next_meal_card(e, lang),
               rows(('remaining_portions', 'meals_today', 'portions_today')),
               history(tr('Poids du bol · 24 h', 'Bowl weight · 24 h'), 24, ('bowl_weight',))]
    if 'camera_snapshot' in e:
        feeding.append(tile('camera_snapshot'))
    return [
        (tr('Alimentation', 'Feeding'), 'mdi:paw', feeding),
        (tr('Régulation hybride', 'Hybrid regulation'), 'mdi:chart-donut', [
            distribution_progress(e, lang),
            rows(('simulation', 'budget', 'suggested_portions', 'decision'), tr('Complément simulé', 'Simulated supplement')),
            history(tr('Croquettes · 48 h', 'Kibble · 48 h'), 48, ('intake_today', 'estimated_distributed')),
        ]),
        (tr('Calibration et entretien', 'Calibration and maintenance'), 'mdi:cog-outline', [
            calibration_card(e, lang),
            rows(('calibration_enabled', 'configured_weight', 'calibration_weight', 'measured_weight')),
            health_card(e, lang),
            rows(('online', 'status_text', 'has_warning', 'has_fault', 'desiccant_days', 'battery_present', 'battery', 'child_lock', 'camera_enabled')),
            rows(('manual_enabled', 'manual_state', 'manual_pending', 'manual_result'), tr('Complément manuel', 'Manual supplement')),
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
    """Keep the three thematic sections in order on narrow screens."""
    sections = [{'type': 'grid', 'cards': [
        {'type': 'heading', 'heading': heading, 'icon': icon, 'heading_style': 'title'},
        *[dict(card, grid_options={'columns': 'full'}) for card in cards],
    ]} for heading, icon, cards in _groups(e, lang)]
    views = [{
        'title': 'Alimentation' if lang == 'fr' else 'Feeding',
        'path': 'feeding', 'icon': 'mdi:paw', 'type': 'sections',
        'max_columns': 3, 'dense_section_placement': False, 'sections': sections,
    }]
    if 'meal_calendar' in e:
        views.append({
            'title': 'Repas programmés' if lang == 'fr' else 'Scheduled meals',
            'path': 'meals', 'icon': 'mdi:calendar-clock', 'type': 'panel',
            'cards': [{'type': 'calendar', 'entities': [e['meal_calendar']],
                       'initial_view': 'listWeek'}],
        })
    return {'title': title, 'views': views}


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
