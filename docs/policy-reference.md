# Policy reference

CUDA-Q Guard uses a small TOML policy so execution limits are reviewable and version-controlled.

```toml
version = 1
name = "local-safe"
allowed_operations = ["sample", "observe"]
allowed_targets = ["qpp-cpu", "nvidia"]
allow_remote = false
allow_async = false
max_qubits = 28
max_shots = 100000
allowed_qpu_ids = [0]
require_seed = true

[target_options.nvidia]
option = ["mqpu", "fp64"]
```

A request is denied when any bound is exceeded. Unknown policy keys, unlisted target options, unknown target-option values, and unsupported policy versions fail closed.

`allow_remote = false` is deliberately conservative. Provider target definitions can report `is_remote() = false` before provider-specific configuration is supplied, so the runtime treats a target as remote/hardware when CUDA-Q reports it as remote **or** when it has no local simulator backend. A remote policy must explicitly allow both remote execution and the provider target name.

A target-option value of `"*"` allows any value for that explicitly named option key. This is useful for provider-specific machine identifiers, but should be used narrowly.

The policy evaluates declared workload metadata such as qubit count and operation. Built-in workloads also call CUDA-Q `estimate_resources()` before execution and fail if the compiled kernel exceeds the declared or policy qubit bound. Library users can opt into the same preflight check with `resource_probe`. This is still not a compiler sandbox or formal verification of arbitrary Python control flow.
