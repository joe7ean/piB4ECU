# Changelog

All notable changes to this project are documented in this file.

## [1.0.0-alpha.1] - 2026-03-26

### Added
- Root `README.md` with quick start and runtime notes.
- `docs/SETUP.md` and `docs/MEASURING_BLOCKS.md` as consolidated project docs.
- `app/ecu_trace.py` documentation for ECU-first diagnostic workflow.
- `LICENSE` (MIT).

### Changed
- Reorganized project structure into `app/` and `docs/`.
- Default HTTP port switched to `80` (overridable via `ECU_HTTP_PORT`).
- Setup documentation rewritten for clearer Raspberry Pi deployment steps.

### Removed
- Tracked local artifacts (virtualenv, caches, local editor state, old logs).
- Legacy folder layout under `passat_ecu--claudeOnline/`.
