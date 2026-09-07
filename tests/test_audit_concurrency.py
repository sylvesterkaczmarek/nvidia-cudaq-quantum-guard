from concurrent.futures import ThreadPoolExecutor, TimeoutError
import errno
import multiprocessing
import os
from pathlib import Path
import threading
import time

import pytest

from cudaq_guard.audit import AuditTrail, read_jsonl, verify_audit
from cudaq_guard.errors import AuditIntegrityError


class _SlowHeadTrail(AuditTrail):
    def _head(self) -> str:
        head = super()._head()
        # Widen the stale-head window that previously let writers fork the chain.
        time.sleep(0.002)
        return head


def _append_in_process(path: str, worker: int, ready, start) -> None:
    trail = _SlowHeadTrail(path)
    ready.put(worker)
    if not start.wait(20):
        raise RuntimeError("concurrent audit test did not start")
    for sequence in range(8):
        trail.append({"worker": worker, "sequence": sequence})


def _assert_complete(path: Path, workers: int, records: int) -> None:
    assert verify_audit(path)["records"] == workers * records
    actual = [(record["worker"], record["sequence"]) for record in read_jsonl(path)]
    assert len(actual) == len(set(actual))
    assert set(actual) == {(worker, sequence) for worker in range(workers) for sequence in range(records)}


def test_distinct_trails_serialise_simultaneous_threads(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    start = threading.Barrier(8)

    def append(worker: int) -> None:
        trail = _SlowHeadTrail(path)
        start.wait(timeout=10)
        for sequence in range(8):
            trail.append({"worker": worker, "sequence": sequence})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(8)))
    _assert_complete(path, 8, 8)


def test_distinct_trails_serialise_spawned_processes(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    processes = [context.Process(target=_append_in_process, args=(str(path), worker, ready, start))
                 for worker in range(4)]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=20) for _ in processes} == set(range(4))
        start.set()
        for process in processes:
            process.join(timeout=20)
            assert not process.is_alive(), "audit writer did not finish"
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        ready.join_thread()
    _assert_complete(path, 4, 8)


def test_readers_wait_for_a_complete_append(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append({"event": "one"})
    real_write = os.write
    partially_written = threading.Event()
    release = threading.Event()

    def paused_write(fd, data):
        if not partially_written.is_set():
            written = real_write(fd, data[:10])
            partially_written.set()
            if not release.wait(10):
                raise RuntimeError("partial audit write was not released")
            return written
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", paused_write)
    with ThreadPoolExecutor(max_workers=3) as executor:
        writer = executor.submit(trail.append, {"event": "two"})
        try:
            assert partially_written.wait(10)
            verifier = executor.submit(verify_audit, path)
            reader = executor.submit(lambda: list(read_jsonl(path)))
            with pytest.raises(TimeoutError):
                verifier.result(timeout=0.05)
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.05)
        finally:
            release.set()
        writer.result(timeout=10)
        assert verifier.result(timeout=10)["records"] == 2
        assert [record["event"] for record in reader.result(timeout=10)] == ["one", "two"]


def test_short_and_interrupted_writes_are_completed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.preflight()
    real_write = os.write
    real_fsync = os.fsync
    writes = 0
    syncs = 0

    def short_write(fd, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise InterruptedError()
        return real_write(fd, data[:7])

    def interrupted_fsync(fd):
        nonlocal syncs
        syncs += 1
        if syncs == 1:
            raise InterruptedError()
        return real_fsync(fd)

    monkeypatch.setattr(os, "write", short_write)
    monkeypatch.setattr(os, "fsync", interrupted_fsync)
    trail.append({"event": "one", "value": "long enough for multiple writes"})
    assert writes > 2
    assert syncs == 2
    assert verify_audit(path)["records"] == 1
    assert list(read_jsonl(path))[0]["value"] == "long enough for multiple writes"


def test_failed_partial_write_is_preserved_and_blocks_later_append(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append({"event": "one"})
    before = path.read_bytes()
    real_write = os.write
    writes = 0

    def failed_write(fd, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(fd, data[:9])
        raise OSError(errno.ENOSPC, "disk full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", failed_write)
        with pytest.raises(OSError, match="disk full"):
            trail.append({"event": "two"})
    damaged = path.read_bytes()
    assert damaged.startswith(before)
    assert len(damaged) == len(before) + 9
    with pytest.raises(AuditIntegrityError):
        verify_audit(path)
    with pytest.raises(AuditIntegrityError):
        trail.append({"event": "three"})
    assert path.read_bytes() == damaged


def test_zero_length_write_fails_without_success(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.preflight()
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda fd, data: 0)
        with pytest.raises(OSError, match="no write progress"):
            trail.append({"event": "one"})
    assert verify_audit(path)["records"] == 0
    trail.append({"event": "two"})
    assert verify_audit(path)["records"] == 1


def test_windows_lock_does_not_write_before_acquisition(tmp_path: Path, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    from cudaq_guard import audit

    path = tmp_path / "audit.jsonl"
    calls = []

    def locking(fd, operation, size):
        assert size == 1
        assert os.fstat(fd).st_size == 0
        calls.append(operation)
        if len(calls) == 1:
            raise OSError(errno.EACCES, "another process holds the lock")

    def unsafe_write(*args):
        raise AssertionError("must acquire the lock without an initial write")

    # Keep the platform override local to the audit module, so pathlib and the
    # test runner continue using the actual host platform.
    platform_os = SimpleNamespace(**vars(os))
    platform_os.name = "nt"
    platform_os.write = unsafe_write
    monkeypatch.setattr(audit, "os", platform_os)
    monkeypatch.setattr(audit.time, "sleep", lambda seconds: None)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(
        LK_NBLCK=2, LK_UNLCK=0, locking=locking,
    ))
    with audit._audit_lock(path):
        assert calls == [2, 2]
    assert calls == [2, 2, 0]
    assert path.with_name("audit.jsonl.lock").read_bytes() == b""
