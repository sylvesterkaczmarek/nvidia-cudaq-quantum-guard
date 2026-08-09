from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .crypto import sha256_json
from .models import ExecutionRequest, PolicyDecision, TargetInfo

_ALLOWED_KEYS = {
    "version",
    "name",
    "allowed_operations",
    "allowed_targets",
    "allow_remote",
    "allow_async",
    "max_qubits",
    "max_shots",
    "allowed_qpu_ids",
    "require_seed",
    "target_options",
}


@dataclass(frozen=True)
class GuardPolicy:
    version: int = 1
    name: str = "local-safe"
    allowed_operations: tuple[str, ...] = ("sample", "observe")
    allowed_targets: tuple[str, ...] = ("qpp-cpu",)
    allow_remote: bool = False
    allow_async: bool = False
    max_qubits: int = 24
    max_shots: int = 100_000
    allowed_qpu_ids: tuple[int, ...] = (0,)
    require_seed: bool = True
    target_options: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    @classmethod
    def from_toml(cls, path: str | Path) -> "GuardPolicy":
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise ValueError(f"unknown policy keys: {', '.join(sorted(unknown))}")

        target_options_raw = raw.get("target_options", {})
        if not isinstance(target_options_raw, dict):
            raise ValueError("target_options must be a TOML table")
        normalized_options: dict[str, dict[str, tuple[str, ...]]] = {}
        for target, options in target_options_raw.items():
            if not isinstance(options, dict):
                raise ValueError(f"target_options.{target} must be a table")
            normalized_options[target] = {}
            for key, values in options.items():
                if not isinstance(values, list) or not all(isinstance(v, (str, int, float, bool)) for v in values):
                    raise ValueError(f"target_options.{target}.{key} must be an array of scalar values")
                normalized_options[target][key] = tuple(str(v) for v in values)

        policy = cls(
            version=int(raw.get("version", 1)),
            name=str(raw.get("name", "local-safe")),
            allowed_operations=tuple(str(v) for v in raw.get("allowed_operations", ["sample", "observe"])),
            allowed_targets=tuple(str(v) for v in raw.get("allowed_targets", ["qpp-cpu"])),
            allow_remote=bool(raw.get("allow_remote", False)),
            allow_async=bool(raw.get("allow_async", False)),
            max_qubits=int(raw.get("max_qubits", 24)),
            max_shots=int(raw.get("max_shots", 100_000)),
            allowed_qpu_ids=tuple(int(v) for v in raw.get("allowed_qpu_ids", [0])),
            require_seed=bool(raw.get("require_seed", True)),
            target_options=normalized_options,
        )
        policy._validate_self()
        return policy

    def _validate_self(self) -> None:
        if self.version != 1:
            raise ValueError(f"unsupported policy version: {self.version}")
        if not self.name.strip():
            raise ValueError("policy name cannot be empty")
        if self.max_qubits < 1:
            raise ValueError("max_qubits must be positive")
        if self.max_shots < 1:
            raise ValueError("max_shots must be positive")
        if any(qpu < 0 for qpu in self.allowed_qpu_ids):
            raise ValueError("allowed_qpu_ids cannot contain negative values")

    @property
    def hash(self) -> str:
        data = asdict(self)
        data["target_options"] = {
            target: {key: list(values) for key, values in sorted(options.items())}
            for target, options in sorted(self.target_options.items())
        }
        return sha256_json(data)

    def evaluate(self, request: ExecutionRequest, target_info: TargetInfo | None = None) -> PolicyDecision:
        violations: list[str] = []
        if request.operation not in self.allowed_operations:
            violations.append("operation_not_allowed")
        if request.target not in self.allowed_targets:
            violations.append("target_not_allowed")
        if request.qubits < 1:
            violations.append("invalid_qubit_count")
        elif request.qubits > self.max_qubits:
            violations.append("qubit_limit_exceeded")
        if request.shots is not None:
            if request.shots < 1:
                violations.append("invalid_shot_count")
            elif request.shots > self.max_shots:
                violations.append("shot_limit_exceeded")
        if request.async_mode and not self.allow_async:
            violations.append("async_not_allowed")
        if request.qpu_id not in self.allowed_qpu_ids:
            violations.append("qpu_id_not_allowed")
        if self.require_seed and request.seed is None:
            violations.append("seed_required")
        if target_info is not None and target_info.is_remote and not self.allow_remote:
            violations.append("remote_target_not_allowed")

        allowed_options = self.target_options.get(request.target, {})
        for key, value in request.target_options.items():
            if key not in allowed_options:
                violations.append(f"target_option_not_allowed:{key}")
                continue
            allowed_values = allowed_options[key]
            if "*" not in allowed_values and str(value) not in allowed_values:
                violations.append(f"target_option_value_not_allowed:{key}")

        return PolicyDecision(
            allowed=not violations,
            policy_name=self.name,
            policy_hash=self.hash,
            violations=tuple(violations),
        )

    def evaluate_resources(self, request: ExecutionRequest, resources: dict[str, Any]) -> PolicyDecision:
        violations: list[str] = []
        try:
            actual_qubits = int(resources["num_qubits"])
        except (KeyError, TypeError, ValueError):
            actual_qubits = 0
        if actual_qubits < 1:
            violations.append("resource_estimate_invalid")
        else:
            if actual_qubits > self.max_qubits:
                violations.append("resource_qubit_limit_exceeded")
            if actual_qubits > request.qubits:
                violations.append("declared_qubit_limit_exceeded")
        return PolicyDecision(
            allowed=not violations,
            policy_name=self.name,
            policy_hash=self.hash,
            violations=tuple(violations),
        )
