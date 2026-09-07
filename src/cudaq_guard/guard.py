from __future__ import annotations

import platform
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from .audit import AuditTrail
from .crypto import redact_mapping, sha256_json
from .errors import PolicyDeniedError
from .models import ExecutionRequest, PolicyDecision
from .policy import GuardPolicy
from .runtime import CudaQRuntime


_EXECUTION_LOCK = threading.Lock()
_EXECUTION_STATE = threading.local()


@contextmanager
def _execution_scope():
    # CUDA-Q target and seed configuration is shared across runtime adapters.
    # Reject nesting instead of deadlocking or changing an outer run's target.
    if getattr(_EXECUTION_STATE, "active", False):
        raise ValueError("nested guarded execution is not supported")
    with _EXECUTION_LOCK:
        _EXECUTION_STATE.active = True
        try:
            yield
        finally:
            _EXECUTION_STATE.active = False


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
        static = self.policy.evaluate(request)
        if not static.allowed:
            return static
        if getattr(_EXECUTION_STATE, "active", False):
            # A read made by the executing callback already owns the lock.
            target_info = self.runtime.describe_target(request.target)
        else:
            with _EXECUTION_LOCK:
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

        if self.audit is not None:
            self.audit.preflight()

        resources: dict[str, Any] | None = None
        resource_decision: PolicyDecision | None = None
        try:
            with _execution_scope():
                self.runtime.configure(request.target, request.target_options, request.seed)
                if resource_probe is not None:
                    resources = resource_probe(self.runtime)
                    resource_decision = self.policy.evaluate_resources(request, resources)
                    if not resource_decision.allowed:
                        raise PolicyDeniedError(
                            f"execution denied by policy {resource_decision.policy_name}: "
                            f"{', '.join(resource_decision.violations)}"
                        )
                result = fn(self.runtime)
        except Exception as exc:
            if resource_decision is not None and not resource_decision.allowed:
                self._audit(run_id, request, resource_decision, started, "denied_resource", resources=resources)
            else:
                self._audit(run_id, request, decision, started, "error", error=exc, resources=resources)
            raise

        self._audit(run_id, request, decision, started, "completed", result=result, resources=resources)
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
    # CUDA-Q SampleResult exposes both mapping-style counts and expectation().
    # Mapping semantics are therefore checked first so samples are not mislabeled.
    if hasattr(result, "items"):
        try:
            counts = dict(result.items())
        except Exception:
            pass
        else:
            if counts and all(
                isinstance(key, str)
                and key
                and set(key) <= {"0", "1"}
                and type(value) is int
                and value >= 0
                for key, value in counts.items()
            ):
                return {"kind": "sample", "counts": counts, "shots": sum(counts.values())}
            return {"kind": "mapping", "value": counts}
    if hasattr(result, "expectation") and callable(result.expectation):
        try:
            return {"kind": "observe", "expectation": float(result.expectation())}
        except Exception:
            pass
    if isinstance(result, dict):
        return {"kind": "mapping", "value": result}
    return {"kind": "text", "value": str(result)}
