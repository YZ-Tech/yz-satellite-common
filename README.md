# yz-satellite-common

Shared plumbing for the `yz-*` satellites — the pieces that used to be
copy-pasted per satellite (FABLE: "extract a yz-satellite-common wheel"):

- **`events.EventBroadcaster`** — the in-process event fan-out four
  satellites carried as byte-identical `observer.py` copies (transcript,
  people, body, head). One instance per satellite, parameterized by
  channel name; frame shape `{event: <channel>, kind, ...}` unchanged.
- **`events.make_events_router(broadcaster)`** — the `/events` WebSocket
  endpoint (hello frame + queue pump) as a mountable APIRouter.
- **`persistent.PersistentSettings`** — the JSON-sidecar settings engine
  (load / save / apply_patch, atomic writes, allow-listed keys, coercer
  per field, optional legacy-location migration). Satellites keep a thin
  `persistent_settings.py` shim exposing their existing module API.
- **`serve.run_server(app, default_port, ...)`** — the uvicorn entry with
  the YZ_PORT standard in one place: `YZ_PORT` (core-resolved,
  settings.ports override) wins, then the satellite's legacy env, then
  its baked default.

Not a satellite: no manifest, no service, no UI. Pure library wheel — a
pip dependency of the satellites, shipped in the installer's local-index
alongside them.

The JS-side duplication (per-satellite `install-to-frontend.mjs`, vite
lib configs) is deliberately NOT here: satellites publish standalone via
git subtree, so truly shared JS needs an npm package + publishing story.
