# Camera development — first milestone (not a release)

Experimental still images only. No continuous stream, microphone, recording or feeding change. The entity is disabled by default. Do not publish or install this branch in production before testing on HA OS. No automatic runtime download during integration startup; first image request triggers the upstream hash-verified installer. Native code runs under the HA Core process user, in a subprocess; review upstream code and third-party licenses before use. Internet is required for provisioning and first-time runtime setup. The runtime is cached under `.storage/mova_nutripal_xp2p` and not included in Git. No images are persisted by the integration (temporary JPEG in a private directory, removed after capture). The last JPEG may be reused in memory for 30 s. HA's `camera.snapshot` service may save images at the requested path. A separate cloud login is made on demand, not shared with feeding commands; coexistence and token behavior require live HA validation. Requests coalesce while a capture is in progress; requests within 30 s of completion reuse the last successful image (or return no image on failure) to limit repeated camera use. Do not add a continuously refreshing dashboard card yet. Disable the entity to stop requests. The device camera switch is checked before video provisioning; the integration never turns it on. If that check fails, no video session starts.

## Prepare sources

From the repository on the OptiPlex, with the existing validated upstream checkout and lab commit marker:

```sh
python3 tools/prepare_camera.py ../homeassistant-dreamelawnmower --commit "$(cat ../video_lab/upstream_commit.txt)"
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
```

Review the copied source and license, then include the entire `xp2p` package in the development branch. No external binaries or account data should be committed. The static dependency walker uses committed bytes and intentionally fails on unknown import layouts. The runtime requires requests and aiohttp (already provided by HA), Linux x86_64 or aarch64, and an FFmpeg build supporting Enhanced FLV / HEVC. Ubuntu 24.04 FFmpeg 6.1.1 was verified by the original lab. HA OS support is not verified yet. First request can take longer than HA's image HTTP timeout; if a caller times out, the shared executor capture continues through cleanup. After the capture finishes, one request within 30 seconds can retrieve the cached image. Do not repeatedly retry. Check the HA logs for sanitized stage names only. A future version will separate preparation into an explicit UI step and improve snapshot caching/lifecycle.
