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


def test_append_cannot_override_chain_metadata(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    first = trail.append({"event": "one"})
    second = trail.append({"event": "two", "previous_hash": "forged", "record_hash": "forged"})
    assert second["previous_hash"] == first["record_hash"]
    assert verify_audit(path)["records"] == 2


@pytest.mark.parametrize("damage", [b'{"incomplete":', b'not json\n', b'\xff\n'])
def test_append_rejects_damaged_history_without_modifying_it(tmp_path: Path, damage: bytes) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append({"event": "one"})
    path.write_bytes(path.read_bytes() + damage)
    before = path.read_bytes()
    with pytest.raises(AuditIntegrityError):
        trail.append({"event": "two"})
    assert path.read_bytes() == before
    with pytest.raises(AuditIntegrityError):
        trail.preflight()
    assert path.read_bytes() == before


def test_unterminated_record_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append({"event": "one"})
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    before = path.read_bytes()
    with pytest.raises(AuditIntegrityError, match="unterminated"):
        verify_audit(path)
    with pytest.raises(AuditIntegrityError, match="unterminated"):
        trail.append({"event": "two"})
    assert path.read_bytes() == before


def test_append_rejects_rehashed_chain_break(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append({"event": "one"})
    trail.append({"event": "two"})
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(reversed(lines)))
    before = path.read_bytes()
    with pytest.raises(AuditIntegrityError, match="previous hash mismatch"):
        trail.append({"event": "three"})
    assert path.read_bytes() == before


def test_preflight_creates_empty_log_without_a_record(tmp_path: Path) -> None:
    path = tmp_path / "new" / "audit.jsonl"
    trail = AuditTrail(path)
    trail.preflight()
    assert path.read_bytes() == b""
    assert verify_audit(path)["records"] == 0
    trail.append({"event": "one"})
    before = path.read_bytes()
    trail.preflight()
    assert path.read_bytes() == before
