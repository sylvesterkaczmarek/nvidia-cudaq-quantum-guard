import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from cudaq_guard.audit import verify_audit
from cudaq_guard.errors import AuditIntegrityError, PolicyDeniedError
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

    def get_target(self):
        target = FakeTarget()
        target.name = self.target[0] if self.target else "qpp-cpu"
        return target

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


@pytest.mark.parametrize("stage", ["configure", "probe", "callback"])
def test_application_policy_denials_are_audited_once(tmp_path, stage):
    runtime = CudaQRuntime(FakeCudaQ())
    audit = tmp_path / "audit.jsonl"
    guard = Guard(GuardPolicy(), runtime=runtime, audit_path=str(audit))

    def deny(*args):
        raise PolicyDeniedError("application refused execution")

    if stage == "configure":
        runtime.configure = deny
    probe = deny if stage == "probe" else lambda rt: {"num_qubits": 2}
    callback = deny if stage == "callback" else lambda rt: {"00": 100}
    with pytest.raises(PolicyDeniedError, match="application refused execution"):
        guard.execute(request(), callback, resource_probe=probe)

    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["status"] == "error"
    assert records[0]["error"]["type"] == "PolicyDeniedError"
    assert verify_audit(audit)["records"] == 1


@pytest.mark.parametrize("broken_path", ["corrupt", "directory"])
def test_known_audit_failure_prevents_runtime_and_callback(tmp_path, broken_path):
    audit = tmp_path / "audit.jsonl"
    if broken_path == "corrupt":
        audit.write_text('{"damaged": true}\n')
    else:
        audit.mkdir()
    fake = FakeCudaQ()
    guard = Guard(GuardPolicy(), runtime=CudaQRuntime(fake), audit_path=str(audit))
    calls = []
    with pytest.raises((AuditIntegrityError, OSError)):
        guard.execute(
            request(),
            lambda rt: calls.append("callback"),
            resource_probe=lambda rt: calls.append("probe"),
        )
    assert calls == []
    assert fake.target is None


@pytest.mark.parametrize(
    "value",
    [
        {"energy": -1.234, "iterations": 25},
        {"0": 1.9, "1": 2.1},
        {"0": True},
        {"0": -1},
        {"0": "5"},
        {"2": 5},
        {"": 5},
        {},
        SampleLike({"energy": 2}),
    ],
)
def test_non_histogram_mappings_keep_exact_values(value):
    assert summarize_result(value) == {"kind": "mapping", "value": value}


def test_valid_sample_histogram_keeps_zero_and_large_counts():
    counts = {"00": 0, "11": 2**60 + 1}
    assert summarize_result(counts) == {
        "kind": "sample", "counts": counts, "shots": 2**60 + 1,
    }


def test_concurrent_guards_keep_target_and_seed_until_callback_returns():
    first_running = Event()
    second_entered = Event()
    second_configured = Event()
    release_first = Event()
    shared = {"target": None, "seed": None}

    class SharedRuntime:
        def describe_target(self, target):
            return TargetInfo(target, simulator="local")

        def configure(self, target, options, seed):
            shared.update(target=target, seed=seed)
            if target == "second":
                second_configured.set()

    policy = GuardPolicy(allowed_targets=("first", "second"))

    def first_callback(rt):
        first_running.set()
        assert release_first.wait(5)
        return dict(shared)

    def second_run():
        second_entered.set()
        return Guard(policy, runtime=SharedRuntime()).execute(
            request(target="second", seed=22), lambda rt: dict(shared),
        )

    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(
            Guard(policy, runtime=SharedRuntime()).execute,
            request(target="first", seed=11), first_callback,
        )
        assert first_running.wait(5)
        second = executor.submit(second_run)
        try:
            assert second_entered.wait(5)
            assert not second_configured.wait(0.1)
        finally:
            release_first.set()
        assert first.result(timeout=5) == {"target": "first", "seed": 11}
        assert second.result(timeout=5) == {"target": "second", "seed": 22}


def test_nested_guard_is_rejected_without_changing_outer_configuration():
    fake = FakeCudaQ()
    outer = Guard(GuardPolicy(), runtime=CudaQRuntime(fake))
    inner = Guard(GuardPolicy(), runtime=CudaQRuntime(fake))

    def callback(rt):
        with pytest.raises(ValueError, match="nested guarded execution"):
            inner.execute(request(seed=99), lambda inner_rt: None)
        return fake.seed

    assert outer.execute(request(seed=7), callback) == 7
    assert outer.execute(request(seed=8), lambda rt: fake.seed) == 8


@pytest.mark.parametrize("value", [True, 2.9, "2", -1, float("nan"), float("inf")])
def test_runtime_does_not_coerce_invalid_resource_counts(value):
    fake = FakeCudaQ()
    resources = FakeResources(2)
    resources.num_qubits = value
    resources.count = lambda: 3
    fake.estimate_resources = lambda *args: resources
    runtime = CudaQRuntime(fake)
    with pytest.raises(ValueError, match="num_qubits must be a nonnegative integer"):
        runtime.estimate_resources(object())


def test_ignored_target_switch_prevents_seed_probe_and_callback(tmp_path):
    fake = FakeCudaQ()
    fake.target = ("other", {})
    fake.set_target = lambda *args, **kwargs: None
    audit = tmp_path / "audit.jsonl"
    guard = Guard(GuardPolicy(), runtime=CudaQRuntime(fake), audit_path=str(audit))
    calls = []
    with pytest.raises(ValueError, match="did not activate requested target"):
        guard.execute(
            request(), lambda rt: calls.append("callback"),
            resource_probe=lambda rt: calls.append("probe"),
        )
    assert fake.seed is None
    assert calls == []
    assert json.loads(audit.read_text())["status"] == "error"


def test_active_platform_state_is_not_copied_to_other_targets():
    class SharedPlatformTarget:
        platform = "default"
        description = "fake target"

        def __init__(self, name, simulator):
            self.name = name
            self.simulator = simulator

        def num_qpus(self):
            return 8

        def is_remote(self):
            return True

    local = SharedPlatformTarget("qpp-cpu", "qpp")
    provider = SharedPlatformTarget("provider", "")

    class Module:
        def get_targets(self):
            return [local, provider]

        def get_target(self):
            return provider

    runtime = CudaQRuntime(Module())
    targets = {target.name: target for target in runtime.available_targets()}
    assert targets["qpp-cpu"].is_remote is False
    assert targets["qpp-cpu"].num_qpus == 1
    assert targets["provider"].is_remote is True
    assert targets["provider"].num_qpus == 8
    assert Guard(GuardPolicy(), runtime=runtime).authorize(request()).allowed


def test_current_simulator_target_keeps_reported_remote_state():
    class RemoteSimulator(FakeTarget):
        def is_remote(self):
            return True

    fake = FakeCudaQ()
    fake.get_targets = lambda: [RemoteSimulator()]
    fake.get_target = lambda: RemoteSimulator()
    assert CudaQRuntime(fake).available_targets()[0].is_remote is True
