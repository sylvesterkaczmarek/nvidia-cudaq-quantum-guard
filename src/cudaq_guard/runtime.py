from __future__ import annotations

import importlib
import importlib.metadata
from typing import Any

from .errors import CudaQUnavailableError
from .models import TargetInfo


class CudaQRuntime:
    """Small lazy adapter over NVIDIA CUDA-Q.

    The module is imported only when execution or target discovery is requested,
    so policy validation and audit verification remain usable without CUDA-Q.
    """

    def __init__(self, module: Any | None = None):
        self._module = module

    @property
    def cudaq(self) -> Any:
        if self._module is None:
            try:
                self._module = importlib.import_module("cudaq")
            except ImportError as exc:
                raise CudaQUnavailableError(
                    'CUDA-Q is not installed. Install with: pip install "nvidia-cudaq-quantum-guard[cudaq]"'
                ) from exc
        return self._module

    @property
    def version(self) -> str | None:
        try:
            return importlib.metadata.version("cudaq")
        except importlib.metadata.PackageNotFoundError:
            return getattr(self._module, "__version__", None) if self._module is not None else None

    def available_targets(self) -> list[TargetInfo]:
        # CUDA-Q 0.15's Target.is_remote()/num_qpus() inspect the current
        # platform, even when called on a different advertised target object.
        # Only use that dynamic information for the active target.
        get_target = getattr(self.cudaq, "get_target", None)
        current_name = str(getattr(get_target(), "name", "")) if callable(get_target) else None
        targets = []
        for target in self.cudaq.get_targets():
            name = str(getattr(target, "name", ""))
            simulator = str(getattr(target, "simulator", "") or "")
            platform = str(getattr(target, "platform", "") or "")
            description = str(getattr(target, "description", "") or "")
            num_qpus = 1
            reported_remote = False
            if name == current_name:
                try:
                    num_qpus = int(target.num_qpus())
                except Exception:
                    pass
                remote_attr = getattr(target, "is_remote", None)
                try:
                    reported_remote = bool(remote_attr()) if callable(remote_attr) else bool(remote_attr)
                except Exception:
                    pass
            # Provider target definitions in CUDA-Q may report is_remote=False until
            # provider-specific configuration is supplied. Treat targets without a
            # local simulator backend as remote/hardware conservatively.
            is_remote = reported_remote or not bool(simulator)
            targets.append(TargetInfo(name, simulator, platform, description, num_qpus, is_remote))
        return targets

    def describe_target(self, name: str) -> TargetInfo:
        for target in self.available_targets():
            if target.name == name:
                return target
        raise ValueError(f"CUDA-Q target is not available: {name}")

    def configure(self, target: str, options: dict[str, str], seed: int | None) -> None:
        self.cudaq.set_target(target, **options)
        active_target = str(getattr(self.cudaq.get_target(), "name", ""))
        if active_target != target:
            raise ValueError(
                f"CUDA-Q did not activate requested target {target!r}; active target is {active_target!r}"
            )
        if seed is not None and hasattr(self.cudaq, "set_random_seed"):
            self.cudaq.set_random_seed(int(seed))

    def estimate_resources(self, kernel: Any, *args: Any) -> dict[str, int]:
        resources = self.cudaq.estimate_resources(kernel, *args)
        counts = {
            "num_qubits": getattr(resources, "num_qubits", 0),
            "num_used_qubits": getattr(resources, "num_used_qubits", 0),
            "gate_count": resources.count(),
            "depth": getattr(resources, "depth", 0),
            "multi_qubit_gate_count": getattr(resources, "multi_qubit_gate_count", 0),
            "multi_qubit_depth": getattr(resources, "multi_qubit_depth", 0),
        }
        for name, value in counts.items():
            if type(value) is not int or value < 0:
                raise ValueError(f"CUDA-Q resource estimate {name} must be a nonnegative integer")
        return counts

    def available_gpu_count(self) -> int | None:
        fn = getattr(self.cudaq, "num_available_gpus", None)
        if not callable(fn):
            return None
        try:
            return int(fn())
        except Exception:
            return None

    def sample(self, kernel: Any, *args: Any, shots: int, qpu_id: int = 0) -> Any:
        if qpu_id != 0:
            raise ValueError("synchronous cudaq.sample does not accept qpu_id; use asynchronous execution")
        return self.cudaq.sample(kernel, *args, shots_count=shots)

    def sample_async(self, kernel: Any, *args: Any, shots: int, qpu_id: int = 0) -> Any:
        return self.cudaq.sample_async(kernel, *args, shots_count=shots, qpu_id=qpu_id)

    def observe(self, kernel: Any, hamiltonian: Any, *args: Any, qpu_id: int = 0) -> Any:
        return self.cudaq.observe(kernel, hamiltonian, *args, qpu_id=qpu_id)
