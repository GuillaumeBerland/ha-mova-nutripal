# Native MOVA NutriPal dashboard

The generator produces either a complete responsive Sections dashboard (up to three columns on wide screens, fewer on small screens) or a single manual Lovelace card. The single card is read-only. The full dashboard allows explicit edits to the existing reference weight and daily target in Technical; no dispensing or acknowledgement controls. No frontend plugin or global theme is required. Entity icons and colors follow the integration and the active HA theme.

## V5.2 dashboard layout (integration v0.2.5-beta.2)

- **Home:** two responsive sections, two compact tiles, an exclusion-aware consumption summary, a scheduled-meal progress summary, next scheduled meal, on-demand camera, health summary and 24-hour bowl graph. The bar represents the scheduled meals reported complete (blue) and remaining (orange), not all dispensed food. The total includes remaining meals. Progress requires a coherent supported daily schedule and online status; inconsistent or unavailable data are not interpreted as completed meals. Reconstructed or total theoretical dispensing is shown separately on representative days. On excluded days raw intake is replaced by a warning on Home, but retained in Technical and History. The configured reference is visible, with a warning if it differs from the physical weighing proposal. No setting is applied automatically.
- **Schedule:** daily program with estimated weights, plus the native calendar if enabled. No historical dispensing is inferred from planned events.
- **History:** up to seven recent archived balances with native colored Markdown bars relative to each day's target, the full 30-day table, and raw 48-hour counter history. Excluded/incomplete days are not plotted as representative balances. Raw counters reset at midnight and may include calibration trials.
- **Technical:** detailed daily balance, simulation, physical reference, diagnostic calibration, device status, maintenance and manual-command status. The native Configuration card exposes the reference weight and daily target if enabled. The midnight diagnostic card shows the last boundary decision and its reasons (beta.2). Other cards are read-only.

The full dashboard uses existing paths (`feeding`, `meals`, `feeding-history`) and adds `technical`. Optional data and disabled entities are not guessed. The single-card format retains the previous detailed layout. No custom frontend, theme, integration update or HA restart is needed for dashboard-only changes.

## Generate locally

After installing the integration and restarting Home Assistant, run from this repository on a computer that can SSH into HA:

```sh
ssh root@HOME_ASSISTANT_IP 'cat /config/.storage/core.entity_registry' | python3 tools/generate_dashboard.py --language fr --format dashboard --title 'MOVA NutriPal' > /tmp/mova-nutripal-dashboard.yaml
cat /tmp/mova-nutripal-dashboard.yaml
```

Replace the SSH destination with your own. For English use `--language en`. For a single card use `--format card` (also the default, for compatibility). The script runs locally and reads registry data from standard input; do not upload or share the registry. It resolves actual entity IDs through the existing unique IDs, including renamed entities. For multiple feeders, pass `--device` with the selected HA device registry ID. Missing or disabled required entities are reported; optional entities, including the camera, are omitted rather than guessed.

The Schedule view is included if the selected feeder has the daily program sensors or an enabled calendar. Calendar events are projections, not dispensing history.

## Install the generated configuration

For a full dashboard, create a **new** empty dashboard in Home Assistant (Settings > Dashboards). Open it, enter edit mode and open the Raw configuration editor from the menu. Paste the generated content, replacing only this new dashboard's configuration, then save. JSON syntax is valid YAML. To preserve an existing dashboard, make a backup or use the single-card format instead: add a Manual card and paste its generated configuration.

The camera tile is present only when the camera entity is enabled in the selected device's registry. It uses the native More info dialog and never embeds a picture or auto-playing live stream. Opening the dialog can start the stream; closing it leaves HA's normal idle timeout in control. Other cards or viewers may still request video or JPEGs. No change to global HLS settings is needed.

The next meal is displayed only for an unambiguous supported daily kibble schedule; unsupported, overdue-unconfirmed or unavailable schedules remain unavailable. The displayed time is a schedule, not a guarantee of dispensing. Estimated distribution and forecast are not measured consumption. Automatic supplementation remains simulation only.

Do not commit generated personal dashboards or registry data to the public repository.

### Daily balance (alpha.4)

