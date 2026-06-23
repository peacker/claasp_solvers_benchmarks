"""Container-side benchmark worker."""

from __future__ import annotations

import copy
import json
import math
import numbers
import os
import platform
import resource
import shutil
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .schema import benchmark_from_dict
from .runner import _base_result, cpu_model, maxrss_to_mb


MODEL_FAMILY_TO_SOLVER_FAMILY = {
    "SAT": "sat",
    "SMT": "smt",
    "MILP": "milp",
    "CP_MiniZinc": "cp",
}


def _cpu_model() -> str | None:
    return cpu_model()


def _safe_public_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        if not math.isfinite(float(value)):
            return None
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_safe_public_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_public_value(item) for key, item in value.items()}
    return str(value)


def _claasp_version() -> str | None:
    try:
        import claasp

        version = getattr(claasp, "__version__", None)
        if version:
            return str(version)
    except Exception:
        return None
    version_path = Path("/workspace/claasp/VERSION")
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return None


def _instantiate_cipher(primitive: str, parameters: dict[str, Any]) -> Any:
    normalized = primitive.lower().replace("-", "").replace("_", "")
    if normalized.startswith("speck"):
        from claasp.ciphers.block_ciphers.speck_block_cipher import SpeckBlockCipher

        kwargs = {
            key: parameters[key]
            for key in ["block_bit_size", "key_bit_size", "rotation_alpha", "rotation_beta", "number_of_rounds"]
            if key in parameters
        }
        if "rounds" in parameters and "number_of_rounds" not in kwargs:
            kwargs["number_of_rounds"] = parameters["rounds"]
        return SpeckBlockCipher(**kwargs)
    raise ValueError(f"unsupported CLAASP cipher metadata primitive: {primitive}")


def _cipher_metadata(cipher: Any, parameters: dict[str, Any]) -> dict[str, Any]:
    components = []
    try:
        components = list(cipher.get_all_components())
    except Exception:
        components = []
    return {
        "id": getattr(cipher, "id", None),
        "family_name": getattr(cipher, "family_name", None),
        "cipher_type": getattr(cipher, "type", None),
        "parameters": parameters,
        "number_of_rounds": getattr(cipher, "number_of_rounds", parameters.get("number_of_rounds") or parameters.get("rounds")),
        "block_bit_size": parameters.get("block_bit_size"),
        "key_bit_size": parameters.get("key_bit_size"),
        "input_bit_sizes": _safe_public_value(getattr(cipher, "inputs_bit_size", None)),
        "output_bit_size": _safe_public_value(getattr(cipher, "output_bit_size", None)),
        "component_count": len(components) if components else None,
    }


def _run_claasp_import_check(benchmark: Any) -> dict[str, Any]:
    task = benchmark.execution.task
    import claasp  # noqa: F401

    checks: dict[str, Any] = {"claasp_imported": True}
    if task.get("show_solvers"):
        from claasp.cipher_modules.models.utils import set_component_solution  # noqa: F401

        checks["claasp_model_utils_imported"] = True
    return checks


def _run_claasp_cipher_metadata(benchmark: Any) -> dict[str, Any]:
    task = benchmark.execution.task
    parameters = dict(benchmark.challenge.parameters)
    parameters.update(task.get("cipher_parameters", {}))
    build_started = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.challenge.primitive, parameters)
    build_time = round(time.perf_counter() - build_started, 6)
    return {
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {"build_time_seconds": build_time, "solve_time_seconds": None},
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": cipher.__class__.__name__,
            "metadata_source": "CLAASP cipher object",
        },
        "solver_output": {},
    }


def _normalise_status(status: Any) -> str:
    text = str(status or "").lower()
    if "sat" in text and "unsat" not in text:
        return "sat"
    if "unsat" in text:
        return "unsat"
    if "timeout" in text:
        return "timeout"
    if text in {"optimum", "error", "unknown", "skipped"}:
        return text
    return "unknown"


def _compact_solution(solution: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status",
        "solver_name",
        "total_weight",
        "solving_time_seconds",
        "building_time_seconds",
        "memory_megabytes",
        "test_name",
    ]
    return {key: _safe_public_value(solution.get(key)) for key in keys if key in solution}


