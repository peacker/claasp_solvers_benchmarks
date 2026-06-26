"""Benchmark runners."""

from __future__ import annotations

import json
import os
import platform
import resource
import subprocess
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from .schema import Benchmark, benchmark_to_dict, utc_now


def cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or None


def maxrss_to_mb(maxrss: int) -> float:
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return round(maxrss / divisor, 3)


def _base_result(benchmark: Benchmark) -> dict[str, Any]:
    challenge = benchmark.challenge
    execution = benchmark.execution
    return {
        "schema_version": 1,
        "benchmark_id": benchmark.id,
        "tier": benchmark.tier,
        "created_at": utc_now(),
        "challenge": {
            "id": challenge.id,
            "name": challenge.name,
            "primitive": challenge.primitive,
            "primitive_family": challenge.primitive_family,
            "goal": challenge.goal,
            "analysis": challenge.analysis,
            "model_family": challenge.model_family,
            "difficulty": challenge.difficulty,
            "parameters": challenge.parameters,
            "tags": challenge.tags,
        },
        "execution": {
            "runner": execution.runner,
            "solver": execution.solver,
            "claasp_image": execution.claasp_image,
            "timeout_seconds": execution.timeout_seconds,
            "memory_mb": execution.memory_mb,
            "seed": execution.seed,
            "expected_status": execution.expected_status,
            "num_threads": execution.num_threads,
            "task": execution.task,
            "claasp_method": execution.task.get("claasp_method_name"),
            "observed_threads": None,
            "machine": {
                "system": platform.system(),
                "machine": platform.machine(),
                "processor": platform.processor() or None,
                "platform": platform.platform(),
                "node": platform.node() or None,
                "cpu_model": cpu_model(),
                "cpu_count": os.cpu_count(),
                "usable_cpu_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(),
                "python": platform.python_version(),
            },
        },
        "cipher": {
            "id": None,
            "family_name": challenge.primitive,
            "cipher_type": None,
            "parameters": challenge.parameters,
            "number_of_rounds": challenge.parameters.get("number_of_rounds") or challenge.parameters.get("rounds"),
            "block_bit_size": challenge.parameters.get("block_bit_size"),
            "key_bit_size": challenge.parameters.get("key_bit_size"),
            "input_bit_sizes": None,
            "output_bit_size": None,
            "component_count": None,
        },
        "status": "unknown",
        "timing": {
            "wall_time_seconds": None,
            "cpu_time_seconds": None,
            "build_time_seconds": None,
            "solve_time_seconds": None,
            "time_to_first_solution_seconds": None,
            "proof_time_seconds": None,
            "enumeration_time_seconds": None,
        },
        "resources": {
            "peak_memory_mb": None,
        },
        "model": {
            "variables": None,
            "constraints": None,
            "clauses": None,
            "file_size_bytes": None,
        },
        "claasp_output": {},
        "solver_output": {},
        "artifacts": {},
        "error": None,
    }


class SyntheticRunner:
    """Deterministic local runner used for validation, reports, and site fixtures."""

    def run(self, benchmark: Benchmark, output_dir: Path) -> dict[str, Any] | list[dict[str, Any]]:
        started = time.perf_counter()
        result = _base_result(benchmark)
        task = benchmark.execution.task
        duration = float(task.get("synthetic_wall_time_seconds", 0.01))
        time.sleep(min(duration, 0.05))
        result["status"] = task.get("status", benchmark.execution.expected_status or "sat")
        result["timing"]["wall_time_seconds"] = round(time.perf_counter() - started, 6)
        result["timing"]["cpu_time_seconds"] = 0.0
        result["timing"]["build_time_seconds"] = task.get("synthetic_build_time_seconds")
        result["timing"]["solve_time_seconds"] = task.get("synthetic_solve_time_seconds")
        result["resources"]["peak_memory_mb"] = 0.0
        result["model"].update(task.get("model", {}))
        result["solver_output"].update(task.get("solver_output", {}))
        return result


