# Native MOVA NutriPal dashboard

The generator produces either a complete responsive Sections dashboard (up to three columns on wide screens, fewer on small screens) or a single manual Lovelace card. Both are read-only: no dispensing, acknowledgement or setting controls. No frontend plugin or global theme is required. Entity icons and colors follow the integration and the active HA theme.

The V4 view follows three thematic columns: feeding and next meal, hybrid regulation and daily dispensing, and calibration with maintenance. Native Markdown cards highlight the next scheduled time, countdown, portion count and estimated grams; a ten-segment daily distribution bar distinguishes already dispensed kibble (blue), remaining scheduled estimate (orange), and unallocated target (white). The bar is capped at ten segments, while actual and forecast figures and percentages remain uncapped. Missing data is not treated as zero. The calibration card shows progress toward three initial valid samples and distinguishes disabled or unavailable calibration. The health summary also flags pending manual commands. History graphs show bowl weight over 24 hours and daily intake/estimated distribution over 48 hours. Daily counters reset at midnight; they are not rolling totals. No per-cat intake is inferred. Camera access is on demand via a tile without a live preview. No global theme or extra frontend plugin is required.

## Generate locally

After installing the integration and restarting Home Assistant, run from this repository on a computer that can SSH into HA:

```sh
ssh root@HOME_ASSISTANT_IP 'cat /config/.storage/core.entity_registry' | python3 tools/generate_dashboard.py --language fr --format dashboard --title 'MOVA NutriPal' > /tmp/mova-nutripal-dashboard.yaml
cat /tmp/mova-nutripal-dashboard.yaml
```

Replace the SSH destination with your own. For English use `--language en`. For a single card use `--format card` (also the default, for compatibility). The script runs locally and reads registry data from standard input; do not upload or share the registry. It resolves actual entity IDs through the existing unique IDs, including renamed entities. For multiple feeders, pass `--device` with the selected HA device registry ID. Missing or disabled required entities are reported; optional entities, including the camera, are omitted rather than guessed.

The complete dashboard optionally adds a second **Scheduled meals** view with the native calendar card when the enabled calendar entity exists for the selected feeder. The single-card format is unchanged. Calendar events are projections, not dispensing history.

## Install the generated configuration

For a full dashboard, create a **new** empty dashboard in Home Assistant (Settings > Dashboards). Open it, enter edit mode and open the Raw configuration editor from the menu. Paste the generated content, replacing only this new dashboard's configuration, then save. JSON syntax is valid YAML. To preserve an existing dashboard, make a backup or use the single-card format instead: add a Manual card and paste its generated configuration.

The camera tile is present only when the camera entity is enabled in the selected device's registry. It uses the native More info dialog and never embeds a picture or auto-playing live stream. Opening the dialog can start the stream; closing it leaves HA's normal idle timeout in control. Other cards or viewers may still request video or JPEGs. No change to global HLS settings is needed.

The next meal is displayed only for an unambiguous supported daily kibble schedule; unsupported, overdue-unconfirmed or unavailable schedules remain unavailable. The displayed time is a schedule, not a guarantee of dispensing. Estimated distribution and forecast are not measured consumption. Automatic supplementation remains simulation only.

Do not commit generated personal dashboards or registry data to the public repository.

### Daily balance (alpha.4)

Regenerate the dashboard after the new diagnostic sensors are created. The feeding view separates MOVA consumption, reconstructed dispensing, and theoretical estimates (including the reference weight). The optional Feeding history view shows archived dated totals, including incomplete days, with missing quantities displayed as unknown. The first complete day requires both observed midnight boundaries. No historical reconstruction is attempted for days before installation. No dashboard action changes feeding settings or dispenses food.

Since alpha.6, the configured reference is authoritative and automatic calibration medians are diagnostic only. The optional physical weighing proposal is displayed separately from the active reference. Regenerate after updating.
