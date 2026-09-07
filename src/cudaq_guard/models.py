from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TargetInfo:
    name: str
    simulator: str = ""
    platform: str = ""
    description: str = ""
    num_qpus: int = 1
    is_remote: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionRequest:
    workload: str
    operation: str
    target: str
    qubits: int
    shots: int | None = None
    async_mode: bool = False
    qpu_id: int = 0
    seed: int | None = None
    target_options: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("workload", "operation", "target"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.qubits) is not int or self.qubits < 1:
            raise ValueError("qubits must be a positive integer")
        if self.shots is not None and (type(self.shots) is not int or self.shots < 1):
            raise ValueError("shots must be a positive integer or None")
        if type(self.async_mode) is not bool:
            raise ValueError("async_mode must be a boolean")
        if type(self.qpu_id) is not int or self.qpu_id < 0:
            raise ValueError("qpu_id must be a non-negative integer")
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("seed must be an integer or None")
        if not isinstance(self.target_options, dict) or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str)
            for key, value in self.target_options.items()
        ):
            raise ValueError("target_options must map non-empty option names to strings")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "target_options", dict(self.target_options))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    policy_name: str
    policy_hash: str
    violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "policy_name": self.policy_name,
            "policy_hash": self.policy_hash,
            "violations": list(self.violations),
        }
