from __future__ import annotations

import platform
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .audit import AuditTrail
from .crypto import redact_mapping, sha256_json
from .errors import PolicyDeniedError
from .models import ExecutionRequest, PolicyDecision
from .policy import GuardPolicy
from .runtime import CudaQRuntime


class Guard:
    def __init__(
        self,
        policy: GuardPolicy,
        *,
        audit_path: str | None = None,
        runtime: CudaQRuntime | None = None,
    ):
        self.policy = policy
        self.runtime = runtime or CudaQRuntime()
        self.audit = AuditTrail(audit_path) if audit_path else None

    def authorize(self, request: ExecutionRequest) -> PolicyDecision:
        # First evaluate without touching CUDA-Q. A disallowed target must not be
        # configured just to discover that it is disallowed.
        static = self.policy.evaluate(request)
        if not static.allowed:
            return static
        target_info = self.runtime.describe_target(request.target)
        return self.policy.evaluate(request, target_info)

    def execute(
        self,
        request: ExecutionRequest,
        fn: Callable[[CudaQRuntime], Any],
        *,
        resource_probe: Callable[[CudaQRuntime], dict[str, Any]] | None = None,
    ) -> Any:
        run_id = str(uuid.uuid4())
        started = time.perf_counter()
        decision: PolicyDecision
        try:
            decision = self.authorize(request)
        except Exception as exc:
            self._audit(run_id, request, None, started, "authorization_error", error=exc)
            raise

        if not decision.allowed:
            self._audit(run_id, request, decision, started, "denied")
            raise PolicyDeniedError(
                f"execution denied by policy {decision.policy_name}: {', '.join(decision.violations)}"
            )

        resources: dict[str, Any] | None = None
        try:
            self.runtime.configure(request.target, request.target_options, request.seed)
            if resource_probe is not None:
                resources = resource_probe(self.runtime)
                resource_decision = self.policy.evaluate_resources(request, resources)
                if not resource_decision.allowed:
                    self._audit(
                        run_id, request, resource_decision, started, "denied_resource", resources=resources
                    )
                    raise PolicyDeniedError(
                        f"execution denied by policy {resource_decision.policy_name}: "
                        f"{', '.join(resource_decision.violations)}"
                    )
            result = fn(self.runtime)
        except PolicyDeniedError:
            raise
        except Exception as exc:
            self._audit(run_id, request, decision, started, "error", error=exc, resources=resources)
            raise

        self._audit(
            run_id, request, decision, started, "completed", result=result, resources=resources
        )
        return result

    def _audit(
        self,
        run_id: str,
        request: ExecutionRequest,
        decision: PolicyDecision | None,
        started: float,
        status: str,
        *,
        result: Any | None = None,
        error: BaseException | None = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        if self.audit is None:
            return
        request_dict = request.to_dict()
        request_dict["target_options"] = redact_mapping(request.target_options)
        record: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "request": request_dict,
            "request_hash": sha256_json(request_dict),
            "policy": decision.to_dict() if decision else None,
            "python": platform.python_version(),
            "cudaq_version": self.runtime.version,
        }
        if resources is not None:
            record["resources"] = resources
        if result is not None:
            record["result"] = summarize_result(result)
        if error is not None:
            record["error"] = {"type": type(error).__name__, "message": str(error)}
        self.audit.append(record)


def summarize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "expectation") and callable(result.expectation):
        try:
            return {"kind": "observe", "expectation": float(result.expectation())}
        except Exception:
            pass
    if hasattr(result, "items"):
        try:
            counts = {str(k): int(v) for k, v in result.items()}
            return {"kind": "sample", "counts": counts, "shots": int(sum(counts.values()))}
        except Exception:
            pass
    if isinstance(result, dict):
        return {"kind": "mapping", "value": result}
    return {"kind": "text", "value": str(result)}
