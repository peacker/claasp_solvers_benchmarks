"""Container-side benchmark worker."""

from __future__ import annotations

import json
import numbers
import platform
import resource
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .schema import benchmark_from_dict
from .runner import _base_result, maxrss_to_mb


def _safe_public_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
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
    result["execution"]["machine"].update(
        {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "platform": platform.platform(),
            "node": platform.node() or None,
            "python": platform.python_version(),
        }
    )
    try:
        task_kind = task.get("kind", "claasp_import_check")
        if task_kind == "claasp_import_check":
            details = _run_claasp_import_check(benchmark)
        elif task_kind == "claasp_cipher_metadata":
            details = _run_claasp_cipher_metadata(benchmark)
        elif task_kind == "synthetic":
            details = _run_synthetic(task)
        else:
            raise ValueError(f"unsupported worker task kind: {task_kind}")
        result["status"] = task.get("status", benchmark.execution.expected_status or "sat")
        result["artifacts"]["worker_details"] = details
        if isinstance(details, dict):
            result["cipher"].update(details.get("cipher", {}))
            result["timing"].update(details.get("timing", {}))
            result["claasp_output"].update(details.get("claasp_output", {}))
            result["solver_output"].update(details.get("solver_output", {}))
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