Regenerate the dashboard after the new diagnostic sensors are created. The feeding view separates MOVA consumption, reconstructed dispensing, and theoretical estimates (including the reference weight). The optional Feeding history view shows archived dated totals, including incomplete days, with missing quantities displayed as unknown. The first complete day requires both observed midnight boundaries. No historical reconstruction is attempted for days before installation. No dashboard action dispenses food. Reference weight and target can be edited explicitly in Technical (V5.2).

Since alpha.6, the configured reference is authoritative and automatic calibration medians are diagnostic only. The optional physical weighing proposal is displayed separately from the active reference. Regenerate after updating.

### Beta dashboard

The main view prioritizes the current daily schedule and the configured physical
reference. If a reconstructed balance is unavailable, the main colored summary still shows
scheduled progress when the plan is coherent. A marked day displays a non-representative
warning on Home; unmodified raw counters remain in Technical and History. The
history view labels excluded rows; the physical card displays the latest recorded
weighing series and whether its proposed value matches the configured reference.
The three-sample diagnostic progress is no longer the main calibration card when
the physical reference entity is present. No custom Lovelace cards are required.

## Pet health (v0.2.6-alpha.2)

A fifth **Health** view is generated when the selected feeder has an enabled
`pet_health` sensor. By default it uses a native read-only Markdown summary of
all profiles, so the generator continues to work without any frontend resource.

For interactive dated weight charts, entry of direct or carrier-based weights,
profile editing and explicit correction of previous measurements, install the
optional self-contained local card. It reads the profile and weight sensor
attributes in the HA frontend and uses the existing validated health actions.
It has no external assets, cloud requests or feeding controls. New pets are
shown without regenerating the dashboard. Imported dates are plotted from the
local history, not from HA Recorder timestamps.

1. Copy `dashboard/mova-pet-health-card.js` to
   `/config/www/mova-pet-health-card.js` on the HA host, e.g.:

   ```sh
   ssh root@HOME_ASSISTANT_IP 'mkdir -p /config/www && cat > /config/www/mova-pet-health-card.js' < dashboard/mova-pet-health-card.js
   ```

2. In HA, enable Advanced Mode in your user profile if needed. Open Settings >
   Dashboards > Resources (the three-dot menu), add `/local/mova-pet-health-card.js?v=1`
   as a **JavaScript module**. With YAML-managed resources add the equivalent
   `url` and `type: module` to your existing `lovelace.resources` configuration
   instead. If creating `www` for the first time, a Core restart may be needed
   before `/local` is served. Reload the browser after adding the resource.
3. Generate the full dashboard as usual, adding `--health-ui` to the generator
   command. Without that flag the native read-only summary is used instead.
4. Import or create profiles using the existing health actions. Historical
   measurements are read from the individual weight sensors. Do not disable
   those sensors if you want the historical chart and correction selector.
   Profile edits and measurements are saved by the backend, not in the browser.

The local card and generated configuration are generic. Keep any private import
script outside the repository; no personal names or measurements belong in Git.
A correction requires both an explicit checkbox and confirmation. One weight per
pet/date remains the rule. Empty optional profile fields preserve existing values;
clearing targets, deleting profiles or removing weights is not supported yet.
There are no veterinary records or food profiles in alpha.2. A real HA validation
is required; the optional offline browser smoke test uses a mocked HA frontend:

```sh
python tools/test_pet_health_card.py /usr/bin/chromium
```

This optional test requires Playwright and Chromium; neither is required by the
integration or the regular Python unit tests.

## Food profiles (v0.2.6-alpha.3)

The optional Health card now includes a shared food profile, mixture components,
optional declared calories, dated history and an add/correct form. Weight graphs
show vertical markers for food period start dates within their displayed date
range. The native read-only Health view also shows the current declared mixture.
The card never changes live feeding settings or recommends a ration. Update the
local `mova-pet-health-card.js` resource and increment the resource query string
(e.g. `?v=2`) to avoid using the cached alpha.2 JavaScript. Use `--health-ui` when
generating the dashboard to enable the interactive card. The native fallback can
be used without the resource. Existing pet history is retained.
