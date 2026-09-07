import math
from types import SimpleNamespace

import pytest

from cudaq_guard import workloads


@pytest.mark.parametrize("steps", [True, 2, 3.5, "25"])
def test_invalid_grid_size_is_rejected_before_runtime_use(steps):
    with pytest.raises(ValueError, match="integer number of steps"):
        workloads.vqe_grid(object(), steps=steps)


@pytest.mark.parametrize("energy", [math.nan, math.inf, -math.inf])
def test_nonfinite_expectation_cannot_be_reported_as_completed(monkeypatch, energy):
    monkeypatch.setattr(workloads, "deuteron_vqe_problem", lambda _: (object(), object()))
    runtime = SimpleNamespace(cudaq=object(), observe=lambda *a, **k: SimpleNamespace(expectation=lambda: energy))
    with pytest.raises(ValueError, match="non-finite energy"):
        workloads.vqe_grid(runtime, steps=3)


def test_historical_problem_name_remains_a_compatible_alias(monkeypatch):
    problem = (object(), object())
    monkeypatch.setattr(workloads, "deuteron_vqe_problem", lambda _: problem)
    assert workloads.h2_vqe_problem(object()) is problem


def test_cpu_deuteron_energies_match_analytic_curve_and_matrix():
    pytest.importorskip("cudaq")
    import numpy as np
    from cudaq_guard.runtime import CudaQRuntime

    runtime = CudaQRuntime()
    runtime.configure("qpp-cpu", {}, 7)
    kernel, hamiltonian = workloads.deuteron_vqe_problem(runtime.cudaq)
    # Independently constructed Pauli matrix, with qubit 0 in the right factor.
    identity = np.eye(2)
    x = np.array([[0, 1], [1, 0]])
    y = np.array([[0, -1j], [1j, 0]])
    z = np.diag([1, -1])
    matrix = (5.907 * np.eye(4) - 2.1433 * (np.kron(x, x) + np.kron(y, y))
              + 0.21829 * np.kron(identity, z) - 6.125 * np.kron(z, identity))
    ground_energy = float(np.linalg.eigvalsh(matrix)[0])
    for theta in (-math.pi, -math.pi / 2, 0.0, math.pi / 4, math.pi / 2, math.pi):
        observed = runtime.observe(kernel, hamiltonian, theta).expectation()
        expected = 5.907 - 6.34329 * math.cos(theta) - 4.2866 * math.sin(theta)
        assert observed == pytest.approx(expected, abs=1e-10)

    result = workloads.vqe_grid(runtime, steps=25)
    assert result["problem"] == "deuteron-n2"
    assert result["energy_unit"] == "MeV"
    assert result["best_energy"] == min(item["energy"] for item in result["evaluations"])
    grid_error_bound = math.hypot(6.34329, 4.2866) * (1 - math.cos(math.pi / 24))
    assert ground_energy - 1e-10 <= result["best_energy"] <= ground_energy + grid_error_bound + 1e-10


def test_cpu_ghz_sampling_has_only_correlated_states():
    pytest.importorskip("cudaq")
    from cudaq_guard.runtime import CudaQRuntime

    runtime = CudaQRuntime()
    runtime.configure("qpp-cpu", {}, 7)
    kernel = workloads.ghz_kernel(runtime.cudaq)
    resources = runtime.estimate_resources(kernel, 3)
    assert resources["num_qubits"] == 3
    counts = dict(runtime.sample(kernel, 3, shots=256).items())
    assert set(counts) == {"000", "111"}
    assert sum(counts.values()) == 256
