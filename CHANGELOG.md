# Changelog

## 0.2.6-beta.2 — pet identity and care renewal
- Optional per-pet colours and local photos, with a default cat icon when no photo is available.
- Consistent identity in weight cards, charts and compact care entries; category-specific care icons.
- Renew an open care follow-up and record the new event in one durable local save. Dates are user-declared; no medical schedule is inferred.
- Existing profiles and histories remain readable. Back up before upgrading; beta.1 cannot load profiles containing new visual fields.
- Update the existing local Health card resource to `?v=7` with the matching JavaScript file. No dashboard regeneration or re-import required.
- Add offline regression coverage for visuals, concurrent changes, migration and reminders. Real HA validation remains necessary.
- No changes to feeding commands, calibration, cloud polling or reminder automation.

## 0.2.6-beta.1 — health stabilization
- Consolidate local pet profiles, dated weight history, food periods, care records and optional reminders introduced in 0.2.6 alpha releases.
- Block health writes after interrupted storage operations until reload; preserve durable data.
- Prevent shifting the date of an existing weighing or food period from its correction form. Keep expanded histories open across normal dashboard updates.
- No storage schema, feeder behavior, calibration, or cloud changes relative to alpha.5.
- Update the local Health card resource to `?v=5` after upgrading; no dashboard regeneration or re-import from alpha.5.
- Real HA validation, including midnight boundaries and notification delivery, remains necessary.

## 0.2.2 — readability and dashboard
- Clarify French and English entity labels; retain existing unique IDs.
- Group raw device codes under diagnostics without inventing SD card or mode meanings.
- Add next scheduled meal timestamp and portion count for supported daily schedules.
- Add native read-only dashboard generator with actual entity registry IDs.
- No changes to the hybrid planner, calibration algorithm, cloud requests or manual command guards.

## 0.2.1 — distribution packaging
- Add HACS metadata, documentation, original community icon and GitHub Actions.
- Bundle the pinned Dreame transport and upstream MIT license at repository preparation.
- No changes to feeding or calibration logic compared with 0.2.0.

## 0.2.0
- Passive calibration, persisted settings and restricted manual supplement.
- Automatic feeding remains simulation only.

## 0.1.0
- Cloud read-only sensors, schedule and hybrid simulation.
