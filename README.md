# MOVA NutriPal for Home Assistant

**Experimental — unofficial community integration.** Tested device model: `mova.feeder.q2503` (NutriPal 10 Ultra). EU MOVA cloud; currently uses Europe/Paris for feeding dates. The 0.1.0 read-only version was tested in Home Assistant Core 2026.11.2. The 0.2.x release still requires live validation. No affiliation with MOVA or Dreame.

## Features
- Daily consumption, food bowl weight, dispensing count, desiccant lifetime and device status.
- Hybrid feeding simulation that reserves the remaining autonomous schedule.
- Passive calibration around scheduled meals, with a median of recent accepted measurements.
- Optional manual one-portion supplement, disabled by default, with persistent lock on uncertain results.
- Automatic supplementation remains **simulation only**. No schedule changes are sent.

Keep an adequate independent feeding plan, verify that scheduled feeding works without internet, and monitor pets directly. Do not rely on this software as the sole food supply. Total distributed weight is an estimate; intake and distribution are different metrics. The configurable 100 g is not nutrition advice.

## Installation (HACS)
After a GitHub release is published, open HACS > Custom repositories and add `https://github.com/GuillaumeBerland/ha-mova-nutripal` as an Integration. Download a release, restart Home Assistant and add MOVA NutriPal in Settings > Devices & services. Existing users: back up HA, update the existing component and restart; do not remove the config entry or stored calibration. Keep manual dispensing disabled until verified. Do not bypass a command lock without checking the feeder physically.

## Development
Before the first publication, run `bash prepare.sh` using the existing local upstream clone (optionally supply its path). It exports the three pinned transport files and the original license. They must be committed; HACS users do not run the script. Run `python3 -m unittest discover -s tests -v`. Tests do not connect to MOVA or dispense food. HACS and live HA validation remain separate checks.

Report issues without tokens, passwords, device identifiers, camera URLs or private logs. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [CHANGELOG.md](CHANGELOG.md).

## Français
Intégration non officielle et expérimentale pour la NutriPal 10 Ultra. Le mode hybride automatique reste en simulation. La calibration passive et le complément manuel doivent être validés dans HA avant utilisation. Conserver le programme autonome adapté aux animaux. Installation via un dépôt personnalisé HACS après publication d'une release ; redémarrer HA sans supprimer l'intégration existante. Le code Dreame et sa licence sont intégrés avant la première publication.
