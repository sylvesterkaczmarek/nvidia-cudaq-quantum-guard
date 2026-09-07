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


@pytest.mark.parametrize("key", ["allow_remote", "allow_async", "require_seed"])
@pytest.mark.parametrize("value", ['"false"', "0", "1", "[]"])
def test_toml_permissions_require_boolean_values(tmp_path: Path, key: str, value: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(f"{key} = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=f"{key} must be a boolean"):
        GuardPolicy.from_toml(path)


@pytest.mark.parametrize(
    "declaration",
    [
        "version = true",
        "version = 1.0",
        'version = "1"',
        "name = 1",
        "max_qubits = true",
        "max_qubits = 2.9",
        'max_qubits = "24"',
        "max_shots = nan",
        "max_shots = 0",
        'allowed_operations = "sample"',
        "allowed_operations = [true]",
        'allowed_targets = "qpp-cpu"',
        "allowed_targets = [1]",
        "allowed_qpu_ids = [false]",
        "allowed_qpu_ids = [0.9]",
        'allowed_qpu_ids = ["0"]',
        "allowed_qpu_ids = [-1]",
        "allowed_qpu_ids = 0",
        '[target_options.nvidia]\noption = "mqpu"',
        "[target_options.nvidia]\noption = [nan]",
    ],
)
def test_toml_rejects_malformed_policy_values(tmp_path: Path, declaration: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(declaration + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        GuardPolicy.from_toml(path)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"name": 1},
        {"allow_remote": "false"},
        {"allow_async": 1},
        {"require_seed": "true"},
        {"max_qubits": float("nan")},
        {"max_shots": 1.5},
        {"allowed_operations": "sample"},
        {"allowed_targets": [False]},
        {"allowed_qpu_ids": (True,)},
        {"target_options": {"nvidia": {"option": "mqpu"}}},
        {"target_options": {"nvidia": {"option": (False,)}}},
    ],
)
def test_direct_policy_construction_validates_types(changes: dict) -> None:
    with pytest.raises(ValueError):
        GuardPolicy(**changes)


def test_empty_toml_preserves_default_policy(tmp_path: Path) -> None:
    path = tmp_path / "defaults.toml"
    path.write_text("", encoding="utf-8")
    loaded = GuardPolicy.from_toml(path)
    assert loaded == GuardPolicy()
    assert loaded.hash == GuardPolicy().hash


def test_shipped_policies_load_and_retain_explicit_permissions() -> None:
    root = Path(__file__).parents[1]
    local = GuardPolicy.from_toml(root / "policies" / "local-safe.toml")
    remote = GuardPolicy.from_toml(root / "policies" / "remote-explicit.toml")
    assert not local.allow_remote and not local.allow_async
    assert remote.allow_remote and remote.allow_async
    assert local.evaluate(req()).allowed
    assert remote.evaluate(
        req(target="braket", async_mode=True, seed=None, target_options={"machine": "example"}),
        TargetInfo("braket", is_remote=True),
    ).allowed


def test_supported_scalar_target_option_arrays_remain_compatible(tmp_path: Path) -> None:
    path = tmp_path / "scalars.toml"
    path.write_text('[target_options.qpp-cpu]\ncustom = ["text", 2, 0.5, true]\n', encoding="utf-8")
    policy = GuardPolicy.from_toml(path)
    assert policy.target_options["qpp-cpu"]["custom"] == ("text", "2", "0.5", "True")
    assert policy.evaluate(req(target_options={"custom": "2"})).allowed


def test_empty_allowlists_remain_valid_deny_all_policies() -> None:
    policy = GuardPolicy(allowed_operations=(), allowed_targets=(), allowed_qpu_ids=())
    assert not policy.evaluate(req()).allowed


def test_policy_detaches_caller_owned_collections() -> None:
    targets = ["qpp-cpu"]
    options = {"qpp-cpu": {"option": ["safe"]}}
    policy = GuardPolicy(allowed_targets=targets, target_options=options)
    initial_hash = policy.hash
    targets.append("braket")
    options["qpp-cpu"]["option"].append("unsafe")
    assert policy.hash == initial_hash
    assert not policy.evaluate(req(target="braket")).allowed
    assert not policy.evaluate(req(target_options={"option": "unsafe"})).allowed


@pytest.mark.parametrize("value", [True, False, 2.0, 2.9, "2", float("nan"), float("inf"), None, 0, -1])
def test_resource_counts_are_positive_integers_without_coercion(value) -> None:
    decision = GuardPolicy(max_qubits=2).evaluate_resources(req(qubits=2), {"num_qubits": value})
    assert not decision.allowed
    assert decision.violations == ("resource_estimate_invalid",)


@pytest.mark.parametrize("resources", [{}, None, [], "num_qubits"])
def test_invalid_resource_structure_fails_closed(resources) -> None:
    decision = GuardPolicy().evaluate_resources(req(), resources)
    assert not decision.allowed
    assert decision.violations == ("resource_estimate_invalid",)


def test_resource_integer_bounds_are_checked_without_rounding() -> None:
    policy = GuardPolicy(max_qubits=4)
    assert policy.evaluate_resources(req(qubits=4), {"num_qubits": 4}).allowed
    decision = policy.evaluate_resources(req(qubits=2), {"num_qubits": 5})
    assert set(decision.violations) == {"resource_qubit_limit_exceeded", "declared_qubit_limit_exceeded"}