class DockerRunner:
    """Run one benchmark inside a pinned CLAASP Docker image."""

    def __init__(self, workspace: Path | None = None):
        self.workspace = (workspace or Path.cwd()).resolve()

    def _claasp_source_dir(self) -> Path | None:
        env_path = os.environ.get("CLAASP_SOURCE_DIR")
        candidates = [Path(env_path).expanduser()] if env_path else []
        candidates.extend([self.workspace / "claasp", self.workspace.parent / "claasp"])
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists():
                return resolved
        return None

    def run(self, benchmark: Benchmark, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        result = _base_result(benchmark)
        actual_image = os.environ.get("CLAASP_DOCKER_IMAGE", benchmark.execution.claasp_image)
        result["execution"]["claasp_image"] = actual_image
        claasp_source_dir = self._claasp_source_dir()
        start_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="claasp-bench-") as tmp:
            manifest_path = Path(tmp) / "benchmark.json"
            manifest_path.write_text(json.dumps(benchmark_to_dict(benchmark)), encoding="utf-8")
            container_manifest = "/bench/benchmark.json"
            command = [
                "docker",
                "run",
                "--rm",
                "-e",
                "PYTHONPATH=/workspace/claasp:/workspace",
                "-v",
                f"{self.workspace}:/workspace",
                "-v",
                f"{tmp}:/bench",
            ]
            if benchmark.execution.num_threads is not None:
                command.extend(["--cpus", str(benchmark.execution.num_threads)])
            if claasp_source_dir is not None:
                command.extend(["-v", f"{claasp_source_dir}:/workspace/claasp"])
            command.extend(
                [
                    "-w",
                    "/workspace",
                    actual_image,
                    "bash",
                    "-lc",
                    f"sage -python -m claasp_bench.worker {container_manifest}",
                ]
            )
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=benchmark.execution.timeout_seconds,
                )
                stdout_excerpt = completed.stdout[-4000:]
                stderr_excerpt = completed.stderr[-4000:]
                worker_result_path = Path(tmp) / "result.json"
                if completed.returncode == 0:
                    if worker_result_path.exists():
                        result = json.loads(worker_result_path.read_text(encoding="utf-8"))
                        results = result if isinstance(result, list) else [result]
                        for item in results:
                            item["execution"]["claasp_image"] = actual_image
                            item["artifacts"].setdefault("stdout_excerpt", stdout_excerpt)
                            item["artifacts"].setdefault("stderr_excerpt", stderr_excerpt)
                        result = results if isinstance(result, list) else results[0]
                    else:
                        result["status"] = "unknown"
                        result["error"] = "worker completed without writing /bench/result.json"
                        result["artifacts"]["stdout_excerpt"] = stdout_excerpt
                        result["artifacts"]["stderr_excerpt"] = stderr_excerpt
                else:
                    if worker_result_path.exists():
                        result = json.loads(worker_result_path.read_text(encoding="utf-8"))
                        results = result if isinstance(result, list) else [result]
                        for item in results:
                            item["execution"]["claasp_image"] = actual_image
                            item["artifacts"].setdefault("stdout_excerpt", stdout_excerpt)
                            item["artifacts"].setdefault("stderr_excerpt", stderr_excerpt)
                        result = results if isinstance(result, list) else results[0]
                    else:
                        result["status"] = "error"
                        result["error"] = f"docker exited with status {completed.returncode}"
                        result["artifacts"]["stdout_excerpt"] = stdout_excerpt
                        result["artifacts"]["stderr_excerpt"] = stderr_excerpt
            except subprocess.TimeoutExpired:
                worker_result_path = Path(tmp) / "result.json"
                if worker_result_path.exists():
                    result = json.loads(worker_result_path.read_text(encoding="utf-8"))
                    results = result if isinstance(result, list) else [result]
                    for item in results:
                        item["execution"]["claasp_image"] = actual_image
                    result = results if isinstance(result, list) else results[0]
                else:
                    result["status"] = "timeout"
                    result["error"] = f"timeout after {benchmark.execution.timeout_seconds}s"
            except Exception as exc:
                result["status"] = "error"
                result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

        end_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        if isinstance(result, list):
            return result
        result["timing"]["wall_time_seconds"] = round(time.perf_counter() - started, 6)
        result["timing"]["cpu_time_seconds"] = round(
            (end_usage.ru_utime + end_usage.ru_stime) - (start_usage.ru_utime + start_usage.ru_stime),
            6,
        )
        result["resources"]["peak_memory_mb"] = max(
            result["resources"].get("peak_memory_mb") or 0,
            maxrss_to_mb(end_usage.ru_maxrss),
        )
        return result


def runner_for(name: str) -> SyntheticRunner | DockerRunner:
    if name == "synthetic":
        return SyntheticRunner()
    if name == "docker":
        return DockerRunner()
    raise ValueError(f"unknown runner {name}")