def _run_claasp_sat_xor_differential_find_one(benchmark: Any, solver_name: str) -> dict[str, Any]:
    from claasp.cipher_modules.models.sat.sat_models.sat_xor_differential_model import SatXorDifferentialModel

    parameters = dict(benchmark.challenge.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.challenge.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = SatXorDifferentialModel(cipher)
    solution = model.find_one_xor_differential_trail(solver_name=solver_name)
    solution = _safe_public_value(solution)
    variables = getattr(model, "_variables_list", None)
    constraints = getattr(model, "_model_constraints", None)
    build_time = solution.get("building_time_seconds")
    solve_time = solution.get("solving_time_seconds")
    return {
        "status": _normalise_status(solution.get("status")),
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": build_time,
            "solve_time_seconds": solve_time,
        },
        "resources": {"peak_memory_mb": solution.get("memory_megabytes")},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": cipher.__class__.__name__,
            "method_name": "SatXorDifferentialModel.find_one_xor_differential_trail",
        },
        "solver_output": _compact_solution(solution),
    }


def _available_solver_rows(benchmark: Any) -> list[dict[str, Any]]:
    family = benchmark.execution.task.get("solver_family") or MODEL_FAMILY_TO_SOLVER_FAMILY.get(
        benchmark.challenge.model_family
    )
    try:
        from claasp.catalog import Catalog

        rows = Catalog().solvers()["rows"]
    except ModuleNotFoundError:
        rows = _fallback_solver_rows()
    if family:
        rows = [row for row in rows if row.get("family") == family]
    source = benchmark.execution.task.get("solver_source")
    if source:
        rows = [row for row in rows if row.get("source") == source]
    if benchmark.execution.task.get("available_only", True):
        rows = [row for row in rows if row.get("available")]
    return rows


def _fallback_solver_rows() -> list[dict[str, Any]]:
    solver_modules = [
        ("sat", "claasp.cipher_modules.models.sat.solvers", "SAT_SOLVERS_INTERNAL", "SAT_SOLVERS_EXTERNAL"),
        ("smt", "claasp.cipher_modules.models.smt.solvers", "SMT_SOLVERS_INTERNAL", "SMT_SOLVERS_EXTERNAL"),
        ("milp", "claasp.cipher_modules.models.milp.solvers", "MILP_SOLVERS_INTERNAL", "MILP_SOLVERS_EXTERNAL"),
        ("cp", "claasp.cipher_modules.models.cp.solvers", "CP_SOLVERS_INTERNAL", "CP_SOLVERS_EXTERNAL"),
    ]
    rows: list[dict[str, Any]] = []
    for family, module_name, internal_name, external_name in solver_modules:
        try:
            module = __import__(module_name, fromlist=[internal_name, external_name])
        except ModuleNotFoundError:
            continue
        for solver in getattr(module, internal_name, []):
            rows.append(_solver_row(family, solver, source="internal"))
        for solver in getattr(module, external_name, []):
            rows.append(_solver_row(family, solver, source="external"))
    return rows


def _solver_row(family: str, solver: dict[str, Any], source: str) -> dict[str, Any]:
    executable = solver.get("keywords", {}).get("command", {}).get("executable")
    return {
        "solver_name": solver.get("solver_name"),
        "solver_brand_name": solver.get("solver_brand_name"),
        "family": family,
        "source": source,
        "executable": executable,
        "available": True if source == "internal" else bool(executable and shutil.which(executable)),
    }


def _run_synthetic(task: dict[str, Any]) -> dict[str, Any]:
    time.sleep(min(float(task.get("synthetic_wall_time_seconds", 0.01)), 0.05))
    return {"synthetic": True}


def _machine_metadata() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "platform": platform.platform(),
        "node": platform.node() or None,
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "usable_cpu_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(),
        "python": platform.python_version(),
    }


def _apply_details(result: dict[str, Any], details: dict[str, Any]) -> None:
    result["status"] = details.get("status", result["status"])
    result["artifacts"]["worker_details"] = details
    result["cipher"].update(details.get("cipher", {}))
    result["timing"].update(details.get("timing", {}))
    result["resources"].update({key: value for key, value in details.get("resources", {}).items() if value is not None})
    result["model"].update(details.get("model", {}))
    result["claasp_output"].update(details.get("claasp_output", {}))
    result["solver_output"].update(details.get("solver_output", {}))


def _finalize_timing(result: dict[str, Any], started: float, start_usage: Any) -> None:
    end_usage = resource.getrusage(resource.RUSAGE_SELF)
    result["timing"]["wall_time_seconds"] = round(time.perf_counter() - started, 6)
    result["timing"]["cpu_time_seconds"] = round(
        (end_usage.ru_utime + end_usage.ru_stime) - (start_usage.ru_utime + start_usage.ru_stime),
        6,
    )
    result["resources"]["peak_memory_mb"] = max(
        result["resources"].get("peak_memory_mb") or 0,
        maxrss_to_mb(end_usage.ru_maxrss),
    )


