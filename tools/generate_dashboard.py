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
    'sensor': ('battery', 'meals_today', 'meals_yesterday', 'portions_today', 'portions_yesterday',
               'daily_reconstructed', 'daily_corrected_forecast', 'daily_quality', 'daily_history_count',
               'daily_difference', 'daily_portion_weight', 'compensated_samples', 'compensated_weight', 'physical_reference',
               'scheduled_daily_portions', 'scheduled_daily_weight'),
    'binary_sensor': ('battery_present', 'child_lock', 'camera_enabled', 'manual_enabled'),
    'camera': ('camera_snapshot',),
    'calendar': ('meal_calendar',),
    'number': ('reference_setting', 'target_setting'),
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
        for key in sorted(GROUPS.get(platform, ()) + OPTIONAL.get(platform, ()) + (('pet_health',) if platform == 'sensor' else ()), key=len, reverse=True):
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
    'intake_today': ('Consommation MOVA', 'MOVA intake'),
    'intake_yesterday': ('Consommation MOVA hier', 'MOVA intake yesterday'),
    'estimated_distributed': ('Distribué théor. (brut)', 'Raw theoretical dispensing'),
    'next_meal': ('Prochain repas', 'Next meal'),
    'next_meal_portions': ('Portions du prochain repas', 'Next meal portions'),
    'remaining_portions': ('Portions autonomes restantes', 'Remaining scheduled portions'),
    'simulation': ('Mode simulation', 'Simulation mode'),
    'target': ('Objectif journalier', 'Daily target'),
    'forecast': ('Prévision', 'Forecast'),
    'budget': ('Budget restant', 'Extra budget'),
    'suggested_portions': ('Complément simulé (portions)', 'Simulated extra portions'),
    'decision': ('Décision simulée', 'Simulated decision'),
    'calibration_enabled': ('Collecte automatique (diagnostic)', 'Automatic collection (diagnostic)'),
    'configured_weight': ('Poids nominal par portion', 'Nominal portion weight'),
    'calibration_weight': ('Référence utilisée / portion', 'Configured reference / portion'),
    'physical_reference': ('Référence proposée (pesées)', 'Suggested physical reference'),
    'measured_weight': ('Poids médian calibré par portion', 'Calibrated median portion weight'),
    'calibration_samples': ('Mesures classiques (diag.)', 'Classic samples (diag.)'),
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
    'daily_reconstructed': ('Distribué reconst. (est.)', 'Reconstructed (est.)'),
    'daily_difference': ('Écart reconst. / théorique', 'Reconstructed / theoretical difference'),
    'daily_portion_weight': ('Poids moyen reconst. / portion', 'Reconstructed mean / portion'),
    'daily_quality': ('Qualité du bilan', 'Balance quality'),
    'scheduled_daily_weight': ('Programme total (est.)', 'Total program (est.)'),
    'scheduled_daily_portions': ('Portions programmées', 'Scheduled portions'),
    'compensated_samples': ('Mesures compensées (exp.)', 'Compensated samples (exp.)'),
    'compensated_weight': ('Médiane compensée (exp.)', 'Compensated median (exp.)'),
    'camera_snapshot': ('Ouvrir la caméra', 'Open camera'),
    'reference_setting': ('Poids de référence par portion', 'Reference weight per portion'),
    'target_setting': ('Objectif journalier', 'Daily target'),
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


