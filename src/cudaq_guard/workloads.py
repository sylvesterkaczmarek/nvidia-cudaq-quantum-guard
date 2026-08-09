from __future__ import annotations

import math
from typing import Any


def ghz_kernel(cudaq: Any) -> Any:
    @cudaq.kernel
    def kernel(qubit_count: int):
        q = cudaq.qvector(qubit_count)
        h(q[0])
        for index in range(qubit_count - 1):
            x.ctrl(q[index], q[index + 1])
        mz(q)

    return kernel


def h2_vqe_problem(cudaq: Any) -> tuple[Any, Any]:
    from cudaq import spin

    @cudaq.kernel
    def ansatz(theta: float):
        q = cudaq.qvector(2)
        x(q[0])
        ry(theta, q[1])
        x.ctrl(q[1], q[0])

    hamiltonian = (
        5.907
        - 2.1433 * spin.x(0) * spin.x(1)
        - 2.1433 * spin.y(0) * spin.y(1)
        + 0.21829 * spin.z(0)
        - 6.125 * spin.z(1)
    )
    return ansatz, hamiltonian


def vqe_grid(runtime: Any, *, steps: int = 25, qpu_id: int = 0) -> dict[str, Any]:
    if steps < 3:
        raise ValueError("VQE grid requires at least 3 steps")
    kernel, hamiltonian = h2_vqe_problem(runtime.cudaq)
    best_theta = 0.0
    best_energy = math.inf
    evaluations: list[dict[str, float]] = []
    for index in range(steps):
        theta = -math.pi + (2.0 * math.pi * index / (steps - 1))
        result = runtime.observe(kernel, hamiltonian, theta, qpu_id=qpu_id)
        energy = float(result.expectation())
        evaluations.append({"theta": theta, "energy": energy})
        if energy < best_energy:
            best_energy = energy
            best_theta = theta
    return {
        "kind": "vqe_grid",
        "steps": steps,
        "best_theta": best_theta,
        "best_energy": best_energy,
        "evaluations": evaluations,
    }
