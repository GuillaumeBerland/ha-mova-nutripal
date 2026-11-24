# Native MOVA NutriPal dashboard card

No additional frontend integration or custom card is needed. The card is read-only and has no dispense or unlock buttons. It shows total intake (not per cat), estimated distribution, next scheduled meal, simulation, calibration and status. The 24-hour graph uses Home Assistant's existing Recorder history, if available.

After installing 0.2.2 and restarting Home Assistant, run from this repository on a computer that can SSH into HA:

```sh
ssh root@HOME_ASSISTANT_IP 'cat /config/.storage/core.entity_registry' | python3 tools/generate_dashboard.py --language fr > /tmp/mova-nutripal-card.yaml
cat /tmp/mova-nutripal-card.yaml
```

Replace the SSH destination with your own. The script runs locally and reads registry data from standard input; do not upload or share the registry. It resolves actual entity IDs through the existing unique IDs, including renamed entities. For multiple feeders, pass `--device` with the selected HA device registry ID. Disabled or missing required entities are reported rather than silently guessed.

In Home Assistant, edit a dashboard, add a Manual card, and paste the generated content (JSON syntax accepted as YAML). Save. For English use `--language en`. If needed, change the display labels in the dashboard editor. Do not commit the generated personal dashboard or registry to this public repository.

The next meal is displayed only for an unambiguous supported daily kibble schedule; unsupported, overdue-unconfirmed or unavailable schedules remain unavailable. The displayed time is a schedule, not a guarantee of dispensing.
