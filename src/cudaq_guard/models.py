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
