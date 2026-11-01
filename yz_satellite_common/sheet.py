"""The sheet record — merge math for `auto_meta.json`.

Pure functions over plain dicts: no FastAPI, no settings, no filesystem.
Everything here is about *record* logic (does this fact reinforce, change
or contradict what we already hold), never about *policy* (which facts we
seek, when to ask, who may see them). Policy is core's job — see
`backend/_docs/PERSON_SHEET_PLAN.md`.

That split is why the catalog is absent from this module. Core stamps
`tier`, `dimension` and `volatility` onto a candidate from the catalog
before handing it over; the store denormalizes them so a fact survives a
catalog change and so filters work without a catalog lookup.

Deliberately dependency-free so it can move to `yz-satellite-common`
unchanged if the character self-sheets end up needing the same math.

The numbers below are defaults to tune once there is lived data. The
structure is the commitment; the constants are not.
"""
from __future__ import annotations

import time
from typing import Any

# Confidence ladder. A fact seen once is a rumour; repetition earns
# belief, asymptotically, and never reaches certainty — only a human
# promoting it to `meta.json` makes it certain.
_CONF_FIRST = 0.4
_CONF_CEIL = 1.0
_CONF_RATE = 0.7  # each further observation closes 30% of the remaining gap

# Decay half-lives in days, by catalog volatility. `stable` never decays:
# where someone was born does not get less true.
_HALF_LIFE_DAYS = {"stable": None, "slow": 183, "fast": 42}

# Testimony beats inference: what someone said about themselves outranks
# what we worked out about them, regardless of how often we worked it out.
_TESTIMONY = ("told_me", "asked")

OUTCOMES = ("answered", "deflected", "refused")
_OUTCOMES = OUTCOMES

_EMPTY: dict[str, Any] = {
    "tags": [],
    "attributes": {},
    "notes": [],
    "ask_log": {},
    "ask_blocklist": [],
    "coverage": {},
}


def empty() -> dict[str, Any]:
    """A fresh, valid sheet."""
    return normalize(None)


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Fill in anything a sheet is missing, and drop anything malformed.

    Every read goes through here, so the rest of the module can assume the
    six top-level keys exist with the right types — a truncated write or a
    hand-edited file yields a usable sheet rather than a KeyError.
    """
    sheet = dict(raw or {})
    for key, default in _EMPTY.items():
        if not isinstance(sheet.get(key), type(default)):
            sheet[key] = type(default)()
    return sheet


def _confidence(observations: int) -> float:
    """Asymptotic ladder: 0.40, 0.58, 0.71, 0.79, 0.85, ... never 1.0."""
    gap = _CONF_CEIL - _CONF_FIRST
    return round(_CONF_CEIL - gap * (_CONF_RATE ** max(0, observations - 1)), 3)


def observe(
    sheet: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge extracted candidates into a sheet.

    Each candidate is `{key, value, origin, source_chunks, tier?,
    dimension?, visibility?, volatility?}`. Returns the updated sheet and
    a change list — one entry per candidate, with `action` in
    `added | reinforced | disputed | ignored | blocked`, so the caller can
    log what the extraction pass actually did rather than diffing files.

    Blocked keys (the user deleted the fact and does not want it back) are
    dropped here rather than in core, so no caller can route around the
    blocklist.
    """
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    attrs = sheet["attributes"]
    blocked = set(sheet["ask_blocklist"])
    changes: list[dict[str, Any]] = []

    for cand in candidates:
        key = cand.get("key")
        if not key:
            continue
        if key in blocked:
            changes.append({"key": key, "action": "blocked"})
            continue

        value = cand.get("value")
        origin = cand.get("origin") or "inferred"
        chunks = list(cand.get("source_chunks") or [])
        existing = attrs.get(key)

        if existing is None:
            attrs[key] = {
                "value": value,
                "confidence": _confidence(1),
                "observations": 1,
                "first_seen": now,
                "last_seen": now,
                "source_chunks": chunks,
                "origin": origin,
                "tier": cand.get("tier", 0),
                "dimension": cand.get("dimension", "core"),
                "visibility": cand.get("visibility") or _default_visibility(cand),
                "volatility": cand.get("volatility", "slow"),
            }
            changes.append({"key": key, "action": "added", "value": value})
            continue

        if existing.get("locked") and not _same(existing.get("value"), value):
            # A locked fact is authored, not observed — the character's own
            # background story, or something a human pinned. Nothing the
            # extractor finds may contradict it, and it never becomes
            # "disputed": there is nothing to resolve, the author already
            # decided. This is what keeps an improvised detail from quietly
            # rewriting canon.
            changes.append({"key": key, "action": "locked", "value": value})
            continue

        if _same(existing.get("value"), value):
            existing["observations"] = int(existing.get("observations", 1)) + 1
            existing["confidence"] = _confidence(existing["observations"])
            existing["last_seen"] = now
            existing["source_chunks"] = _merge_chunks(existing.get("source_chunks"), chunks)
            existing.pop("disputed", None)
            # Testimony upgrades an inference in place: same value, better
            # provenance. The reverse never happens (see below).
            if origin in _TESTIMONY and existing.get("origin") not in _TESTIMONY:
                existing["origin"] = origin
            changes.append({"key": key, "action": "reinforced", "value": value})
            continue

        # Values disagree.
        if existing.get("origin") in _TESTIMONY and origin not in _TESTIMONY:
            # Never silently overwrite what someone told us with something
            # we worked out. The inference simply loses.
            changes.append({"key": key, "action": "ignored", "value": value})
            continue

        existing["disputed"] = {
            "value": value,
            "origin": origin,
            "ts": now,
            "source_chunks": chunks,
        }
        existing["confidence"] = round(float(existing.get("confidence", _CONF_FIRST)) * 0.5, 3)
        existing["last_seen"] = now
        changes.append({"key": key, "action": "disputed", "value": value})

    return sheet, changes


