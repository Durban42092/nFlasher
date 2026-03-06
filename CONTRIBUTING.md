# Contributing to nFlasher

Thanks for wanting to improve nFlasher. Here's how to get started.

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/nflasher
cd nflasher

# System deps (Debian/Ubuntu)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                 libgirepository1.0-dev python3-dev

# Dev install with extras
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/
```

## Code style

- Formatting: `black` (line length 100)
- Linting: `ruff`
- Type hints: encouraged, checked with `mypy --strict` on core modules

```bash
black nflasher/
ruff check nflasher/
mypy nflasher/pit.py nflasher/backend.py
```

## Project structure

```
nflasher/
├── pit.py       — PIT binary format (no external deps, pure stdlib)
├── backend.py   — subprocess wrappers for nphonecli / odin4 / heimdall
└── ui.py        — GTK4 frontend (gi.repository only)
tests/
├── test_pit.py
└── test_backend.py
```

## Adding a new flash backend

1. Add a new value to `FlashBackend` enum in `backend.py`
2. Implement `_probe_<name>()` in `DeviceManager`
3. Implement `_flash_<name>()` in `FlashEngine`
4. Add the binary to `detect_backend()` priority chain
5. Wire a button in `_build_options_tab()` in `ui.py`

## Submitting a PR

- One logical change per PR
- Include a test if touching `pit.py` or `backend.py`
- Update `CHANGELOG.md` under `[Unreleased]`
- Target the `main` branch

## Reporting bugs

Open a GitHub Issue with:
- nFlasher version (`nflasher --version`)
- Backend binary + version (`nphonecli --version`, etc.)
- Device model
- Full log output (copy from the log panel)
