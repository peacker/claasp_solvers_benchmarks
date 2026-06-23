"""Container-side benchmark worker."""

from __future__ import annotations

import json
import resource
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .schema import benchmark_from_dict
from .runner import _base_result, maxrss_to_mb


def _run_claasp_import_check(task: dict[str, Any]) -> dict[str, Any]:
    import claasp  # noqa: F401

    checks: dict[str, Any] = {"claasp_imported": True}
    if task.get("show_solvers"):
        from claasp.cipher_modules.models.utils import set_component_solution  # noqa: F401

        checks["claasp_model_utils_imported"] = True
    return checks


def _run_synthetic(task: dict[str, Any]) -> dict[str, Any]:
    time.sleep(min(float(task.get("synthetic_wall_time_seconds", 0.01)), 0.05))
    return {"synthetic": True}


def run_worker(manifest_path: Path, result_path: Path) -> int:
    with manifest_path.open("r", encoding="utf-8") as handle:
        benchmark = benchmark_from_dict(json.load(handle))
    result = _base_result(benchmark)
    started = time.perf_counter()
    start_usage = resource.getrusage(resource.RUSAGE_SELF)
    task = benchmark.execution.task
    try:
        task_kind = task.get("kind", "claasp_import_check")
        if task_kind == "claasp_import_check":
            details = _run_claasp_import_check(task)
        elif task_kind == "synthetic":
            details = _run_synthetic(task)
        else:
            raise ValueError(f"unsupported worker task kind: {task_kind}")
        result["status"] = task.get("status", benchmark.execution.expected_status or "sat")
        result["artifacts"]["worker_details"] = details
        result["model"].update(task.get("model", {}))
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    end_usage = resource.getrusage(resource.RUSAGE_SELF)
    result["timing"]["wall_time_seconds"] = round(time.perf_counter() - started, 6)
    result["timing"]["cpu_time_seconds"] = round(
        (end_usage.ru_utime + end_usage.ru_stime) - (start_usage.ru_utime + start_usage.ru_stime),
        6,
    )
    result["resources"]["peak_memory_mb"] = maxrss_to_mb(end_usage.ru_maxrss)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["status"] != "error" else 1


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m claasp_bench.worker /bench/benchmark.json", file=sys.stderr)
        return 2
    manifest_path = Path(args[0])
    return run_worker(manifest_path, manifest_path.with_name("result.json"))


if __name__ == "__main__":
    raise SystemExit(main())
