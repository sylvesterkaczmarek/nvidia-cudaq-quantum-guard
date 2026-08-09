import json
from pathlib import Path

import pytest

from cudaq_guard.audit import verify_audit
from cudaq_guard.errors import PolicyDeniedError
from cudaq_guard.guard import Guard, summarize_result
from cudaq_guard.models import ExecutionRequest, TargetInfo
from cudaq_guard.policy import GuardPolicy
from cudaq_guard.runtime import CudaQRuntime


class FakeTarget:
    name = "qpp-cpu"
    simulator = "qpp"
    platform = "default"
    description = "fake CPU simulator"

    def num_qpus(self):
        return 1

    def is_remote(self):
        return False


class FakeResources:
    def __init__(self, qubits=2):
        self.num_qubits = qubits
        self.num_used_qubits = qubits
        self.depth = 3
        self.multi_qubit_gate_count = max(0, qubits - 1)
        self.multi_qubit_depth = max(0, qubits - 1)

    def count(self):
        return max(1, self.num_qubits * 2 - 1)


class FakeCudaQ:
    __version__ = "0.test"

    def __init__(self):
        self.target = None
        self.seed = None

    def get_targets(self):
        return [FakeTarget()]

    def set_target(self, target, **options):
        self.target = (target, options)

    def set_random_seed(self, seed):
        self.seed = seed

    def estimate_resources(self, kernel, *args):
        return FakeResources(int(args[0]) if args else 2)

    def num_available_gpus(self):
        return 0


def request(**kwargs):
    data = dict(
        workload="unit",
        operation="sample",
        target="qpp-cpu",
        qubits=2,
        shots=100,
        qpu_id=0,
        seed=7,
        target_options={},
    )
    data.update(kwargs)
    return ExecutionRequest(**data)


def test_guard_executes_allowed_request_and_audits(tmp_path: Path) -> None:
    fake = FakeCudaQ()
    runtime = CudaQRuntime(fake)
    audit = tmp_path / "audit.jsonl"
    guard = Guard(GuardPolicy(max_qubits=4), audit_path=str(audit), runtime=runtime)
    result = guard.execute(request(), lambda rt: {"00": 50, "11": 50})
    assert result["00"] == 50
    assert fake.target == ("qpp-cpu", {})
    assert fake.seed == 7
    assert verify_audit(audit)["records"] == 1
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["status"] == "completed"
    assert record["result"]["shots"] == 100


def test_guard_denies_before_execution(tmp_path: Path) -> None:
    fake = FakeCudaQ()
    runtime = CudaQRuntime(fake)
    audit = tmp_path / "audit.jsonl"
    guard = Guard(GuardPolicy(max_qubits=2), audit_path=str(audit), runtime=runtime)
    called = False

    def work(_):
        nonlocal called
        called = True

    with pytest.raises(PolicyDeniedError):
        guard.execute(request(qubits=3), work)
    assert called is False
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["status"] == "denied"


def test_guard_resource_probe_blocks_underdeclared_kernel(tmp_path: Path) -> None:
    fake = FakeCudaQ()
    runtime = CudaQRuntime(fake)
    audit = tmp_path / "audit.jsonl"
    guard = Guard(GuardPolicy(max_qubits=8), audit_path=str(audit), runtime=runtime)
    called = False

    def work(_):
        nonlocal called
        called = True

    with pytest.raises(PolicyDeniedError, match="declared_qubit_limit_exceeded"):
        guard.execute(
            request(qubits=2),
            work,
            resource_probe=lambda rt: rt.estimate_resources(object(), 3),
        )
    assert called is False
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["status"] == "denied_resource"
    assert record["resources"]["num_qubits"] == 3


class SampleLike(dict):
    def expectation(self):
        return 0.25


def test_sample_result_is_not_mislabeled_as_observe() -> None:
    summary = summarize_result(SampleLike({"000": 5, "111": 3}))
    assert summary == {
        "kind": "sample",
        "counts": {"000": 5, "111": 3},
        "shots": 8,
    }
