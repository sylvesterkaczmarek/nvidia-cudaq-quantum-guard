from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .audit import verify_audit
from .doctor import collect_doctor, render_doctor, to_json
from .errors import AuditIntegrityError, CudaQGuardError
from .guard import Guard, summarize_result
from .models import ExecutionRequest
from .policy import GuardPolicy
from .runtime import CudaQRuntime
from .workloads import ghz_kernel, h2_vqe_problem, vqe_grid
from . import __version__


def _target_options(values: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"target option must be KEY=VALUE: {value}")
        key, option = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("target option key cannot be empty")
        options[key] = option.strip()
    return options


def _policy(path: str) -> GuardPolicy:
    return GuardPolicy.from_toml(path)


def _request(args: argparse.Namespace, operation: str, workload: str, qubits: int, shots: int | None) -> ExecutionRequest:
    return ExecutionRequest(
        workload=workload,
        operation=operation,
        target=args.target,
        qubits=qubits,
        shots=shots,
        async_mode=getattr(args, "async_mode", False),
        qpu_id=args.qpu_id,
        seed=args.seed,
        target_options=_target_options(args.target_option),
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    report = collect_doctor()
    print(to_json(report) if args.json else render_doctor(report))
    return 0 if report["cudaq_installed"] else 2


def cmd_targets(args: argparse.Namespace) -> int:
    targets = [target.to_dict() for target in CudaQRuntime().available_targets()]
    if args.json:
        print(json.dumps(targets, indent=2, sort_keys=True))
    else:
        for target in targets:
            print(f"{target['name']:20} qpus={target['num_qpus']:<3} simulator={target['simulator'] or '-'}")
    return 0


def cmd_policy_check(args: argparse.Namespace) -> int:
    policy = _policy(args.policy)
    request = _request(args, args.operation, "declared-workload", args.qubits, args.shots)
    runtime = CudaQRuntime()
    static = policy.evaluate(request)
    if static.allowed and args.inspect_target:
        target = runtime.describe_target(request.target)
        decision = policy.evaluate(request, target)
    else:
        decision = static
    print(json.dumps(decision.to_dict(), indent=2, sort_keys=True))
    return 0 if decision.allowed else 3


def cmd_run_ghz(args: argparse.Namespace) -> int:
    guard = Guard(_policy(args.policy), audit_path=args.audit)
    request = _request(args, "sample", "ghz", args.qubits, args.shots)
    def execute(runtime):
        kernel = ghz_kernel(runtime.cudaq)
        if args.async_mode:
            return runtime.sample_async(
                kernel, args.qubits, shots=args.shots, qpu_id=args.qpu_id
            ).get()
        return runtime.sample(kernel, args.qubits, shots=args.shots, qpu_id=args.qpu_id)

    result = guard.execute(
        request,
        execute,
        resource_probe=lambda runtime: runtime.estimate_resources(
            ghz_kernel(runtime.cudaq), args.qubits
        ),
    )
    print(json.dumps(summarize_result(result), indent=2, sort_keys=True))
    return 0


def cmd_run_vqe(args: argparse.Namespace) -> int:
    guard = Guard(_policy(args.policy), audit_path=args.audit)
    request = _request(args, "observe", "h2-vqe-grid", 2, None)
    request = ExecutionRequest(**{**request.to_dict(), "metadata": {"steps": args.steps}})
    result = guard.execute(
        request,
        lambda runtime: vqe_grid(runtime, steps=args.steps, qpu_id=args.qpu_id),
        resource_probe=lambda runtime: runtime.estimate_resources(
            h2_vqe_problem(runtime.cudaq)[0], 0.0
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    if not targets:
        raise ValueError("at least one target is required")
    policy = _policy(args.policy)
    rows: list[dict[str, Any]] = []
    for target in targets:
        namespace = argparse.Namespace(**vars(args))
        namespace.target = target
        request = _request(namespace, "sample", "ghz", args.qubits, args.shots)
        guard = Guard(policy, audit_path=args.audit)
        started = time.perf_counter()
        try:
            result = guard.execute(
                request,
                lambda runtime: (
                    runtime.sample_async(ghz_kernel(runtime.cudaq), args.qubits, shots=args.shots, qpu_id=args.qpu_id).get()
                    if args.async_mode
                    else runtime.sample(ghz_kernel(runtime.cudaq), args.qubits, shots=args.shots, qpu_id=args.qpu_id)
                ),
                resource_probe=lambda runtime: runtime.estimate_resources(
                    ghz_kernel(runtime.cudaq), args.qubits
                ),
            )
            rows.append(
                {
                    "target": target,
                    "status": "ok",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "result": summarize_result(result),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "target": target,
                    "status": "error",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0 if any(row["status"] == "ok" for row in rows) else 4


def cmd_audit_verify(args: argparse.Namespace) -> int:
    report = verify_audit(args.path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _add_execution_args(parser: argparse.ArgumentParser, *, include_async: bool = True) -> None:
    parser.add_argument("--policy", default="policies/local-safe.toml")
    parser.add_argument("--target", default="qpp-cpu")
    parser.add_argument("--target-option", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--qpu-id", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    if include_async:
        parser.add_argument("--async", dest="async_mode", action="store_true")
    else:
        parser.set_defaults(async_mode=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cudaq-guard", description="Policy-controlled CUDA-Q execution and audit tooling")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="diagnose CUDA-Q, GPU and target availability")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    targets = sub.add_parser("targets", help="list CUDA-Q targets visible on this system")
    targets.add_argument("--json", action="store_true")
    targets.set_defaults(func=cmd_targets)

    policy = sub.add_parser("policy", help="policy utilities")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    check = policy_sub.add_parser("check", help="evaluate a declared execution request")
    _add_execution_args(check)
    check.add_argument("--operation", choices=["sample", "observe", "run"], default="sample")
    check.add_argument("--qubits", type=int, default=4)
    check.add_argument("--shots", type=int, default=1000)
    check.add_argument("--inspect-target", action="store_true", help="also inspect CUDA-Q target metadata")
    check.set_defaults(func=cmd_policy_check)

    run = sub.add_parser("run", help="run built-in guarded workloads")
    run_sub = run.add_subparsers(dest="workload", required=True)
    ghz = run_sub.add_parser("ghz", help="sample a GHZ state")
    _add_execution_args(ghz)
    ghz.add_argument("--qubits", type=int, default=4)
    ghz.add_argument("--shots", type=int, default=1000)
    ghz.add_argument("--audit", default="runs/audit.jsonl")
    ghz.set_defaults(func=cmd_run_ghz)

    vqe = run_sub.add_parser("vqe", help="run a small H2 VQE grid search")
    _add_execution_args(vqe, include_async=False)
    vqe.add_argument("--steps", type=int, default=25)
    vqe.add_argument("--audit", default="runs/audit.jsonl")
    vqe.set_defaults(func=cmd_run_vqe)

    compare = sub.add_parser("compare", help="compare the guarded GHZ workload across CUDA-Q targets")
    _add_execution_args(compare)
    compare.add_argument("--targets", default="qpp-cpu,nvidia")
    compare.add_argument("--qubits", type=int, default=20)
    compare.add_argument("--shots", type=int, default=1000)
    compare.add_argument("--audit", default="runs/compare-audit.jsonl")
    compare.set_defaults(func=cmd_compare)

    audit = sub.add_parser("audit", help="tamper-evident audit utilities")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    verify = audit_sub.add_parser("verify", help="verify an audit hash chain")
    verify.add_argument("path")
    verify.set_defaults(func=cmd_audit_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (CudaQGuardError, AuditIntegrityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
