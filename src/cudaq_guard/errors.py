class CudaQGuardError(RuntimeError):
    """Base exception for CUDA-Q Guard."""


class PolicyDeniedError(CudaQGuardError):
    """Raised when an execution request is denied by policy."""


class CudaQUnavailableError(CudaQGuardError):
    """Raised when CUDA-Q is required but unavailable."""


class AuditIntegrityError(CudaQGuardError):
    """Raised when a tamper-evident audit chain does not verify."""
