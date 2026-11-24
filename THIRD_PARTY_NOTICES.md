# Third-party notices

The directory `custom_components/mova_nutripal/dreame_cloud/` contains `protocol.py`, `exceptions.py` and `types.py` from [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum), revision `fec086caf064f2681e8bcc7be20a0d0ef54f444d`.

Copyright (c) 2022 Tasshack. MIT license; the complete original license is copied to that directory by `prepare.sh` and must be committed alongside the files. Preserve all upstream notices. The MOVA app and its downloaded plugin are not distributed here.

## Experimental camera transport

`custom_components/mova_nutripal/xp2p/` is prepared from [EvotecIT/homeassistant-dreamelawnmower](https://github.com/EvotecIT/homeassistant-dreamelawnmower), at the exact commit in `UPSTREAM_COMMIT`. Its original MIT license is included as `LICENSE`. Preserve these notices and the upstream source. The embedded host worker is the upstream project's MIT-licensed worker, not the Tencent library. At first camera use the upstream bootstrap retrieves hash-pinned Tencent XP2P binaries (Tencent terms), AOSP Bionic/VNDK files (Apache 2.0), and on x86_64 QEMU user-static (GPL-2.0-or-later) from their original distribution sources. Those separately licensed binaries are not distributed in this repository. See the upstream worker README and bootstrap for provenance; review applicable third-party terms before using the optional camera.