def daily_balance_card(e, lang):
    """Promote reconstructed mass; keep the theoretical planner explicitly separate."""
    fr = lang == 'fr'
    def tr(a, b): return a if fr else b
    keys = ('daily_reconstructed', 'daily_corrected_forecast', 'daily_quality', 'estimated_distributed',
            'forecast', 'target', 'intake_today', 'bowl_weight', 'calibration_weight', 'simulation')
    ids = [e[k] for k in keys]
    r, c, q, d, f, t, eaten, bowl, w, mode = ids
    lines = ["{% set " + var + " = states('" + eid + "') | float(none) %}" for var,eid in
             zip(('r','c','d','f','t','eaten','bowl','w'),(r,c,d,f,t,eaten,bowl,w))]
    if 'scheduled_daily_weight' in e and 'scheduled_daily_portions' in e:
        sw, sp = e['scheduled_daily_weight'], e['scheduled_daily_portions']
        ids += [sw, sp]
        lines += ["{% set planned = states('"+sw+"')|float(none) %}",
                  "{% set portions = states('"+sp+"')|int(none) %}"]
    else:
        lines += ["{% set planned = none %}", "{% set portions = none %}"]
    lines += ["{% set q = states('"+q+"') %}",
              "{% if is_state('"+mode+"', 'on') %}", tr('**Simulation uniquement**', '**Simulation only**'),
              "{% else %}", tr('⚠️ Mode simulation non confirmé', '⚠️ Simulation mode not confirmed'), "{% endif %}",
              "{% if q == 'excluded' %}", tr('⚠️ **Journée non représentative** — essais ou manipulation signalés. Les compteurs MOVA restent bruts.', '⚠️ **Non-representative day** — trials or handling flagged. MOVA counters remain raw.'), "{% endif %}\n",
              tr('**Consommation déclarée par MOVA :**', '**Intake reported by MOVA:**')+" {% if is_number(eaten) %}{{ '%g'|format(eaten) }} g{% else %}—{% endif %}\n",
              tr('**Dans le bol :**', '**In the bowl:**')+" {% if is_number(bowl) %}{{ '%g'|format(bowl) }} g{% else %}—{% endif %}\n",
              "{% if q == 'reconstructed' and is_number(r) and r >= 0 and is_number(t) and t > 0 %}",
              "## {{ '%g'|format(r) }} / {{ '%g'|format(t) }} g\n",
              tr('Distribution reconstituée (non certifiée)', 'Reconstructed dispensing (not certified)'),
              "{% set green = [[(10*r/t)|int,0]|max,10]|min %}",
              "{% set total = [[(10*c/t)|int,green]|max,10]|min if is_number(c) and c >= r else green %}",
              "{{ '🟩'*green }}{{ '🟧'*(total-green) }}{{ '⬜'*(10-total) }}\n",
              tr('🟩 Reconstitué :', '🟩 Reconstructed:')+" **{{ '%g'|format(r) }} g**\n",
              "{% if is_number(c) and c >= r %}",
              tr('🟧 Repas restants (est.) :', '🟧 Remaining meals (est.):')+" **{{ '%g'|format(c-r) }} g**\n",
              tr('Prévision corrigée indicative :', 'Indicative corrected forecast:')+" **{{ '%g'|format(c) }} g ({{ (100*c/t)|round(0)|int }} %)**\n",
              "{% endif %}", "{% if is_number(d) %}",
              tr('Écart reconstitué / théorique :', 'Reconstructed / theoretical difference:')+" **{{ '%+.1f'|format(r-d) }} g**",
              "{% endif %}", "{% else %}",
              "{% if is_number(planned) and planned >= 0 and is_number(t) and t > 0 %}",
              tr('**Programme quotidien normal (estimé)**', '**Normal daily program (estimated)**'),
              "## {{ '%g'|format(planned) }} / {{ '%g'|format(t) }} g\n",
              "{% set blue = [[(10*planned/t)|int,0]|max,10]|min %}",
              "{{ '🟦'*blue }}{{ '⬜'*(10-blue) }}\n",
              tr('Programme :', 'Program:')+" {{ portions if portions is not none else '—' }} " + tr('portions · hors essais et distributions supplémentaires.', 'portions · excluding trials and extra dispensing.'),
              tr('Couverture de l’objectif :', 'Target coverage:')+" **{{ (100*planned/t)|round(1) }} %**\n",
              "{% elif q != 'excluded' and is_number(d) and d >= 0 and is_number(t) and t > 0 %}",
              tr('**Distribution théorique**', '**Theoretical dispensing**'),
              "## {{ '%g'|format(d) }} / {{ '%g'|format(t) }} g\n",
              "{% set blue = [[(10*d/t)|int,0]|max,10]|min %}",
              "{% set total = [[(10*f/t)|int,blue]|max,10]|min if is_number(f) and f >= d else blue %}",
              "{{ '🟦'*blue }}{{ '🟧'*(total-blue) }}{{ '⬜'*(10-total) }}\n",
              tr('🟦 Déjà distribué (est.) · 🟧 Repas restants (est.)', '🟦 Already dispensed (est.) · 🟧 Remaining meals (est.)'),
              "{% endif %}",
              tr('**Distribution reconstituée indisponible**', '**Reconstructed dispensing unavailable**'),
              "{% if q == 'missing_boundary' %}", tr('Poids du bol à minuit non établi. Pas de mesure complète.', 'Midnight bowl weight not established. No full-day measurement.'),
              "{% elif q == 'excluded' %}", tr('Journée exclue des bilans représentatifs.', 'Day excluded from representative balances.'),
              "{% elif q == 'inconsistent' %}", tr('Données incohérentes : bilan non calculé.', 'Inconsistent data: balance not calculated.'),
              "{% elif q == 'storage_error' %}", tr('Historique local indisponible.', 'Local history unavailable.'),
              "{% else %}", tr('En attente de données cohérentes.', 'Waiting for consistent data.'), "{% endif %}", "{% endif %}\n",
              "{% if q == 'reconstructed' and is_number(planned) and planned >= 0 %}",
              tr('Programme quotidien normal :', 'Normal daily program:')+" **{{ '%g'|format(planned) }} g** ({{ portions if portions is not none else '—' }} "+tr('portions', 'portions')+")\n", "{% endif %}",
              tr('**Calcul théorique de la régulation (compteurs bruts)**', '**Theoretical regulation calculation (raw counters)**')+'\n',
              tr('Référence configurée :', 'Configured reference:')+" {% if is_number(w) %}{{ '%g'|format(w) }} g/portion{% else %}—{% endif %}\n",
              tr('Distribué (est.) :', 'Dispensed (est.):')+" {% if is_number(d) %}{{ '%g'|format(d) }} g{% else %}—{% endif %}\n",
              tr('Prévision théorique :', 'Theoretical forecast:')+" {% if is_number(f) %}{{ '%g'|format(f) }} g{% else %}—{% endif %}\n",
              "{% if q != 'excluded' and is_number(f) and is_number(t) and f > t %}",
              tr('Dépassement **théorique** :', '**Theoretical** excess:')+" {{ '%g'|format(f-t) }} g",
              "{% endif %}\n", tr('Le bilan reconstitué ne pilote pas la distribution.', 'Reconstructed balance does not control dispensing.')]
    return dict(_markdown('\n'.join(lines), ids), title=tr('Bilan alimentaire journalier', 'Daily feeding balance'))


