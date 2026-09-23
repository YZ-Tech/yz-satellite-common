# Changelog

## 0.0.2

- `yz_satellite_common.sheet` — the sheet record: merge math for the
  per-person `auto_meta.json` sheets and the character self-sheets.
  Confidence ladder, volatility decay, dispute handling (testimony beats
  inference and is never silently overwritten), ask log with a permanent
  refusal blocklist, hand-edit and dispute-resolution paths.
- Lives here rather than in `yz-people` because core runs the same math on
  the character self-sheets — one copy, two callers. Pure functions over
  plain dicts, no FastAPI/settings/filesystem coupling, so the wheel stays
  dependency-free. Design: `backend/_docs/PERSON_SHEET_PLAN.md`.

## 0.0.1

First release — EventBroadcaster + `/events` router, PersistentSettings
engine, `run_server` (YZ_PORT standard); wheel-only release workflow.
