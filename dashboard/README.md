# Native MOVA NutriPal dashboard

The generator produces either a complete responsive Sections dashboard (up to three columns on wide screens, fewer on small screens) or a single manual Lovelace card. Both are read-only: no dispensing, acknowledgement or setting controls. No frontend plugin or global theme is required. Entity icons and colors follow the integration and the active HA theme.

The view groups feeding, feeder status (with the optional camera), and hybrid simulation with passive calibration into three compact sections. Two history graphs share a wider section; manual supplement status remains read-only. A native Markdown card shows estimated dispensing versus the daily target with a ten-segment progress indicator (the percentage can exceed 100%). It shows unavailable data instead of zero when measurements or units are incompatible. The next scheduled meal shows the HA-local date and time, portion count and a minute-updated countdown; a past scheduled time is flagged for verification. The status summary distinguishes offline, unavailable, warning and fault states. No custom theme or CSS is installed. Recorder history must be available for graphs. Daily counters reset at midnight; they are not rolling 48-hour totals. No per-cat intake is inferred.

## Generate locally

After installing the integration and restarting Home Assistant, run from this repository on a computer that can SSH into HA:

```sh
ssh root@HOME_ASSISTANT_IP 'cat /config/.storage/core.entity_registry' | python3 tools/generate_dashboard.py --language fr --format dashboard --title 'MOVA NutriPal' > /tmp/mova-nutripal-dashboard.yaml
cat /tmp/mova-nutripal-dashboard.yaml
```

Replace the SSH destination with your own. For English use `--language en`. For a single card use `--format card` (also the default, for compatibility). The script runs locally and reads registry data from standard input; do not upload or share the registry. It resolves actual entity IDs through the existing unique IDs, including renamed entities. For multiple feeders, pass `--device` with the selected HA device registry ID. Missing or disabled required entities are reported; optional entities, including the camera, are omitted rather than guessed.

## Install the generated configuration

For a full dashboard, create a **new** empty dashboard in Home Assistant (Settings > Dashboards). Open it, enter edit mode and open the Raw configuration editor from the menu. Paste the generated content, replacing only this new dashboard's configuration, then save. JSON syntax is valid YAML. To preserve an existing dashboard, make a backup or use the single-card format instead: add a Manual card and paste its generated configuration.

The camera tile is present only when the camera entity is enabled in the selected device's registry. It uses the native More info dialog and never embeds a picture or auto-playing live stream. Opening the dialog can start the stream; closing it leaves HA's normal idle timeout in control. Other cards or viewers may still request video or JPEGs. No change to global HLS settings is needed.

The next meal is displayed only for an unambiguous supported daily kibble schedule; unsupported, overdue-unconfirmed or unavailable schedules remain unavailable. The displayed time is a schedule, not a guarantee of dispensing. Estimated distribution and forecast are not measured consumption. Automatic supplementation remains simulation only.

Do not commit generated personal dashboards or registry data to the public repository.
