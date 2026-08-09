from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from .crypto import canonical_json, sha256_json
from .errors import AuditIntegrityError

GENESIS_HASH = "0" * 64


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    return sha256_json(record_without_hash)


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise AuditIntegrityError(f"invalid JSON at audit line {line_no}") from exc
            if not isinstance(value, dict):
                raise AuditIntegrityError(f"audit line {line_no} is not an object")
            yield value


def verify_audit(path: str | Path) -> dict[str, Any]:
    previous = GENESIS_HASH
    count = 0
    for count, record in enumerate(read_jsonl(path), 1):
        expected_previous = record.get("previous_hash")
        if expected_previous != previous:
            raise AuditIntegrityError(f"audit chain broken at record {count}: previous hash mismatch")
        actual_hash = record.get("record_hash")
        payload = dict(record)
        payload.pop("record_hash", None)
        expected_hash = _record_hash(payload)
        if actual_hash != expected_hash:
            raise AuditIntegrityError(f"audit chain broken at record {count}: record hash mismatch")
        previous = actual_hash
    return {"valid": True, "records": count, "head_hash": previous}


class AuditTrail:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _head(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        return verify_audit(self.path)["head_hash"]

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record["previous_hash"] = self._head()
        record["record_hash"] = _record_hash(record)
        serialized = canonical_json(record) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, serialized.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return record
