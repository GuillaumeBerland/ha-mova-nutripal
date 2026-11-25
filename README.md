# MOVA NutriPal for Home Assistant

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/mova_nutripal/brand/dark_logo@2x.png">
  <img src="custom_components/mova_nutripal/brand/logo@2x.png" alt="MOVA NutriPal — community integration" width="380">
</picture>

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

## Scheduled meal calendar
The native read-only calendar projects the current supported daily kibble schedule for today and the following 59 days. No additional cloud calls, no schedule writes, and no historical reconstruction. Unsupported repeat types, expired or invalid schedules are unavailable rather than guessed. Ambiguous or nonexistent local times during daylight-saving transitions are omitted. Events are one-minute calendar markers, not confirmed dispensing or measured durations. Use the calendar for information, not feeding automation.

## Dashboard
A native, read-only dashboard is available in a responsive Sections layout or as a single card. See [dashboard instructions](dashboard/README.md) to generate it with your actual entity IDs (French or English). The optional camera opens on demand; no extra frontend plugin or global theme is required.

## Development
Before the first publication, run `bash prepare.sh` using the existing local upstream clone (optionally supply its path). It exports the three pinned transport files and the original license. They must be committed; HACS users do not run the script. Run `python3 -m unittest discover -s tests -v`. Tests do not connect to MOVA or dispense food. HACS and live HA validation remain separate checks.

Report issues without tokens, passwords, device identifiers, camera URLs or private logs. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [CHANGELOG.md](CHANGELOG.md).

## Français
Intégration non officielle et expérimentale pour la NutriPal 10 Ultra. Le mode hybride automatique reste en simulation. La calibration passive et le complément manuel doivent être validés dans HA avant utilisation. Conserver le programme autonome adapté aux animaux. Installation via un dépôt personnalisé HACS après publication d'une release ; redémarrer HA sans supprimer l'intégration existante. Le code Dreame et sa licence sont intégrés avant la première publication.

## Assisted calibration

Keep automatic supplementation in simulation and manual dispensing disabled. In Developer Tools > Actions, select `mova_nutripal.add_calibration_measurement` and target only the **Valid calibration samples** sensor. Enter the actual number of portions, the local MOVA date, the cumulative daily portion counter immediately after the measured distribution, and the kibble-only weight before/after (same tare). Confirm no food was eaten, added or removed between weighings. No food is dispensed by this action. The action saves locally, then requests one normal coordinator refresh.

Example: 5 portions, 0 g before and 34 g after, daily counter 12, on 2026-11-24 gives 6.8 g per portion. Do not enter the example for a different event. Samples must be 2–20 g per portion, and dates must be within the last 30 days. Overlapping portion-counter ranges on the same day are rejected among the 15 retained samples, across assisted and passive sources. Older legacy samples are preserved but have no event identity. Only record a weighing once; do not reuse an evicted measurement. The last 15 accepted samples share one unweighted median, applied only with calibration enabled and at least three valid samples. Reset calibration removes both kinds of samples. The existing reference weight is not changed automatically. The calibration samples sensor exposes the retained sample details and source counts.

### Experimental compensated calibration (diagnostics only)

When passive calibration is enabled and manual supplementation is disabled, the integration can observe a supported autonomous meal. The estimate is `(bowl_after - bowl_before + intake_after - intake_before) / portions`. Since alpha.5, it requires two coherent pre-meal readings, early post-meal coverage, a completed schedule and a matching portions counter. It tracks the largest observed bowl weight and waits at least 25 minutes after the scheduled time with at least five minutes of consistent mass balance (1 g tolerance). It can wait up to 30 minutes for delayed intake counters. Estimates below the observed increase in bowl weight by more than 1 g are rejected. Missing readings, changed schedules and counter resets can invalidate the observation entirely. Observations are not certified measurements: the cloud readings may be delayed or consistently incorrect, a peak may be missed, food may be moved, and a manual action in MOVAhome cannot always be detected.

The diagnostic sensors `compensated_samples` and `compensated_weight` expose a count and median of accepted version-2 observations among the last 30 retained records. The count sensor includes `observations`, `observation_status`, `legacy_observations` and `rejected_observations` attributes. Older observations are retained as `legacy_unverified` and excluded from the count and median; completed rejected observations are also retained but excluded. Interrupted observations may only update the status without creating a record. The experimental median is never used for the hybrid planner or manual dispensing guards. Disabling passive calibration pauses collection; resetting the normal calibration does not delete these diagnostic observations. The existing 30-second near-meal polling is unchanged; when compensated observation remains active, polling continues at 60 seconds until the end of its extended window, then returns to normal. This increases the number of cloud snapshots during that window but adds no new API endpoints or feeding commands.

### Experimental daily feeding balance (alpha.4)

The daily balance is diagnostic only: consumed grams plus current bowl weight minus the inferred midnight bowl weight. The cloud consumption and bowl readings are not independent measurements. Manual food additions/removals and delayed counters may distort the reconstruction. A day boundary is inferred only from matching valid readings within six minutes on either side of local midnight (Europe/Paris), unchanged bowl weight, zero current-day counters and matching previous-day counters. Missing boundaries remain unknown; no retroactive history is fabricated. Thirty days of dated completed/partial balances are stored separately from the actuator safety state; theoretical weight uses the reference at the last valid reading of that day. The corrected forecast uses reconstructed mass plus the existing estimated remaining meals, never feeding decisions. No additional cloud request is made. The dashboard generator optionally adds a feeding history view and prioritizes the reconstructed balance when available.
