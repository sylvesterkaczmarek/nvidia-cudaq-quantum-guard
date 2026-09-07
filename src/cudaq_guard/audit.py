from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable, Iterator
from weakref import WeakValueDictionary

from .crypto import canonical_json, sha256_json
from .errors import AuditIntegrityError

GENESIS_HASH = "0" * 64

# Keep locks shared between AuditTrail instances without retaining every path
# ever used by a long-lived process. The context manager owns a strong reference.
_THREAD_LOCKS: WeakValueDictionary[str, Any] = WeakValueDictionary()
_THREAD_LOCKS_GUARD = threading.Lock()


def _reset_thread_locks() -> None:
    global _THREAD_LOCKS, _THREAD_LOCKS_GUARD
    _THREAD_LOCKS = WeakValueDictionary()
    _THREAD_LOCKS_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_thread_locks)


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    return sha256_json(record_without_hash)


@contextmanager
def _audit_lock(path: Path) -> Iterator[None]:
    key = os.path.normcase(str(path))
    with _THREAD_LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.get(key)
        if thread_lock is None:
            thread_lock = threading.Lock()
            _THREAD_LOCKS[key] = thread_lock

    with thread_lock:
        # A sidecar keeps the lock stable while the data file is opened/closed.
        # Never remove it: another process may already be waiting on its inode.
        lock_path = path.with_name(path.name + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            elif os.name == "nt":
                import msvcrt

                # Windows byte-range locks can extend beyond EOF. Do not
                # initialise the file before locking: another writer may hold it.
                os.lseek(fd, 0, os.SEEK_SET)
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except InterruptedError:
                        continue
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                raise RuntimeError(f"audit locking is unsupported on platform {os.name!r}")
        finally:
            os.close(fd)


def _read_jsonl_unlocked(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        try:
            for line_no, line in enumerate(handle, 1):
                if not line.endswith("\n"):
                    raise AuditIntegrityError(f"unterminated audit line {line_no}")
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
        except UnicodeDecodeError as exc:
            raise AuditIntegrityError("audit file is not valid UTF-8") from exc


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    resolved = Path(path).resolve()
    with _audit_lock(resolved):
        yield from _read_jsonl_unlocked(resolved)


def _verify_audit_unlocked(path: Path) -> dict[str, Any]:
    previous = GENESIS_HASH
    count = 0
    for count, record in enumerate(_read_jsonl_unlocked(path), 1):
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


def verify_audit(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    with _audit_lock(resolved):
        return _verify_audit_unlocked(resolved)


class AuditTrail:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _head(self) -> str:
        # The caller must hold the audit lock until the new record is durable.
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        return _verify_audit_unlocked(self.path)["head_hash"]

    def preflight(self) -> None:
        """Check current integrity and append access before starting an execution.

        This releases the lock on return; it cannot guarantee that a subsequent
        append succeeds after an external failure or a change in permissions.
        """
        with _audit_lock(self.path):
            self._head()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        with _audit_lock(self.path):
            record = dict(payload)
            record.pop("record_hash", None)
            record["previous_hash"] = self._head()
            record["record_hash"] = _record_hash(record)
            serialized = (canonical_json(record) + "\n").encode("utf-8")
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                remaining = memoryview(serialized)
                while remaining:
                    try:
                        written = os.write(fd, remaining)
                    except InterruptedError:
                        continue
                    if written <= 0:
                        raise OSError("audit append made no write progress")
                    remaining = remaining[written:]
                while True:
                    try:
                        os.fsync(fd)
                        break
                    except InterruptedError:
                        continue
            finally:
                os.close(fd)
            return record