def daily_history_card(e, lang):
    fr = lang == 'fr'
    def tr(a,b): return a if fr else b
    hist = e['daily_history_count']
    quality = e['daily_quality']
    lines = ["{% set rows = state_attr('"+hist+"', 'days') or [] %}",
             "{% set q = states('"+quality+"') %}",
             "{% if q == 'storage_error' %}", tr('⚠️ Stockage indisponible.', '⚠️ Storage unavailable.'), "{% endif %}",
             tr('**Hier — données MOVA brutes :**', '**Yesterday — raw MOVA data:**'),
             "{% if state_attr('"+hist+"', 'yesterday_excluded') == true %}",
             tr('⚠️ Journée non représentative.', '⚠️ Non-representative day.'), "{% endif %}",
             tr('Consommation déclarée :', 'Reported intake:')+" {% set y = states('"+e['intake_yesterday']+"')|float(none) %}{% if is_number(y) %}{{ '%g'|format(y) }} g{% else %}—{% endif %}",
             "{% if rows %}",
             tr('| Date | Reconst. g | Théor. g | MOVA g | Écart g | Portions | État |', '| Date | Recon. g | Theor. g | MOVA g | Diff. g | Portions | Status |'),
             '|---|---:|---:|---:|---:|---:|---|',
             "{% for row in rows|reverse -%}",
             "| {{ row.day }} | {% for k in ['reconstructed','theoretical','consumed','difference','portions'] %}{{ '%g'|format(row[k]) if is_number(row[k]) else '—' }} | {% endfor %}{% if row.excluded_reason is defined and row.excluded_reason %}"+tr('Non représentatif','Non-representative')+"{% elif row.quality == 'reconstructed' %}"+tr('Reconstitué','Reconstructed')+"{% elif row.quality == 'inconsistent' %}"+tr('Incohérent','Inconsistent')+"{% else %}"+tr('Incomplet','Incomplete')+"{% endif %} |",
             "{% endfor %}", "{% else %}", tr('Aucun bilan archivé. Le premier bilan complet exige deux limites de journée observées.', 'No archived balances. The first complete balance requires two observed day boundaries.'), "{% endif %}\n",
             tr('Théorique = portions × poids de référence à la dernière lecture du jour. Les données absentes restent inconnues (—). Les bilans reconstitués supposent aucun ajout/retrait de croquettes non comptabilisé.', 'Theoretical = portions × reference weight at the final reading of the day. Missing values stay unknown (—). Reconstructed balances assume no unrecorded food additions/removals.')]
    entities = [hist, quality, e['intake_yesterday']]
    if 'portions_yesterday' in e:
        portions = e['portions_yesterday']
        entities.append(portions)
        lines.insert(lines.index("{% if rows %}"), tr('Portions distribuées :', 'Portions dispensed:') + " {% set p = states('"+portions+"')|int(none) %}{{ p if p is not none else '—' }}")
    return dict(_markdown('\n'.join(lines), entities), title=tr('Historique alimentaire · 30 jours', 'Feeding history · 30 days'))


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
        tr('Mesures de diagnostic uniquement. La référence configurée reste utilisée.', 'Diagnostic measurements only. The configured reference remains in use.'),
        "{% elif is_number(measured) and measured > 0 %}",
        tr('## {{ n }} mesures valides', '## {{ n }} valid samples') + "\n",
        tr('🟪🟪🟪 · Minimum initial atteint', '🟪🟪🟪 · Initial minimum reached') + "\n",
        tr('Médiane de diagnostic :', 'Diagnostic median:') + " **{{ '%g'|format(measured|round(2)) }} g**",
        "{% else %}", tr('Minimum initial atteint · médiane indisponible.', 'Initial minimum reached · median unavailable.'), "{% endif %}",
    ])
    return dict(_markdown(content, [samples, enabled, measured]), title=tr('Calibration · diagnostic', 'Calibration · diagnostics'))


