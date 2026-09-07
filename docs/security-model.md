# Security model

CUDA-Q Guard is an execution-control and provenance layer around CUDA-Q calls. Its useful security boundary is the guarded API or CLI invocation.

It provides:

- fail-closed policy evaluation before execution
- target, operation, qubit, shot, asynchronous-execution and QPU-ID bounds
- explicit remote-target authorization
- target-option allowlists
- deterministic-seed requirements where requested
- optional CUDA-Q resource preflight that detects under-declared qubit use before execution
- tamper-evident local audit chains
- redaction of obvious credential-like target options

It does not provide:

- a sandbox for arbitrary Python code
- formal verification that arbitrary Python code cannot bypass or misrepresent resource use
- authentication or authorization of operating-system users
- cryptographic signing of audit records
- QPU provider credential management
- formal verification of CUDA-Q kernels
- protection against code that bypasses the guard and calls CUDA-Q directly

For higher-assurance environments, place the guard behind a process/service boundary, restrict direct CUDA-Q access, use signed policy/configuration, and export audit heads to an independent log or attestation system.

CUDA-Q target and seed settings are shared within a process. Cooperating `Guard.execute()` calls therefore serialise configuration, resource probing, and the workload callback, including calls through different Guard instances. This trades in-process concurrency for consistent runtime settings. Use separate worker processes when independent execution is needed. Nested guarded calls in the same thread are rejected; a callback must not wait for another guarded call in a different thread, since that call will wait for the current callback to finish.

The protected interval ends when the callback returns. A callback submitting asynchronous work must await completion inside that interval if it depends on those runtime settings; the built-in asynchronous GHZ path does so. Direct CUDA-Q calls outside the guard do not participate in this lock.

Audit preflight detects existing corruption and access failures before runtime configuration. It cannot make execution and the final disk append atomic. See [audit persistence and locking limits](audit-format.md).
