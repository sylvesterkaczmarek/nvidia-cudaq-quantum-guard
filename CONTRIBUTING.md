# Contributing

Contributions are welcome when they improve practical CUDA-Q execution control, diagnostics, provenance, or reproducibility.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

For real CUDA-Q smoke tests:

```bash
python -m pip install -e ".[cudaq,dev]"
cudaq-guard doctor
make smoke
```

## Design rules

- fail closed rather than silently changing target or policy
- keep credentials out of logs and fixtures
- do not claim a security property that the code does not enforce
- keep core policy/audit code usable without a CUDA-Q installation
- add regression tests for policy semantics and execution adapters
- keep provider-specific assumptions behind explicit configuration

If a change alters the audit schema or policy semantics, document the compatibility impact in the pull request.
