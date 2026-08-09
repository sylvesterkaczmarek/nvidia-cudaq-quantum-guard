"""Minimal library integration example for an application that already uses CUDA-Q."""

from cudaq_guard import ExecutionRequest, Guard, GuardPolicy
from cudaq_guard.runtime import CudaQRuntime

runtime = CudaQRuntime()
cudaq = runtime.cudaq


@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0])
    x.ctrl(q[0], q[1])
    mz(q)


policy = GuardPolicy.from_toml("policies/local-safe.toml")
guard = Guard(policy, audit_path="runs/library-audit.jsonl", runtime=runtime)
request = ExecutionRequest(
    workload="bell",
    operation="sample",
    target="qpp-cpu",
    qubits=2,
    shots=1000,
    seed=7,
)

counts = guard.execute(
    request,
    lambda rt: rt.sample(bell, shots=1000),
    resource_probe=lambda rt: rt.estimate_resources(bell),
)
print(counts)
