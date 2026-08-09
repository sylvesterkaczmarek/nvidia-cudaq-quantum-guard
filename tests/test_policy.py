from pathlib import Path

import pytest

from cudaq_guard.models import ExecutionRequest, TargetInfo
from cudaq_guard.policy import GuardPolicy


def req(**kwargs):
    base = dict(
        workload="ghz",
        operation="sample",
        target="qpp-cpu",
        qubits=4,
        shots=1000,
        qpu_id=0,
        seed=7,
        target_options={},
    )
    base.update(kwargs)
    return ExecutionRequest(**base)


def test_local_policy_allows_bounded_cpu_sample() -> None:
    policy = GuardPolicy()
    decision = policy.evaluate(req(), TargetInfo("qpp-cpu", simulator="qpp", is_remote=False))
    assert decision.allowed
    assert not decision.violations


@pytest.mark.parametrize(
    ("execution_request", "violation"),
    [
        (req(operation="run"), "operation_not_allowed"),
        (req(target="braket"), "target_not_allowed"),
        (req(qubits=25), "qubit_limit_exceeded"),
        (req(shots=100001), "shot_limit_exceeded"),
        (req(async_mode=True), "async_not_allowed"),
        (req(qpu_id=1), "qpu_id_not_allowed"),
        (req(seed=None), "seed_required"),
    ],
)
def test_policy_denies_out_of_bounds_requests(execution_request: ExecutionRequest, violation: str) -> None:
    policy = GuardPolicy(max_qubits=24)
    decision = policy.evaluate(execution_request)
    assert not decision.allowed
    assert violation in decision.violations


def test_policy_denies_remote_target_after_runtime_inspection() -> None:
    policy = GuardPolicy(allowed_targets=("braket",), allow_remote=False)
    request = req(target="braket")
    decision = policy.evaluate(request, TargetInfo("braket", simulator="", is_remote=True))
    assert not decision.allowed
    assert "remote_target_not_allowed" in decision.violations


def test_target_options_must_be_explicitly_allowed() -> None:
    policy = GuardPolicy(
        allowed_targets=("nvidia",),
        target_options={"nvidia": {"option": ("mqpu",)}},
    )
    assert policy.evaluate(req(target="nvidia", target_options={"option": "mqpu"})).allowed
    decision = policy.evaluate(req(target="nvidia", target_options={"option": "fp64"}))
    assert not decision.allowed
    assert "target_option_value_not_allowed:option" in decision.violations


def test_target_option_wildcard_allows_explicit_key() -> None:
    policy = GuardPolicy(
        allowed_targets=("braket",),
        allow_remote=True,
        require_seed=False,
        target_options={"braket": {"machine": ("*",)}},
    )
    decision = policy.evaluate(
        req(target="braket", seed=None, target_options={"machine": "arn:example"}),
        TargetInfo("braket", simulator="", is_remote=True),
    )
    assert decision.allowed


def test_policy_hash_is_stable() -> None:
    assert GuardPolicy().hash == GuardPolicy().hash


def test_unknown_toml_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text('version = 1\nname = "x"\nmagic = true\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown policy keys"):
        GuardPolicy.from_toml(path)
