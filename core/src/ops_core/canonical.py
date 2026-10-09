"""Canonical JSON v1 and the payload hash (BUILD_SPEC §6, R005).

The backend hashes proposal payloads and action bodies; the destination recomputes the hash over the bytes it
receives (AM-13). Both sides must therefore produce the same bytes for the same logical value, on every platform.
The rules: UTF-8, sorted keys, compact separators, no ASCII escaping, NFC-normalised strings and keys, integers only
(floats are rejected rather than rounded), and a parser that refuses duplicate keys and non-finite numbers instead of
silently keeping the last key or producing NaN. Two distinct keys that become the same key under NFC are an error,
not a merge: a silent merge would hash a different payload from the one supplied.

Arrays keep the producer's order; this module never sorts them, because some arrays are ordered by meaning. The
producer is therefore responsible for a stable order ("documented stable array order", BUILD_SPEC §6), and
`ops_core.contracts.ProposalPayload` enforces it for the hashed payload: `evidence_refs` sorted ascending by code
point, `source_snapshots` sorted by `evidence_id`.

Tuples are accepted and emitted as arrays, so callers may pass them for immutable sequences. Sets, bytes and datetimes
are rejected: callers pre-serialise timestamps as strings (plan ruling 6).

Timestamps (plan ruling 6): inputs may spell UTC as `Z` or `+00:00`; the hashed form is the one pydantic's JSON mode
emits (`2026-10-05T12:00:00Z`), so only hashed documents (the proposal) require `Z`; `manual-proposal`, `model-pins`
and the `get_recent_alerts` input accept `Z` or `+00:00`.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Final

CANONICALIZATION_VERSION: Final = 1


class CanonicalizationError(ValueError):
    """The value cannot be part of a hashed payload (float, non-string key, key collision, duplicate, non-finite)."""


def _normalize(value: object, path: str = "$") -> object:
    """Return a copy with NFC strings and keys and only JSON-safe scalars; raise on anything the hash must never see."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError(f"float at {path}: canonical payloads use integers only")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalize(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"non-string key {key!r} at {path}")
            nfc = unicodedata.normalize("NFC", key)
            if nfc in out:
                raise CanonicalizationError(f"key collision after NFC at {path}: {key!r}")
            out[nfc] = _normalize(item, f"{path}.{key}")
        return out
    raise CanonicalizationError(f"unsupported type {type(value).__name__} at {path}")


def canonical_json(value: object) -> bytes:
    """Serialise `value` to canonical JSON v1 bytes.

    Object keys are sorted; arrays keep the order the caller gives them, so the caller must supply a stable order
    (see the module docstring).

    Raises:
        CanonicalizationError: a float, a non-string key, two keys equal after NFC, an unsupported type, an integer
            too long to print, or nesting deeper than the interpreter's recursion limit.
    """
    # Untrusted input must never surface a bare ValueError (e.g. CPython's 4300-digit int limit) or RecursionError to
    # callers that catch CanonicalizationError. `_normalize` recurses once per nesting level, so it sits inside the
    # `try` too: JSON nested 2000 deep passes `parse_json_strict` and would otherwise blow the stack here.
    try:
        normalized = _normalize(value)
        return json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except CanonicalizationError:
        raise
    except (ValueError, RecursionError) as exc:
        raise CanonicalizationError(f"cannot canonicalise: {exc}") from exc


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    """The `payload_sha256` of a value: SHA-256 over its canonical bytes."""
    return sha256_hex(canonical_json(value))


def _reject_constant(name: str) -> object:
    raise CanonicalizationError(f"non-finite number {name} is not allowed")


def _reject_float(text: str) -> object:
    raise CanonicalizationError(f"float literal {text} is not allowed: canonical payloads use integers only")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, item in pairs:
        if key in out:
            raise CanonicalizationError(f"duplicate key {key!r}")
        out[key] = item
    return out


def parse_json_strict(text: str) -> object:
    """Parse JSON the way the hash requires: duplicate keys, NaN/Infinity and float literals are errors."""
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant, parse_float=_reject_float
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        # CanonicalizationError is a ValueError, so re-raise it unchanged; everything else (oversized ints, deep
        # nesting) is untrusted-input failure that must not escape as a bare ValueError/RecursionError.
        if isinstance(exc, CanonicalizationError):
            raise
        raise CanonicalizationError(f"invalid JSON: {exc}") from exc
