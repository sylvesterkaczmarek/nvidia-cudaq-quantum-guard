"""Policy-controlled execution and audit tooling for NVIDIA CUDA-Q."""

from .audit import AuditTrail, verify_audit
from .guard import Guard
from .models import ExecutionRequest, PolicyDecision, TargetInfo
from .policy import GuardPolicy
from .runtime import CudaQRuntime

__all__ = [
    "AuditTrail",
    "CudaQRuntime",
    "ExecutionRequest",
    "Guard",
    "GuardPolicy",
    "PolicyDecision",
    "TargetInfo",
    "verify_audit",
]

__version__ = "0.4.0"
