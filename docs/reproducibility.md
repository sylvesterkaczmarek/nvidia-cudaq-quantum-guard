# Reproducibility

Local simulator examples use an explicit CUDA-Q random seed. Policies and requests are hashed into audit records, and the audit record stores the CUDA-Q and Python versions when available.

Recommended clean run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[cudaq,dev]"
cudaq-guard doctor
cudaq-guard run ghz --policy policies/local-safe.toml --target qpp-cpu --qubits 4 --shots 1000 --seed 7
cudaq-guard audit verify runs/audit.jsonl
```

Finite-shot sampling is statistical even with deterministic simulator seeds across software versions. Bit-for-bit equality across CUDA-Q releases, different GPU architectures, and real QPUs is not claimed.

## Deuteron model and energy checks

The VQE example uses the rounded N=2 deuteron Hamiltonian from [Dumitrescu et al., *Cloud Quantum Computing of an Atomic Nucleus*, Eq. (4)](https://arxiv.org/abs/1801.03897):

```text
H = 5.907 I - 2.1433 (X0 X1 + Y0 Y1) + 0.21829 Z0 - 6.125 Z1  [MeV]
```

These coefficients describe a finite nuclear basis, not molecular hydrogen. They preserve the existing CUDA-Q example's rounding. The circuit prepares `cos(theta/2)|q0=1,q1=0> + sin(theta/2)|q0=0,q1=1>`, giving

```text
E(theta) = 5.907 - 6.34329 cos(theta) - 4.2866 sin(theta)  [MeV]
E_min = 5.907 - sqrt(6.34329^2 + 4.2866^2)              [MeV]
```

The rounded Hamiltonian's minimum is approximately -1.749 MeV. It is not the extrapolated physical deuteron binding energy. The CLI evaluates an evenly spaced grid including both endpoints of `[-pi, pi]`; it reports only the best evaluated point. For `steps >= 3`, the ideal grid's excess above the continuous minimum is at most `sqrt(6.34329^2 + 4.2866^2) * (1 - cos(pi/(steps-1)))` MeV. Non-finite expectation values raise an error instead of producing a completed result.

With CUDA-Q installed, run:

```bash
python -m pytest tests/test_workloads.py
```

The CPU tests compare several actual CUDA-Q expectation values with the analytical curve, compare the grid minimum with an independently constructed 4-by-4 Hamiltonian's lowest eigenvalue, and verify correlated GHZ samples and their total shot count. These two runtime tests are skipped when CUDA-Q is unavailable; the remaining validation tests still run. CI installs CUDA-Q explicitly for the numerical checks.
