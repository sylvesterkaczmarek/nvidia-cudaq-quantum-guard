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