def _default_visibility(cand: dict[str, Any]) -> str:
    """Tier 2+ keeps to itself unless the caller says otherwise.

    The default leans closed because the failure it guards against — one
    person's confidence surfacing in front of another — is unrecoverable.
    """
    return "private" if int(cand.get("tier", 0)) >= 2 else "household"


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return a == b


def _merge_chunks(existing: Any, new: list[str]) -> list[str]:
    """Keep provenance append-only and de-duplicated. Every fact has to
    stay checkable — a fact without sources cannot be verified by the
    person it describes."""
    out = list(existing or [])
    for c in new:
        if c not in out:
            out.append(c)
    return out


def decay(sheet: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Halve confidence on the volatility-derived half-life.

    Decay is not housekeeping — it is what makes a stale fact resurface as
    something worth asking about again, which is where "you used to like
    that place" comes from.
    """
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    for attr in sheet["attributes"].values():
        if attr.get("locked"):
            # Authored facts do not fade. A character's background story is as
            # true in year two as on day one.
            continue
        half_life = _HALF_LIFE_DAYS.get(attr.get("volatility", "slow"))
        if not half_life:
            continue
        age_days = (now - float(attr.get("last_seen", now))) / 86400.0
        if age_days <= 0:
            continue
        factor = 0.5 ** (age_days / half_life)
        attr["confidence"] = round(float(attr.get("confidence", _CONF_FIRST)) * factor, 3)
    return sheet


def record_ask(
    sheet: dict[str, Any],
    key: str,
    outcome: str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Log that a slot was asked about, and how it went.

    `refused` is permanent: it adds the key to the blocklist, which
    `observe` also honours, so a refusal stops both the asking and the
    passive re-extraction of the same fact.
    """
    if outcome not in _OUTCOMES:
        raise ValueError(f"outcome must be one of {_OUTCOMES}")
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    sheet["ask_log"][key] = {"asked_at": now, "outcome": outcome}
    if outcome == "refused" and key not in sheet["ask_blocklist"]:
        sheet["ask_blocklist"].append(key)
    return sheet


def forget(sheet: dict[str, Any], key: str, *, block: bool = True) -> dict[str, Any]:
    """Delete a fact. Blocking by default: a user deleting something is
    telling us not to learn it again, not asking for it back tomorrow."""
    sheet = normalize(sheet)
    sheet["attributes"].pop(key, None)
    if block and key not in sheet["ask_blocklist"]:
        sheet["ask_blocklist"].append(key)
    return sheet


def patch_attribute(
    sheet: dict[str, Any],
    key: str,
    patch: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Hand-edit one fact (the sheet editor).

    A human edit is testimony, so it takes `origin: "told_me"` and full
    confidence unless the caller says otherwise — the person described is
    the authority on themselves.
    """
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    attr = sheet["attributes"].get(key)
    if attr is None:
        raise KeyError(key)
    for field in ("value", "visibility", "dimension", "tier", "volatility", "confidence", "origin"):
        if field in patch:
            attr[field] = patch[field]
    if "value" in patch and "confidence" not in patch:
        attr["confidence"] = _CONF_CEIL
        attr["origin"] = patch.get("origin", "told_me")
        attr.pop("disputed", None)
    attr["last_seen"] = now
    return sheet


def resolve_dispute(
    sheet: dict[str, Any],
    key: str,
    *,
    keep: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Settle a disputed fact. `keep` is "current" or "disputed".

    Resolution is the payoff of noticing: the contradiction was surfaced
    in conversation, the person answered, and this writes the answer down.
    """
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    attr = sheet["attributes"].get(key)
    if attr is None:
        raise KeyError(key)
    disputed = attr.pop("disputed", None)
    if keep == "disputed" and disputed:
        attr["value"] = disputed.get("value")
        attr["origin"] = disputed.get("origin", "told_me")
        attr["source_chunks"] = _merge_chunks(
            attr.get("source_chunks"), list(disputed.get("source_chunks") or [])
        )
        attr["observations"] = 1
    attr["confidence"] = _CONF_CEIL
    attr["last_seen"] = now
    return sheet


def put_locked(
    sheet: dict[str, Any],
    key: str,
    value: Any,
    *,
    tier: int = 0,
    dimension: str = "core",
    visibility: str | None = None,
    now: float | None = None,
) -> tuple[dict[str, Any], str]:
    """Write an authored fact — the character's background story, or anything
    a human pinned as canon.

    Returns the sheet and what happened: `added`, `unchanged`, or `refused`.
    **`refused` means the fact was already disclosed and its value differs.**
    A pack update may add facts; it may never change one the character has
    already told someone, because the listener heard the old version and there
    is no taking it back. Callers surface a refusal rather than swallowing it.
    """
    now = time.time() if now is None else now
    sheet = normalize(sheet)
    existing = sheet["attributes"].get(key)
    if existing is not None and not _same(existing.get("value"), value):
        if existing.get("disclosed_at"):
            return sheet, "refused"
    if existing is not None and _same(existing.get("value"), value):
        return sheet, "unchanged"

    sheet["attributes"][key] = {
        "value": value,
        "confidence": _CONF_CEIL,
        "observations": 1,
        "first_seen": (existing or {}).get("first_seen", now),
        "last_seen": now,
        "source_chunks": [],
        "origin": "authored",
        "locked": True,
        "tier": tier,
        "dimension": dimension,
        "visibility": visibility or ("private" if tier >= 2 else "household"),
        "volatility": "stable",
    }
    if existing is not None and existing.get("disclosed_at"):
        sheet["attributes"][key]["disclosed_at"] = existing["disclosed_at"]
    return sheet, "added"


def set_coverage(sheet: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    """Store the coverage meter core computed.

    The satellite cannot compute this itself and deliberately does not
    try: coverage is a ratio against the catalog, and the catalog is
    core's. The store only caches the answer.
    """
    sheet = normalize(sheet)
    sheet["coverage"] = dict(coverage or {})
    return sheet