def physical_card(e, lang):
    """Show actual saved series and configured value, without implying automatic application."""
    fr = lang == 'fr'
    def tr(a,b): return a if fr else b
    physical, used = e['physical_reference'], e['calibration_weight']
    lines = ["{% set series = state_attr('"+physical+"', 'series') or [] %}",
             "{% set used = states('"+used+"')|float(none) %}",
             "{% set proposed = states('"+physical+"')|float(none) %}",
             "{% if is_number(used) %}", "## 🔒 {{ '%g'|format(used) }} g / "+tr('portion','portion')+"\n",
             tr('**Référence configurée utilisée**', '**Configured reference in use**'), "{% else %}",
             tr('Référence configurée indisponible.', 'Configured reference unavailable.'), "{% endif %}\n",
             "{% if series and is_number(proposed) %}", "{% set latest = series[-1] %}",
             "{% if is_number(used) and used == proposed %}",
             tr('🟢 La référence correspond aux dernières pesées.', '🟢 Reference matches latest weighings.'), "{% else %}",
             tr('🟠 Référence proposée :', '🟠 Suggested reference:')+" **{{ '%g'|format(proposed) }} g** · "+tr('application manuelle.', 'manual application.'), "{% endif %}\n",
             "**{{ latest.trials|length }}** "+tr('pesées', 'weighings')+" · **{{ latest.total_portions }}** "+tr('portions', 'portions')+" · **{{ '%g'|format(latest.total_grams) }} g**\n",
             tr('Série du', 'Series dated')+" {{ latest.date }}", "{% else %}",
             tr('Aucune série de pesées disponible.', 'No physical weighing series available.'), "{% endif %}\n",
             tr('Les diagnostics ne changent jamais cette référence.', 'Diagnostics never change this reference.')]
    return dict(_markdown('\n'.join(lines), [physical, used]), title=tr('Calibration physique','Physical calibration'))


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
    has_daily = all(k in e for k in ('daily_reconstructed', 'daily_corrected_forecast', 'daily_quality'))
    feeding = [grid(('bowl_weight', 'intake_today', 'scheduled_daily_weight' if 'scheduled_daily_weight' in e else 'daily_reconstructed' if has_daily else 'estimated_distributed', 'intake_yesterday')),
               next_meal_card(e, lang),
               rows(('remaining_portions', 'meals_today', 'portions_today')),
               history(tr('Poids du bol · 24 h', 'Bowl weight · 24 h'), 24, ('bowl_weight',))]
    if 'camera_snapshot' in e:
        feeding.append(tile('camera_snapshot'))
    return [
        (tr('Alimentation', 'Feeding'), 'mdi:paw', feeding),
        (tr('Régulation hybride', 'Hybrid regulation'), 'mdi:chart-donut', [
            daily_balance_card(e, lang) if has_daily else distribution_progress(e, lang),
            rows(('simulation', 'budget', 'suggested_portions', 'decision'), tr('Complément simulé', 'Simulated supplement')),
            history(tr('Compteurs bruts · 48 h', 'Raw counters · 48 h'), 48, ('intake_today', 'estimated_distributed')),
        ]),
        (tr('Calibration et entretien', 'Calibration and maintenance'), 'mdi:cog-outline', [
            physical_card(e, lang) if 'physical_reference' in e else calibration_card(e, lang),
            rows(('configured_weight', 'calibration_enabled', 'calibration_samples', 'measured_weight', 'compensated_samples', 'compensated_weight'), tr('Diagnostics de calibration','Calibration diagnostics')),
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


def overview_card(e, lang):
    """Show schedule progress separately from raw or reconstructed dispensing."""
    def tr(a, b): return a if lang == 'fr' else b
    ids = []
    lines = []
    for var, key in (('t','target'), ('p','scheduled_daily_weight'), ('sp','scheduled_daily_portions'),
                     ('rem','remaining_portions'), ('w','calibration_weight'), ('proposed','physical_reference'),
                     ('d','estimated_distributed'), ('r','daily_reconstructed'), ('c','daily_corrected_forecast')):
        if key in e:
            ids.append(e[key]); lines.append("{% set "+var+" = states('"+e[key]+"')|float(none) %}")
        else:
            lines.append("{% set "+var+" = none %}")
    for var, key in (('q','daily_quality'), ('mode','simulation'), ('decision','decision'), ('online','online')):
        if key in e:
            ids.append(e[key]); lines.append("{% set "+var+" = states('"+e[key]+"') %}")
        else:
            lines.append("{% set "+var+" = none %}")
    lines += ["{% if q == 'excluded' %}",
              tr('⚠️ **Journée non représentative** — essais ou manipulations signalés. Le programme reste visible ; les compteurs bruts ne représentent pas les repas normaux.', '⚠️ **Non-representative day** — trials or handling flagged. The program remains visible; raw counters do not represent normal meals.'), "{% endif %}",
              "{% if mode != 'on' %}", tr('⚠️ Mode simulation non confirmé.', '⚠️ Simulation mode not confirmed.'), "{% endif %}",
              "{% set valid_program = is_number(p) and p >= 0 and is_number(sp) and sp >= 0 and sp == sp|int and is_number(w) and w > 0 and (p-sp*w)|abs <= 0.02 %}",
              "{% set valid_progress = valid_program and online == 'on' and decision in ['device_not_ready','budget_reached','meal_soon','bowl_not_empty','would_feed'] and is_number(rem) and 0 <= rem <= sp and rem == rem|int %}",
              "{% if valid_program %}",
              "{% if valid_progress %}",
              "{% set done = ((sp-rem)*w)|round(2) %}{% set left = (rem*w)|round(2) %}",
              tr('**Repas programmés signalés terminés (est.)**', '**Scheduled meals reported complete (est.)**'),
              "## {{ '%g'|format(done) }} g{% if is_number(t) and t > 0 %} / {{ '%g'|format(t) }} g{% endif %}\n",
              "{% if is_number(t) and t > 0 %}",
              "{% set filled = [[(10*done/t)|int,0]|max,10]|min %}",
              "{% set total = [[(10*p/t)|int,filled]|max,10]|min %}",
              "{{ '🟦'*filled }}{{ '🟧'*(total-filled) }}{{ '⬜'*(10-total) }}\n", "{% endif %}",
              tr('🟦 Terminés (est.) :', '🟦 Complete (est.):')+" **{{ '%g'|format(done) }} g** · {{ (sp-rem)|int }} "+tr('portions','portions')+"\n",
              tr('🟧 À distribuer (est.) :', '🟧 Remaining (est.):')+" **{{ '%g'|format(left) }} g** · {{ rem|int }} "+tr('portions','portions')+"\n",
              "{% else %}", tr('Progression du programme indisponible — repas terminés non confirmés.', 'Program progress unavailable — completed meals not confirmed.'), "{% endif %}\n",
              tr('**Programme total (inclut les repas restants) :**', '**Total program (includes remaining meals):**')+" **{{ '%g'|format(p) }} g** · {{ sp|int }} "+tr('portions','portions')+"\n",
              "{% if is_number(t) and t > 0 %}",
              tr('Objectif couvert par le programme :', 'Target covered by program:')+" {{ (100*p/t)|round(1) }} %\n",
              "{% if p > t %}", tr('⚠️ Programme au-dessus de l’objectif de', '⚠️ Program exceeds target by')+" {{ '%g'|format((p-t)|round(2)) }} g.", "{% endif %}", "{% endif %}",
              "{% else %}", tr('Programme quotidien indisponible.', 'Daily program unavailable.'), "{% endif %}\n",
              "{% if is_number(w) and w > 0 %}", tr('Référence utilisée :', 'Reference in use:')+" **{{ '%g'|format(w) }} g/portion**\n",
              "{% if is_number(proposed) and proposed > 0 and (w-proposed)|abs > 0.001 %}",
              tr('⚠️ Pesées :', '⚠️ Physical trials:')+" **{{ '%g'|format(proposed) }} g/portion** — "+tr('réglage à appliquer dans l’intégration.', 'apply the setting in the integration.'), "{% endif %}{% endif %}\n",
              "{% if q == 'reconstructed' and is_number(r) and r >= 0 %}",
              tr('Distribution reconstituée (est., toutes distributions) :', 'Reconstructed dispensing (est., all dispensing):')+" **{{ '%g'|format(r) }} g**\n",
              "{% if is_number(c) and c >= r %}", tr('Prévision reconstituée indicative :', 'Indicative reconstructed forecast:')+" **{{ '%g'|format(c) }} g**\n", "{% endif %}",
              "{% elif q != 'excluded' and is_number(d) and d >= 0 %}",
              tr('Distribution totale théorique (est., toutes distributions) :', 'Total theoretical dispensing (est., all dispensing):')+" **{{ '%g'|format(d) }} g**\n",
              tr('Bilan reconstitué indisponible.', 'Reconstructed balance unavailable.'), "{% endif %}\n",
              "{% if mode == 'on' %}", tr('Simulation uniquement · aucun complément automatique.', 'Simulation only · no automatic supplement.'), "{% endif %}"]
    return dict(_markdown('\n'.join(lines), ids), title=tr('Alimentation du jour','Today’s feeding'))


def consumption_card(e, lang):
    """Keep raw consumption accessible in Technical; flag excluded days on Home."""
    def tr(a,b): return a if lang == 'fr' else b
    today, yesterday = e['intake_today'], e['intake_yesterday']
    ids = [today, yesterday]
    q, hist = e.get('daily_quality'), e.get('daily_history_count')
    lines = ["{% set today = states('"+today+"')|float(none) %}",
             "{% set yesterday = states('"+yesterday+"')|float(none) %}"]
    if q:
        ids.append(q)
        lines.append("{% set excluded = states('"+q+"') == 'excluded' %}")
    else:
        lines.append("{% set excluded = false %}")
    if hist:
        ids.append(hist)
        lines.append("{% set yesterday_excluded = state_attr('"+hist+"', 'yesterday_excluded') == true %}")
    else:
        lines.append("{% set yesterday_excluded = false %}")
    lines += [tr('**Aujourd’hui :**', '**Today:**')+" {% if excluded %}"+tr('⚠️ Non représentatif — voir Technique.', '⚠️ Non-representative — see Technical.')+"{% elif is_number(today) and today >= 0 %}**{{ '%g'|format(today) }} g**{% else %}—{% endif %}\n",
              tr('**Hier :**', '**Yesterday:**')+" {% if yesterday_excluded %}"+tr('⚠️ Non représentatif — voir Historique.', '⚠️ Non-representative — see History.')+"{% elif is_number(yesterday) and yesterday >= 0 %}**{{ '%g'|format(yesterday) }} g**{% else %}—{% endif %}\n",
              tr('Valeurs déclarées par MOVA, pas une pesée indépendante.', 'MOVA-reported values, not independent weighing.')]
    return dict(_markdown('\n'.join(lines), ids), title=tr('Consommation','Intake'))


def planning_card(e, lang):
    """Display only the already validated daily schedule, not historical events."""
    def tr(a,b): return a if lang == 'fr' else b
    remaining, weight, portions, planned = (e[k] for k in ('remaining_portions','calibration_weight','scheduled_daily_portions','scheduled_daily_weight'))
    lines = ["{% set slots = state_attr('"+remaining+"', 'schedule') or [] %}",
             "{% set w = states('"+weight+"')|float(none) %}",
             "{% set p = states('"+portions+"')|int(none) %}",
             "{% set g = states('"+planned+"')|float(none) %}",
             "{% if p is not none and p >= 0 and is_number(g) and is_number(w) and w > 0 %}",
             "{% set active = slots|selectattr('status','equalto',true)|list %}",
             "{% if active|sum(attribute='portions') == p %}",
             "| "+tr('Heure | Portions | Poids estimé','Time | Portions | Estimated weight')+" |", "|---|---:|---:|",
             "{% for row in active|sort(attribute='feedingTime') -%}",
             "| {{ row.feedingTime[:5] }} | {{ row.portions }} | {{ '%g'|format((row.portions*w)|round(1)) }} g |",
             "{% endfor %}", "{% endif %}\n",
             tr('**Total quotidien :**','**Daily total:**')+" {{ p }} "+tr('portions','portions')+" · **{{ '%g'|format(g) }} g**",
             "{% else %}", tr('Programme quotidien indisponible ou non pris en charge.', 'Daily program unavailable or unsupported.'), "{% endif %}",
             tr('Horaires programmés, pas une confirmation de distribution.', 'Scheduled times, not confirmation of dispensing.')]
    return dict(_markdown('\n'.join(lines), [remaining,weight,portions,planned]), title=tr('Programme alimentaire','Feeding program'))


def weekly_card(e, lang):
    """Seven most recent archived days; native Markdown, no extra recorder queries."""
    def tr(a,b): return a if lang == 'fr' else b
    hist = e['daily_history_count']
    lines = ["{% set rows = state_attr('"+hist+"', 'days') or [] %}",
             tr('🟩 Reconstitué · 🟦 Théorique · 🟪 Consommation MOVA', '🟩 Reconstructed · 🟦 Theoretical · 🟪 MOVA intake'),
             "{% for row in rows[-7:]|reverse %}", "**{{ row.day }}**\n",
             "{% if row.excluded_reason is defined and row.excluded_reason %}", tr('⚠️ Journée non représentative.', '⚠️ Non-representative day.'),
             "{% elif row.quality == 'reconstructed' and is_number(row.target) and row.target > 0 %}",
             "{% for key, color in [('reconstructed','🟩'),('theoretical','🟦'),('consumed','🟪')] %}",
             "{% if is_number(row[key]) and row[key] >= 0 %}",
             "{% set n = [[(10*row[key]/row.target)|int,0]|max,10]|min %}",
             "{{ color*n }}{{ '⬜'*(10-n) }} **{{ '%g'|format(row[key]) }} g**\n",
             "{% endif %}{% endfor %}",
             "{% else %}", tr('Bilan incomplet — voir le détail.', 'Incomplete balance — see details.'), "{% endif %}\n",
             "{% else %}", tr('Aucun bilan archivé.', 'No archived balances.'), "{% endfor %}",
             tr('Chaque barre représente l’objectif de la journée ; les valeurs restent affichées au-delà de 100 %.', 'Each bar represents the daily target; values above 100% remain visible.')]
    return dict(_markdown('\n'.join(lines), [hist]), title=tr('7 derniers bilans','Last 7 archived balances'))


def configuration_card(e, lang):
    """Native number controls; only the two explicit configuration settings are editable."""
    keys = ('reference_setting', 'target_setting')
    rows = [{'entity': e[k], 'name': LABELS[k][0 if lang == 'fr' else 1]} for k in keys if k in e]
    if not rows:
        return None
    return {'type': 'entities', 'title': 'Configuration alimentaire' if lang == 'fr' else 'Feeding settings',
            'show_header_toggle': False, 'entities': rows}


def midnight_card(e, lang):
    """Explain the last midnight decision without inventing unavailable observations."""
    if 'daily_quality' not in e:
        return None
    q = e['daily_quality']
    def tr(a,b): return a if lang == 'fr' else b
    reasons = {
        'non_adjacent_day': tr('Jours non consécutifs','Non-adjacent days'),
        'before_outside_window': tr('Dernier relevé avant minuit trop ancien','Pre-midnight reading too old'),
        'after_outside_window': tr('Premier relevé après minuit trop tardif','Post-midnight reading too late'),
        'yesterday_intake_mismatch': tr('Consommation de la veille non concordante','Yesterday intake mismatch'),
        'yesterday_portions_mismatch': tr('Portions de la veille non concordantes','Yesterday portion mismatch'),
        'today_counters_not_zero': tr('Compteurs du jour non remis à zéro','Today counters not reset'),
        'bowl_changed': tr('Poids du bol différent','Bowl weight changed'),
        'retry_window_or_observations_changed': tr('Délai ou mesures modifiés pendant la vérification','Retry window or readings changed'),
        'yesterday_counters_changed': tr('Compteurs de la veille supérieurs au dernier relevé','Yesterday counters exceed last reading'),
    }
    lines = ["{% set b = state_attr('"+q+"', 'midnight_boundary') or {} %}",
             "{% if b %}",
             "{% if b.status == 'confirmed' %}", tr('🟢 Limite de journée confirmée.', '🟢 Day boundary confirmed.'),
             "{% elif b.status == 'retry' %}", tr('🟠 Vérification des compteurs de la veille en cours.', '🟠 Checking delayed yesterday counters.'),
             "{% else %}", tr('⚠️ Limite de journée non validée.', '⚠️ Day boundary not validated.'), "{% endif %}",
             "{% for reason in b.reasons %}"]
    for i,(key,label) in enumerate(reasons.items()):
        lines.append(('{% if ' if i == 0 else '{% elif ') + "reason == '"+key+"' %}\n- "+label)
    lines += ["{% else %}\n- {{ reason }}{% endif %}", "{% endfor %}",
              tr('Avant :','Before:')+" {{ b.before.day }} {{ b.before.ts | timestamp_custom('%H:%M:%S', true) }} · {{ b.before.bowl }} g",
              tr('Après :','After:')+" {{ b.after.day }} {{ b.after.ts | timestamp_custom('%H:%M:%S', true) }} · {{ b.after.bowl }} g",
              "{% else %}", tr('Aucun diagnostic de minuit enregistré depuis cette mise à jour.', 'No midnight diagnostic recorded since this update.'), "{% endif %}"]
    return dict(_markdown('\n'.join(lines),[q]),title=tr('Diagnostic du passage à minuit','Midnight boundary diagnostics'))


def pet_health_card(e, lang, interactive=False):
    """Local health hub: no names, weights or animal IDs are copied into YAML."""
    hub = e['pet_health']
    if interactive:
        return {'type': 'custom:mova-pet-health-card', 'entity': hub, 'language': lang}
    def tr(a, b): return a if lang == 'fr' else b
    lines = ["{% set profiles = state_attr('"+hub+"', 'profiles') or [] %}",
             "{% if states('"+hub+"') in ['unknown','unavailable'] %}",
             tr('Suivi santé indisponible.', 'Pet health unavailable.'), "{% else %}",
             "{% for p in profiles %}", "## {{ p.name|e }}",
             tr('Dernière pesée :', 'Latest weight:')+" {% if is_number(p.weight_kg) %}**{{ '%.3f'|format(p.weight_kg) }} kg** · {{ p.latest_date }}{% else %}—{% endif %}",
             tr('Poids cible :', 'Target weight:')+" {% if is_number(p.target_kg) %}{{ '%g'|format(p.target_kg) }} kg{% else %}—{% endif %}",
             tr('Évolution depuis la référence :', 'Change since baseline:')+" {% if is_number(p.change_grams) %}{{ '%+g'|format(p.change_grams) }} g{% else %}—{% endif %}",
             tr('Pesées enregistrées :', 'Recorded measurements:')+" {{ p.measurement_count }}\n",
             "{% else %}", tr('Aucun profil. Crée un animal via les actions Home Assistant.', 'No profiles. Create a pet using Home Assistant actions.'),
             "{% endfor %}",
             "{% set food = state_attr('"+hub+"', 'food') or {} %}",
             "{% if food.current %}", "## "+tr('Alimentation déclarée','Declared food'), "**{{ food.current.name|e }}** · {{ food.current.start_date }}",
             "{% for c in food.current.components %}{{ c.name|e }} : {{ '%g'|format(c.percent) }} %\n{% endfor %}",
             tr('Ration cible déclarée :', 'Declared target ration:')+" {% if is_number(food.current.ration_g) %}{{ '%g'|format(food.current.ration_g) }} g/j{% else %}—{% endif %}",
             tr('Énergie estimée de la ration :', 'Estimated ration energy:')+" {% if is_number(food.current.ration_kcal) %}{{ '%g'|format(food.current.ration_kcal) }} kcal/j{% else %}—{% endif %}",
             "{% endif %}",
             "{% set care = state_attr('"+hub+"', 'care_records') or [] %}",
             "## "+tr('Carnet de santé','Care log'),
             tr('Événements enregistrés :','Recorded events:')+" {{ care|length }}",
             "{% endif %}",
             tr('Les actions de santé ne modifient pas la distribution.', 'Health actions do not change dispensing.')]
    return dict(_markdown('\n'.join(lines), [hub]), title=tr('Suivi du poids','Weight tracking'))


def make_dashboard(e, lang='fr', title='MOVA NutriPal', health_ui=False):
    """V5: everyday essentials first, optional planning/history, diagnostics last."""
    def tr(a,b): return a if lang == 'fr' else b
    def section(heading, icon, contents):
        return {'type':'grid', 'cards':[{'type':'heading','heading':heading,'icon':icon,'heading_style':'title'},
                 *[dict(card, grid_options={'columns':'full'}) for card in contents]]}
    def view(label,path,icon,sections,columns=2):
        return dict(title=label,path=path,icon=icon,type='sections',max_columns=columns,
                    dense_section_placement=False,sections=sections)
    feeding, regulation, maintenance = _groups(e,lang)
    feed, reg, tech = feeding[2], regulation[2], maintenance[2]
    # Keep only bowl and full program tiles. Consumption gets an exclusion-aware summary.
    tiles = dict(feed[0], cards=[c for c in feed[0]['cards']
                 if c['entity'] in (e['bowl_weight'], e.get('scheduled_daily_weight'))])
    essentials = [tiles, overview_card(e,lang), consumption_card(e,lang)]
    daily = [feed[1], *[c for c in feed if c.get('entity') == e.get('camera_snapshot') and c.get('entity')],
             tech[2], feed[3]]
    views = [view(tr('Accueil','Home'),'feeding','mdi:paw',[
        section(tr('Alimentation','Feeding'),'mdi:paw',essentials),
        section(tr('Prochain repas et caméra','Next meal and camera'),'mdi:calendar-clock',daily)])]
    planning = []
    if all(k in e for k in ('scheduled_daily_weight','scheduled_daily_portions')):
        planning.append(section(tr('Programme','Program'),'mdi:calendar-clock',[planning_card(e,lang)]))
    if 'meal_calendar' in e:
        planning.append(section(tr('Calendrier','Calendar'),'mdi:calendar',[{'type':'calendar','entities':[e['meal_calendar']],'initial_view':'listWeek'}]))
    if planning:
        views.append(view(tr('Planning','Schedule'),'meals','mdi:calendar-clock',planning,1))
    history = []
    if 'daily_history_count' in e and 'daily_quality' in e:
        history.append(section(tr('Bilans quotidiens','Daily balances'),'mdi:chart-bar',[weekly_card(e,lang),daily_history_card(e,lang)]))
    history.append(section(tr('Évolution des compteurs','Counter history'),'mdi:chart-line',[reg[2]]))
    views.append(view(tr('Historique','History'),'feeding-history','mdi:calendar-text',history,1))
    if 'pet_health' in e:
        if health_ui:
            views.append(dict(title=tr('Santé','Health'), path='pet-health', icon='mdi:heart-pulse',
                              type='panel', cards=[pet_health_card(e,lang,True)]))
        else:
            views.append(view(tr('Santé','Health'),'pet-health','mdi:heart-pulse',[
                section(tr('Suivi des animaux','Pet health'),'mdi:heart-pulse',[pet_health_card(e,lang)])],1))
    views.append(view(tr('Technique','Technical'),'technical','mdi:cog-outline',[
        section(tr('Régulation hybride','Hybrid regulation'),'mdi:chart-donut',[reg[0], *([midnight_card(e,lang)] if midnight_card(e,lang) else []), reg[1],feed[2]]),
        section(tr('Calibration et entretien','Calibration and maintenance'),'mdi:scale',[tech[0], *([configuration_card(e,lang)] if configuration_card(e,lang) else []), tech[1]]),
        section(tr('État et commandes','Status and commands'),'mdi:shield-check',[tech[3],tech[4]])],3))
    return {'title':title,'views':views}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('fr', 'en'), default='fr')
    parser.add_argument('--device', help='HA device registry ID (only required for multiple feeders)')
    parser.add_argument('--format', choices=('card', 'dashboard'), default='card', help='Single manual card or complete Sections dashboard')
    parser.add_argument('--title', default='MOVA NutriPal', help='Title of a complete dashboard')
    parser.add_argument('--health-ui', action='store_true', help='Use the optional local health card (requires installed Lovelace resource)')
    args = parser.parse_args()
    try:
        entities = find_entities(json.load(sys.stdin), args.device)
        config = make_dashboard(entities, args.language, args.title, args.health_ui) if args.format == 'dashboard' else make_card(entities, args.language)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f'Cannot generate dashboard: {exc}\n')
    # JSON is valid YAML 1.2; no third-party YAML dependency required.
    print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
