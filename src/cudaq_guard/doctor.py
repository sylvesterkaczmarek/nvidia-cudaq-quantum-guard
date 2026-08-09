from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import asdict
from typing import Any

from .errors import CudaQUnavailableError
from .runtime import CudaQRuntime


def collect_doctor(runtime: CudaQRuntime | None = None) -> dict[str, Any]:
    runtime = runtime or CudaQRuntime()
    report: dict[str, Any] = {
        "schema_version": 1,
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cudaq_installed": False,
        "cudaq_version": None,
        "cudaq_gpu_count": None,
        "targets": [],
        "nvidia_smi": None,
    }
    if shutil.which("nvidia-smi"):
        try:
            completed = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                report["nvidia_smi"] = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            report["nvidia_smi"] = None
    try:
        targets = runtime.available_targets()
    except CudaQUnavailableError:
        return report
    report["cudaq_installed"] = True
    report["cudaq_version"] = runtime.version
    report["cudaq_gpu_count"] = runtime.available_gpu_count()
    report["targets"] = [asdict(target) for target in targets]
    return report


def render_doctor(report: dict[str, Any]) -> str:
    lines = [
        f"Python: {report['python']}",
        f"Platform: {report['system']} {report['machine']}",
        f"CUDA-Q installed: {'yes' if report['cudaq_installed'] else 'no'}",
    ]
    if report["cudaq_version"]:
        lines.append(f"CUDA-Q version: {report['cudaq_version']}")
    if report["cudaq_gpu_count"] is not None:
        lines.append(f"CUDA-Q GPUs visible: {report['cudaq_gpu_count']}")
    if report["nvidia_smi"]:
        lines.append("NVIDIA GPU: " + "; ".join(report["nvidia_smi"]))
    targets = report.get("targets", [])
    if targets:
        lines.append("Targets:")
        for target in targets:
            kind = "remote/hardware" if target["is_remote"] else "simulator"
            lines.append(
                f"  - {target['name']} ({kind}, qpus={target['num_qpus']}, simulator={target['simulator'] or '-'})"
            )
    else:
        lines.append("Targets: unavailable")
    return "\n".join(lines)


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
