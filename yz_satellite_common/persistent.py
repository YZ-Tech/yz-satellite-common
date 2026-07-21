"""JSON-sidecar persistent settings — the engine behind each satellite's
thin `persistent_settings.py` shim.

Pattern (was five hand-rolled spellings): on import the shim calls
`load()` so consumers importing the live settings object immediately see
persisted state; PATCH /settings goes through `apply_patch` (allow-listed
keys, per-field coercers, unknown keys dropped silently); writes are
atomic (tmp + rename).

`legacy_paths` heals the settings-inside-data-root shape (the yz-head
footgun): when the canonical sidecar is missing but a legacy location has
one, it is loaded and immediately re-saved to the canonical path."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


class PersistentSettings:
    def __init__(
        self,
        live: Any,
        *,
        tag: str,
        path: Callable[[], Path],
        fields: dict[str, Callable[[Any], Any]],
        legacy_paths: Callable[[], Iterable[Path]] | None = None,
    ) -> None:
        """`live` is the satellite's settings object (dataclass/pydantic
        instance, mutated in place). `fields` maps each mutable key to a
        coercer; a coercer that RAISES skips that key (bad values keep the
        current state — matches the hand-rolled try/except blocks).
        `path` is a callable because sidecar locations can depend on env."""
        self._live = live
        self._tag = tag
        self._path = path
        self._fields = fields
        self._legacy_paths = legacy_paths

    @property
    def mutable_keys(self) -> tuple[str, ...]:
        return tuple(self._fields)

    def _apply(self, data: dict) -> None:
        for key, coerce in self._fields.items():
            if key not in data:
                continue
            try:
                setattr(self._live, key, coerce(data[key]))
            except Exception:  # noqa: BLE001 — bad value -> keep current
                pass

    def load(self) -> None:
        """Read the sidecar into the live object. No-op if missing
        (defaults stand); soft-fail on parse errors. A sidecar found only
        at a legacy location is migrated to the canonical path."""
        canonical = self._path()
        candidates = [canonical]
        if self._legacy_paths is not None:
            candidates += list(self._legacy_paths())
        for p in candidates:
            if not p.is_file():
                continue
            try:
                data = json.loads(p.read_text("utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"[{self._tag}] {p.name} parse failed: {e}", file=sys.stderr)
                return
            if isinstance(data, dict):
                self._apply(data)
                if p != canonical:
                    self.save()  # heal: legacy location -> canonical
            return

    def save(self) -> None:
        """Persist the mutable keys. Atomic via tmp + rename."""
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: _serialize(getattr(self._live, k)) for k in self._fields}
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(p)

    def apply_patch(self, patch: dict) -> Any:
        """Validate + apply a PATCH /settings body, persist, return the
        live object. Unknown keys are dropped silently."""
        self._apply(patch)
        self.save()
        return self._live
