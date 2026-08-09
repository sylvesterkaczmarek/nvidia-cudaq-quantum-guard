from __future__ import annotations

import hashlib
import json
from typing import Any


SENSITIVE_FRAGMENTS = ("password", "passwd", "secret", "token", "credential", "api_key", "apikey")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS):
            redacted[key] = "<redacted>"
        elif isinstance(item, dict):
            redacted[key] = redact_mapping(item)
        else:
            redacted[key] = item
    return redacted
