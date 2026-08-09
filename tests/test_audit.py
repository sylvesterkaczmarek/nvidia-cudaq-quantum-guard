import json
from pathlib import Path

import pytest

from cudaq_guard.audit import AuditTrail, verify_audit
from cudaq_guard.errors import AuditIntegrityError


def test_audit_chain_verifies_and_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    first = trail.append({"event": "one", "value": 1})
    second = trail.append({"event": "two", "value": 2})
    assert first["previous_hash"] == "0" * 64
    assert second["previous_hash"] == first["record_hash"]
    report = verify_audit(path)
    assert report["valid"] is True
    assert report["records"] == 2

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["value"] = 999
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        verify_audit(path)