def run_worker(manifest_path: Path, result_path: Path) -> int:
    with manifest_path.open("r", encoding="utf-8") as handle:
        benchmark = benchmark_from_dict(json.load(handle))
    result = _base_result(benchmark)
    started = time.perf_counter()
    start_usage = resource.getrusage(resource.RUSAGE_SELF)
    task = benchmark.execution.task
    result["execution"]["machine"].update(_machine_metadata())
    task_kind = task.get("kind", "claasp_import_check")
    if benchmark.execution.solver == "all_available" and task_kind == "claasp_sat_xor_differential_find_one":
        expanded_results = []
        for row in _available_solver_rows(benchmark):
            item = _base_result(benchmark)
            item["benchmark_id"] = f"{benchmark.id}_{row.get('solver_name')}"
            item["execution"]["solver"] = row.get("solver_name")
            item["execution"]["machine"].update(_machine_metadata())
            solver_started = time.perf_counter()
            solver_usage = resource.getrusage(resource.RUSAGE_SELF)
            try:
                details = _run_solver_with_timeout(
                    benchmark,
                    row.get("solver_name"),
                    task.get("solver_timeout_seconds"),
                )
                details["solver_output"].update(
                    {
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_available": row.get("available"),
                    }
                )
                _apply_details(item, details)
            except TimeoutError as exc:
                item["status"] = "timeout"
                item["error"] = str(exc)
                item["claasp_output"].update(
                    {
                        "version": _claasp_version(),
                        "method_name": "SatXorDifferentialModel.find_one_xor_differential_trail",
                    }
                )
                item["solver_output"].update(
                    {
                        "solver_name": row.get("solver_name"),
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_available": row.get("available"),
                    }
                )
            except Exception as exc:
                item["status"] = "error"
                item["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                item["claasp_output"].update(
                    {
                        "version": _claasp_version(),
                        "method_name": "SatXorDifferentialModel.find_one_xor_differential_trail",
                    }
                )
                item["solver_output"].update(
                    {
                        "solver_name": row.get("solver_name"),
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_available": row.get("available"),
                    }
                )
            _finalize_timing(item, solver_started, solver_usage)
            expanded_results.append(item)
            result_path.write_text(json.dumps(expanded_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result_path.write_text(json.dumps(expanded_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    try:
        if task_kind == "claasp_import_check":
            details = _run_claasp_import_check(benchmark)
        elif task_kind == "claasp_cipher_metadata":
            details = _run_claasp_cipher_metadata(benchmark)
        elif task_kind == "claasp_sat_xor_differential_find_one":
            details = _run_solver_with_timeout(
                benchmark,
                benchmark.execution.solver,
                task.get("solver_timeout_seconds"),
            )
        elif task_kind == "synthetic":
            details = _run_synthetic(task)
        else:
            raise ValueError(f"unsupported worker task kind: {task_kind}")
        result["status"] = task.get("status", benchmark.execution.expected_status or "sat")
        if isinstance(details, dict):
            _apply_details(result, details)
        result["model"].update(task.get("model", {}))
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    _finalize_timing(result, started, start_usage)
    if benchmark.execution.solver == "all_available":
        rows = _available_solver_rows(benchmark)
        expanded_results = []
        for row in rows:
            item = copy.deepcopy(result)
            item["benchmark_id"] = f"{benchmark.id}_{row.get('solver_name')}"
            item["execution"]["solver"] = row.get("solver_name")
            item["solver_output"].update(
                {
                    "solver_name": row.get("solver_name"),
                    "solver_brand_name": row.get("solver_brand_name"),
                    "solver_family": row.get("family"),
                    "solver_source": row.get("source"),
                    "solver_executable": row.get("executable"),
                    "solver_available": row.get("available"),
                }
            )
            expanded_results.append(item)
        result_payload: Any = expanded_results
    else:
        result_payload = result
    result_path.write_text(json.dumps(result_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    records = result_payload if isinstance(result_payload, list) else [result_payload]
    return 0 if all(record["status"] != "error" for record in records) else 1


def _run_solver_with_timeout(benchmark: Any, solver_name: str, timeout_seconds: Any) -> dict[str, Any]:
    if not timeout_seconds:
        return _run_claasp_sat_xor_differential_find_one(benchmark, solver_name)

    def timeout_handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"solver timed out after {timeout_seconds}s")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))
    try:
        return _run_claasp_sat_xor_differential_find_one(benchmark, solver_name)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m claasp_bench.worker /bench/benchmark.json", file=sys.stderr)
        return 2
    manifest_path = Path(args[0])
    return run_worker(manifest_path, manifest_path.with_name("result.json"))


if __name__ == "__main__":
    raise SystemExit(main())
