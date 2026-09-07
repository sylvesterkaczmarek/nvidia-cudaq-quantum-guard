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

Permission flags require native TOML booleans: use `false`, not `"false"` or `0`. Qubit and shot limits require positive integers; QPU IDs require nonnegative integers. Operation and target allowlists require arrays of non-empty strings. Empty allowlists are valid and permit no matching requests. Omitted fields retain the `GuardPolicy` defaults. Malformed values raise `ValueError` during loading, before runtime configuration.

Direct Python construction validates the same policy fields. `ExecutionRequest` also requires positive integer counts, a boolean asynchronous flag, a nonnegative integer QPU ID, and an integer seed when supplied. Booleans and floating-point values do not count as integers. An omitted shot count remains supported for observation requests. Target-option values must be strings in the Python API; TOML target-option arrays additionally accept finite scalar values that are explicitly converted to strings for CUDA-Q.

`allow_remote = false` is deliberately conservative. Provider target definitions can report `is_remote() = false` before provider-specific configuration is supplied, so the runtime treats a target as remote/hardware when CUDA-Q reports it as remote **or** when it has no local simulator backend. A remote policy must explicitly allow both remote execution and the provider target name.

In CUDA-Q 0.15, dynamic target methods inspect the currently active platform. The guard uses that reported remote state and QPU count only for the active target, so a previous remote job cannot make every advertised simulator appear remote. For inactive targets, `num_qpus = 1` is a fallback, not a measurement of configured capacity. After requesting a target switch, the runtime checks that CUDA-Q actually activated the requested target before running a probe or workload.

A target-option value of `"*"` allows any value for that explicitly named option key. This is useful for provider-specific machine identifiers, but should be used narrowly.

The policy evaluates declared workload metadata such as qubit count and operation. Built-in workloads also call CUDA-Q `estimate_resources()` before execution and fail if the compiled kernel exceeds the declared or policy qubit bound. Library users can opt into the same preflight check with `resource_probe`. This is still not a compiler sandbox or formal verification of arbitrary Python control flow.

A resource probe must report `num_qubits` as a positive integer. Missing, fractional, boolean, or non-finite estimates are rejected before the workload callback; they are never rounded down to fit a limit.
