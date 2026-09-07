from unittest.mock import Mock

import pytest

from cudaq_guard.errors import PolicyDeniedError
from cudaq_guard.guard import Guard
from cudaq_guard.models import ExecutionRequest, TargetInfo
from cudaq_guard.policy import GuardPolicy


def request(**changes):
    values = dict(workload="unit", operation="sample", target="qpp-cpu", qubits=2, shots=100, seed=7)
    values.update(changes)
    return ExecutionRequest(**values)


@pytest.mark.parametrize("field", ["qubits", "shots", "qpu_id", "seed"])
@pytest.mark.parametrize("value", [True, 2.5, "2", float("nan"), float("inf")])
def test_request_rejects_noninteger_counts_and_seed(field, value) -> None:
    with pytest.raises(ValueError, match=field):
        request(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"qubits": 0},
        {"shots": -1},
        {"qpu_id": -1},
        {"async_mode": "false"},
        {"async_mode": 0},
        {"workload": []},
        {"operation": False},
        {"target": ""},
        {"target_options": {"option": True}},
        {"target_options": {"": "value"}},
        {"metadata": []},
    ],
)
def test_request_rejects_invalid_field_types(changes) -> None:
    with pytest.raises(ValueError):
        request(**changes)


def test_optional_observe_shots_and_seed_are_still_supported() -> None:
    execution_request = request(operation="observe", shots=None, seed=None)
    assert GuardPolicy(require_seed=False).evaluate(execution_request).allowed


def test_request_detaches_caller_owned_options() -> None:
    options = {"option": "safe"}
    execution_request = request(target_options=options)
    options["option"] = "unsafe"
    assert execution_request.target_options == {"option": "safe"}


@pytest.mark.parametrize("num_qubits", [True, 2.9, "2", float("nan"), float("inf")])
def test_guard_does_not_execute_with_invalid_resource_count(num_qubits) -> None:
    runtime = Mock()
    runtime.describe_target.return_value = TargetInfo("qpp-cpu", simulator="qpp")
    work = Mock()
    guard = Guard(GuardPolicy(max_qubits=2), runtime=runtime)
    with pytest.raises(PolicyDeniedError, match="resource_estimate_invalid"):
        guard.execute(request(), work, resource_probe=lambda _: {"num_qubits": num_qubits})
    work.assert_not_called()
