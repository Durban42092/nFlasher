# Changelog

All notable changes to nFlasher are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0] - 2024-01-01

### Added
- GTK4 / libadwaita dark-theme frontend
- Full Odin4-compatible partition slot layout: BL / AP / CP / CSC / USERDATA
- PIT v1 and v2 binary parser with round-trip serializer
- PIT download from connected device (nphonecli / heimdall / odin4)
- PIT inspector tab with human-readable partition table
- Hot-swappable flash backend: `nphonecli`, `odin4`, `heimdall`
- Background device polling thread with automatic detection
- Live subprocess log streaming with colour-coded output
- Progress tracking via regex parsing of backend output
- Flash abort support (SIGTERM on subprocess)
- Options: Auto-reboot, T-Flash, EFS Clear, BL Update, Reset Counter, Verify
- Reboot to: Normal / Download Mode / Recovery
- udev rules for Samsung USB device access (no sudo required)
- `.desktop` file and SVG application icon
- `pip install .` / `pip install -e .` installable package
