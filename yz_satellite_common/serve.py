"""The uvicorn entry every satellite main used to hand-roll — with the
YZ_PORT standard in ONE place."""
from __future__ import annotations

import os


def run_server(
    app,
    default_port: int,
    *,
    host_env: str | None = None,
    port_env: str | None = None,
    host_default: str = "127.0.0.1",
    log_level: str = "info",
) -> None:
    """Run a satellite's FastAPI app.

    Port resolution — the YZ_PORT standard:
      1. `YZ_PORT` — what core resolved (settings.ports override), passed
         via spawn env. Wins so the bind always matches the client URL.
      2. `port_env` — the satellite's legacy env var (<NAME>_PORT).
      3. `default_port` — the baked default (manifest service.url).
    Standalone runs (no YZ_PORT) keep the legacy behavior exactly."""
    import uvicorn  # lazy — keeps the wheel dependency-free

    host = os.environ.get(host_env, host_default) if host_env else host_default
    port = int(
        os.environ.get("YZ_PORT")
        or (os.environ.get(port_env) if port_env else None)
        or default_port
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level)
