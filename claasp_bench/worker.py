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
import subprocess
import sys
import threading
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
SOLVER_FAMILY_TO_MODEL_FAMILY = {value: key for key, value in MODEL_FAMILY_TO_SOLVER_FAMILY.items()}
SOLVER_FAMILY_TO_METHOD = {
    "sat": "SatXorDifferentialModel.find_one_xor_differential_trail",
    "smt": "SmtXorDifferentialModel.find_one_xor_differential_trail",
    "milp": "MilpXorDifferentialModel.find_one_xor_differential_trail",
    "cp": "MznXorDifferentialModel.find_one_xor_differential_trail",
}
TASK_KIND_TO_METHOD = {
    "claasp_xor_differential_find_one": {
        "sat": "SatXorDifferentialModel.find_one_xor_differential_trail",
        "smt": "SmtXorDifferentialModel.find_one_xor_differential_trail",
        "milp": "MilpXorDifferentialModel.find_one_xor_differential_trail",
        "cp": "MznXorDifferentialModel.find_one_xor_differential_trail",
    },
    "claasp_sat_xor_differential_find_one": {
        "sat": "SatXorDifferentialModel.find_one_xor_differential_trail",
        "smt": "SmtXorDifferentialModel.find_one_xor_differential_trail",
        "milp": "MilpXorDifferentialModel.find_one_xor_differential_trail",
        "cp": "MznXorDifferentialModel.find_one_xor_differential_trail",
    },
    "claasp_xor_differential_enumerate_fixed_weight": {
        "sat": "SatXorDifferentialModel.find_all_xor_differential_trails_with_fixed_weight",
        "smt": "SmtXorDifferentialModel.find_all_xor_differential_trails_with_fixed_weight",
        "milp": "MilpXorDifferentialModel.find_all_xor_differential_trails_with_fixed_weight",
        "cp": "MznXorDifferentialModel.find_all_xor_differential_trails_with_fixed_weight",
    },
    "claasp_sat_xor_differential_enumerate_fixed_weight": {
        "sat": "SatXorDifferentialModel.find_all_xor_differential_trails_with_fixed_weight",
    },
    "claasp_xor_differential_find_lowest_weight": {
        "sat": "SatXorDifferentialModel.find_lowest_weight_xor_differential_trail",
        "smt": "SmtXorDifferentialModel.find_lowest_weight_xor_differential_trail",
        "milp": "MilpXorDifferentialModel.find_lowest_weight_xor_differential_trail",
        "cp": "MznXorDifferentialModel.find_lowest_weight_xor_differential_trail",
    },
    "claasp_xor_linear_find_one": {
        "sat": "SatXorLinearModel.find_one_xor_linear_trail",
        "smt": "SmtXorLinearModel.find_one_xor_linear_trail",
        "milp": "MilpXorLinearModel.find_one_xor_linear_trail",
        "cp": "MznXorLinearModel.find_one_xor_linear_trail",
    },
    "claasp_xor_linear_enumerate_fixed_weight": {
        "sat": "SatXorLinearModel.find_all_xor_linear_trails_with_fixed_weight",
        "smt": "SmtXorLinearModel.find_all_xor_linear_trails_with_fixed_weight",
        "milp": "MilpXorLinearModel.find_all_xor_linear_trails_with_fixed_weight",
        "cp": "MznXorLinearModel.find_all_xor_linear_trails_with_fixed_weight",
    },
    "claasp_xor_linear_find_lowest_weight": {
        "sat": "SatXorLinearModel.find_lowest_weight_xor_linear_trail",
        "smt": "SmtXorLinearModel.find_lowest_weight_xor_linear_trail",
        "milp": "MilpXorLinearModel.find_lowest_weight_xor_linear_trail",
        "cp": "MznXorLinearModel.find_lowest_weight_xor_linear_trail",
    },
}


class _ProcThreadMonitor:
    """Sample child-process thread counts via /proc during a solver run (Linux only)."""

    def __init__(self, interval: float = 0.1) -> None:
        self._interval = interval
        self._max_threads = 1
        self._running = False
        self._thread: threading.Thread | None = None
        self._our_pid = os.getpid()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)

    @property
    def max_threads(self) -> int:
        return self._max_threads

    def _run(self) -> None:
        while self._running:
            try:
                self._scan()
            except Exception:
                pass
            time.sleep(self._interval)

    def _scan(self) -> None:
        proc_dir = Path("/proc")
        if not proc_dir.exists():
            return
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                text = (entry / "status").read_text(encoding="utf-8", errors="ignore")
            except (FileNotFoundError, PermissionError):
                continue
            data: dict[str, str] = {}
            for line in text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    data[k.strip()] = v.strip()
            try:
                if int(data.get("PPid", -1)) == self._our_pid:
                    self._max_threads = max(self._max_threads, int(data.get("Threads", 1)))
            except ValueError:
                pass


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
    if normalized.startswith("aes"):
        from claasp.ciphers.block_ciphers.aes_block_cipher import AESBlockCipher

        kwargs = {
            key: parameters[key]
            for key in ["key_bit_size", "number_of_rounds"]
            if key in parameters
        }
        if "rounds" in parameters and "number_of_rounds" not in kwargs:
            kwargs["number_of_rounds"] = parameters["rounds"]
        try:
            return AESBlockCipher(**kwargs)
        except TypeError:
            # CLAASP < v3.2.1 uses AESBlockCipher(number_of_rounds, word_size, state_size)
            old_kwargs = {k: v for k, v in kwargs.items() if k == "number_of_rounds"}
            return AESBlockCipher(**old_kwargs)
    if normalized.startswith("ascon"):
        from claasp.ciphers.permutations.ascon_permutation import AsconPermutation

        kwargs = {
            key: parameters[key]
            for key in ["number_of_rounds"]
            if key in parameters
        }
        if "rounds" in parameters and "number_of_rounds" not in kwargs:
            kwargs["number_of_rounds"] = parameters["rounds"]
        return AsconPermutation(**kwargs)
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
    parameters = dict(benchmark.parameters)
    parameters.update(task.get("cipher_parameters", {}))
    build_started = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
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
        "building_time",
        "building_time_seconds",
        "memory_megabytes",
        "test_name",
    ]
    return {key: _safe_public_value(solution.get(key)) for key in keys if key in solution}


def _method_name(task_kind: str, solver_family: str | None) -> str | None:
    method_map = TASK_KIND_TO_METHOD.get(task_kind)
    if method_map:
        return method_map.get(solver_family or "sat")
    return SOLVER_FAMILY_TO_METHOD.get(solver_family or "sat")


def _model_class_for_family(solver_family: str | None) -> tuple[Any, str]:
    if solver_family == "smt":
        from claasp.cipher_modules.models.smt.smt_models.smt_xor_differential_model import SmtXorDifferentialModel

        return SmtXorDifferentialModel, "SmtXorDifferentialModel"
    if solver_family == "milp":
        from claasp.cipher_modules.models.milp.milp_models.milp_xor_differential_model import MilpXorDifferentialModel

        return MilpXorDifferentialModel, "MilpXorDifferentialModel"
    if solver_family == "cp":
        from claasp.cipher_modules.models.cp.mzn_models.mzn_xor_differential_model import MznXorDifferentialModel

        return MznXorDifferentialModel, "MznXorDifferentialModel"
    from claasp.cipher_modules.models.sat.sat_models.sat_xor_differential_model import SatXorDifferentialModel

    return SatXorDifferentialModel, "SatXorDifferentialModel"


def _linear_model_class_for_family(solver_family: str | None) -> tuple[Any, str]:
    if solver_family == "smt":
        from claasp.cipher_modules.models.smt.smt_models.smt_xor_linear_model import SmtXorLinearModel

        return SmtXorLinearModel, "SmtXorLinearModel"
    if solver_family == "milp":
        from claasp.cipher_modules.models.milp.milp_models.milp_xor_linear_model import MilpXorLinearModel

        return MilpXorLinearModel, "MilpXorLinearModel"
    if solver_family == "cp":
        from claasp.cipher_modules.models.cp.mzn_models.mzn_xor_linear_model import MznXorLinearModel

        return MznXorLinearModel, "MznXorLinearModel"
    from claasp.cipher_modules.models.sat.sat_models.sat_xor_linear_model import SatXorLinearModel

    return SatXorLinearModel, "SatXorLinearModel"


def _solver_metadata_for(benchmark: Any, solver_name: str, solver_family: str | None) -> dict[str, Any]:
    rows = _available_solver_rows(benchmark)
    for row in rows:
        if row.get("solver_name") == solver_name and (solver_family is None or row.get("family") == solver_family):
            return {
                "solver_name": row.get("solver_name"),
                "solver_brand_name": row.get("solver_brand_name"),
                "solver_family": row.get("family"),
                "solver_source": row.get("source"),
                "solver_executable": row.get("executable"),
                "solver_options": row.get("options"),
                "solver_selector": row.get("solver_selector"),
                "solver_command_format": row.get("command_format"),
                "solver_version": row.get("version"),
                "solver_available": row.get("available"),
            }
    return {}


def _run_claasp_sat_xor_differential_find_one(benchmark: Any, solver_name: str) -> dict[str, Any]:
    from claasp.cipher_modules.models.sat.sat_models.sat_xor_differential_model import SatXorDifferentialModel

    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
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


def _run_claasp_sat_xor_differential_enumerate_fixed_weight(
    benchmark: Any, solver_name: str
) -> dict[str, Any]:
    from claasp.cipher_modules.models.sat.sat_models.sat_xor_differential_model import SatXorDifferentialModel

    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    fixed_weight = int(benchmark.execution.task.get("fixed_weight", parameters.get("weight", 0)))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = SatXorDifferentialModel(cipher)
    started = time.perf_counter()
    solutions = model.find_all_xor_differential_trails_with_fixed_weight(fixed_weight, solver_name=solver_name)
    enumeration_time = round(time.perf_counter() - started, 6)
    solutions = _safe_public_value(solutions)
    variables = getattr(model, "_variables_list", None)
    constraints = getattr(model, "_model_constraints", None)
    first_solution = solutions[0] if solutions else {}
    build_time = first_solution.get("building_time_seconds") if isinstance(first_solution, dict) else None
    solve_times = [
        solution.get("solving_time_seconds")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("solving_time_seconds"), numbers.Real)
    ]
    memories = [
        solution.get("memory_megabytes")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("memory_megabytes"), numbers.Real)
    ]
    return {
        "status": "sat" if solutions else "unsat",
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": build_time,
            "solve_time_seconds": sum(solve_times) if solve_times else None,
            "enumeration_time_seconds": enumeration_time,
        },
        "resources": {"peak_memory_mb": max(memories) if memories else None},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": cipher.__class__.__name__,
            "method_name": TASK_KIND_TO_METHOD["claasp_sat_xor_differential_enumerate_fixed_weight"],
        },
        "solver_output": {
            "enumerated_trails": len(solutions),
            "fixed_weight": fixed_weight,
            "first_solution": _compact_solution(first_solution) if isinstance(first_solution, dict) else {},
        },
    }


def _run_claasp_smt_xor_differential_find_one(benchmark: Any, solver_name: str) -> dict[str, Any]:
    from claasp.cipher_modules.models.smt.smt_models.smt_xor_differential_model import SmtXorDifferentialModel

    return _run_find_one_with_model(
        benchmark,
        solver_name,
        SmtXorDifferentialModel,
        "SmtXorDifferentialModel.find_one_xor_differential_trail",
    )


def _run_claasp_milp_xor_differential_find_one(benchmark: Any, solver_name: str) -> dict[str, Any]:
    from claasp.cipher_modules.models.milp.milp_models.milp_xor_differential_model import MilpXorDifferentialModel

    return _run_find_one_with_model(
        benchmark,
        solver_name,
        MilpXorDifferentialModel,
        "MilpXorDifferentialModel.find_one_xor_differential_trail",
    )


def _run_claasp_cp_xor_differential_find_one(benchmark: Any, solver_name: str) -> dict[str, Any]:
    from claasp.cipher_modules.models.cp.mzn_models.mzn_xor_differential_model import MznXorDifferentialModel

    return _run_find_one_with_model(
        benchmark,
        solver_name,
        MznXorDifferentialModel,
        "MznXorDifferentialModel.find_one_xor_differential_trail",
        timelimit=benchmark.execution.task.get("solver_timeout_seconds"),
    )


def _run_find_one_with_model(
    benchmark: Any,
    solver_name: str,
    model_class: Any,
    method_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    call_start = time.perf_counter()
    solution = model.find_one_xor_differential_trail(solver_name=solver_name, **kwargs)
    call_elapsed = time.perf_counter() - call_start
    solution = _safe_public_value(solution)
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    build_time = solution.get("building_time_seconds", solution.get("building_time"))
    solve_time = solution.get("solving_time_seconds")
    if solve_time is None and build_time is not None:
        # Estimate solve time as total call time minus model build time
        solve_time = round(max(0.0, call_elapsed - build_time), 6)
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
            "method_name": method_name,
        },
        "solver_output": _compact_solution(solution),
    }


def _run_claasp_xor_differential_find_one(benchmark: Any, solver_name: str, solver_family: str | None) -> dict[str, Any]:
    if solver_family == "smt":
        return _run_claasp_smt_xor_differential_find_one(benchmark, solver_name)
    if solver_family == "milp":
        return _run_claasp_milp_xor_differential_find_one(benchmark, solver_name)
    if solver_family == "cp":
        return _run_claasp_cp_xor_differential_find_one(benchmark, solver_name)
    return _run_claasp_sat_xor_differential_find_one(benchmark, solver_name)


def _run_claasp_xor_differential_enumerate_fixed_weight(
    benchmark: Any, solver_name: str, solver_family: str | None
) -> dict[str, Any]:
    model_class, class_name = _model_class_for_family(solver_family)
    method_name = _method_name("claasp_xor_differential_enumerate_fixed_weight", solver_family)
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    fixed_weight = int(benchmark.execution.task.get("fixed_weight", parameters.get("weight", 0)))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    kwargs: dict[str, Any] = {}
    if solver_family == "cp":
        kwargs["timelimit"] = benchmark.execution.task.get("solver_timeout_seconds")
    started = time.perf_counter()
    solutions = model.find_all_xor_differential_trails_with_fixed_weight(
        fixed_weight, solver_name=solver_name, **kwargs
    )
    enumeration_time = round(time.perf_counter() - started, 6)
    solutions = _safe_public_value(solutions)
    if isinstance(solutions, dict):
        solutions = [solutions]
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    first_solution = solutions[0] if solutions else {}
    solve_times = [
        solution.get("solving_time_seconds")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("solving_time_seconds"), numbers.Real)
    ]
    memories = [
        solution.get("memory_megabytes")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("memory_megabytes"), numbers.Real)
    ]
    build_time = first_solution.get("building_time_seconds", first_solution.get("building_time")) if isinstance(first_solution, dict) else None
    return {
        "status": "sat" if solutions else "unsat",
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": build_time,
            "solve_time_seconds": sum(solve_times) if solve_times else None,
            "enumeration_time_seconds": enumeration_time,
        },
        "resources": {"peak_memory_mb": max(memories) if memories else None},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": class_name,
            "method_name": method_name,
        },
        "solver_output": {
            "enumerated_trails": len(solutions),
            "fixed_weight": fixed_weight,
            "first_solution": _compact_solution(first_solution) if isinstance(first_solution, dict) else {},
        },
    }


def _run_claasp_xor_differential_find_lowest_weight(
    benchmark: Any, solver_name: str, solver_family: str | None
) -> dict[str, Any]:
    model_class, class_name = _model_class_for_family(solver_family)
    method_name = _method_name("claasp_xor_differential_find_lowest_weight", solver_family)
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    kwargs: dict[str, Any] = {}
    if solver_family == "cp":
        kwargs["timelimit"] = benchmark.execution.task.get("solver_timeout_seconds")
    solution = model.find_lowest_weight_xor_differential_trail(solver_name=solver_name, **kwargs)
    solution = _safe_public_value(solution)
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    return {
        "status": _normalise_status(solution.get("status")),
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": solution.get("building_time_seconds", solution.get("building_time")),
            "solve_time_seconds": solution.get("solving_time_seconds"),
            "proof_time_seconds": solution.get("solving_time_seconds"),
        },
        "resources": {"peak_memory_mb": solution.get("memory_megabytes")},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": class_name,
            "method_name": method_name,
        },
        "solver_output": _compact_solution(solution),
    }


def _linear_solver_kwargs(benchmark: Any, solver_family: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if solver_family == "cp":
        kwargs["timelimit"] = benchmark.execution.task.get("solver_timeout_seconds")
    return kwargs


def _run_claasp_xor_linear_find_one(benchmark: Any, solver_name: str, solver_family: str | None) -> dict[str, Any]:
    model_class, class_name = _linear_model_class_for_family(solver_family)
    method_name = _method_name("claasp_xor_linear_find_one", solver_family)
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    solution = model.find_one_xor_linear_trail(solver_name=solver_name, **_linear_solver_kwargs(benchmark, solver_family))
    solution = _safe_public_value(solution)
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    return {
        "status": _normalise_status(solution.get("status")),
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": solution.get("building_time_seconds", solution.get("building_time")),
            "solve_time_seconds": solution.get("solving_time_seconds"),
        },
        "resources": {"peak_memory_mb": solution.get("memory_megabytes")},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": class_name,
            "method_name": method_name,
        },
        "solver_output": _compact_solution(solution),
    }


def _run_claasp_xor_linear_enumerate_fixed_weight(
    benchmark: Any, solver_name: str, solver_family: str | None
) -> dict[str, Any]:
    model_class, class_name = _linear_model_class_for_family(solver_family)
    method_name = _method_name("claasp_xor_linear_enumerate_fixed_weight", solver_family)
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    fixed_weight = int(benchmark.execution.task.get("fixed_weight", parameters.get("weight", 0)))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    started = time.perf_counter()
    solutions = model.find_all_xor_linear_trails_with_fixed_weight(
        fixed_weight, solver_name=solver_name, **_linear_solver_kwargs(benchmark, solver_family)
    )
    enumeration_time = round(time.perf_counter() - started, 6)
    solutions = _safe_public_value(solutions)
    if isinstance(solutions, dict):
        solutions = [solutions]
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    first_solution = solutions[0] if solutions else {}
    solve_times = [
        solution.get("solving_time_seconds")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("solving_time_seconds"), numbers.Real)
    ]
    memories = [
        solution.get("memory_megabytes")
        for solution in solutions
        if isinstance(solution, dict) and isinstance(solution.get("memory_megabytes"), numbers.Real)
    ]
    build_time = (
        first_solution.get("building_time_seconds", first_solution.get("building_time"))
        if isinstance(first_solution, dict)
        else None
    )
    return {
        "status": "sat" if solutions else "unsat",
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": build_time,
            "solve_time_seconds": sum(solve_times) if solve_times else None,
            "enumeration_time_seconds": enumeration_time,
        },
        "resources": {"peak_memory_mb": max(memories) if memories else None},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": class_name,
            "method_name": method_name,
        },
        "solver_output": {
            "enumerated_trails": len(solutions),
            "fixed_weight": fixed_weight,
            "first_solution": _compact_solution(first_solution) if isinstance(first_solution, dict) else {},
        },
    }


def _run_claasp_xor_linear_find_lowest_weight(
    benchmark: Any, solver_name: str, solver_family: str | None
) -> dict[str, Any]:
    model_class, class_name = _linear_model_class_for_family(solver_family)
    method_name = _method_name("claasp_xor_linear_find_lowest_weight", solver_family)
    parameters = dict(benchmark.parameters)
    parameters.update(benchmark.execution.task.get("cipher_parameters", {}))
    cipher_start = time.perf_counter()
    cipher = _instantiate_cipher(benchmark.primitive, parameters)
    cipher_build_time = round(time.perf_counter() - cipher_start, 6)
    model = model_class(cipher)
    solution = model.find_lowest_weight_xor_linear_trail(
        solver_name=solver_name, **_linear_solver_kwargs(benchmark, solver_family)
    )
    solution = _safe_public_value(solution)
    variables = getattr(model, "_variables_list", None) or getattr(model, "_variables_declarations", None)
    constraints = getattr(model, "_model_constraints", None)
    return {
        "status": _normalise_status(solution.get("status")),
        "cipher": _cipher_metadata(cipher, parameters),
        "timing": {
            "cipher_build_time_seconds": cipher_build_time,
            "build_time_seconds": solution.get("building_time_seconds", solution.get("building_time")),
            "solve_time_seconds": solution.get("solving_time_seconds"),
            "proof_time_seconds": solution.get("solving_time_seconds"),
        },
        "resources": {"peak_memory_mb": solution.get("memory_megabytes")},
        "model": {
            "variables": len(variables) if variables is not None else None,
            "constraints": len(constraints) if constraints is not None else None,
        },
        "claasp_output": {
            "version": _claasp_version(),
            "cipher_class": class_name,
            "method_name": method_name,
        },
        "solver_output": _compact_solution(solution),
    }


def _available_solver_rows(benchmark: Any) -> list[dict[str, Any]]:
    families = benchmark.execution.task.get("solver_families")
    family = benchmark.execution.task.get("solver_family")
    try:
        from claasp.catalog import Catalog

        rows = _merge_solver_metadata(Catalog().solvers()["rows"])
    except ModuleNotFoundError:
        rows = _fallback_solver_rows()
    if families:
        rows = [row for row in rows if row.get("family") in families]
    elif family:
        rows = [row for row in rows if row.get("family") == family]
    source = benchmark.execution.task.get("solver_source")
    if source:
        rows = [row for row in rows if row.get("source") == source]
    if benchmark.execution.task.get("available_only", True):
        rows = [row for row in rows if row.get("available")]
    return rows


def _merge_solver_metadata(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback_by_key = {(row.get("family"), row.get("solver_name")): row for row in _fallback_solver_rows()}
    merged = []
    for row in rows:
        details = fallback_by_key.get((row.get("family"), row.get("solver_name")), {})
        item = dict(details)
        item.update({key: value for key, value in row.items() if value is not None})
        merged.append(item)
    return merged


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
    command = solver.get("keywords", {}).get("command", {})
    executable = command.get("executable")
    executables = executable if isinstance(executable, list) else [executable]
    available = any(shutil.which(item) for item in executables if item)
    options = command.get("options")
    solver_selector = command.get("solver")
    return {
        "solver_name": solver.get("solver_name"),
        "solver_brand_name": solver.get("solver_brand_name"),
        "family": family,
        "source": source,
        "executable": _safe_public_value(executable),
        "options": _safe_public_value(options),
        "solver_selector": _safe_public_value(solver_selector),
        "command_format": _safe_public_value(command.get("format")),
        "version": _solver_version(executables),
        "available": True if source == "internal" else available,
    }


def _solver_version(executables: list[Any]) -> str | None:
    executable = next((item for item in executables if isinstance(item, str) and shutil.which(item)), None)
    if not executable:
        return None
    for args in ([executable, "--version"], [executable, "-version"], [executable, "-v"]):
        try:
            completed = subprocess.run(args, check=False, text=True, capture_output=True, timeout=2)
        except Exception:
            continue
        text = (completed.stdout or completed.stderr).strip()
        if completed.returncode == 0 and text:
            return text.splitlines()[0][:240]
    return None


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


def _monitor_solver(
    benchmark: Any,
    solver_name: str,
    solver_family: str | None,
    timeout_seconds: Any,
) -> tuple[dict[str, Any], int]:
    """Run a solver with thread monitoring; return (details, max_threads)."""
    monitor = _ProcThreadMonitor()
    monitor.start()
    try:
        details = _run_solver_with_timeout(benchmark, solver_name, solver_family, timeout_seconds)
    finally:
        monitor.stop()
    return details, monitor.max_threads


def _apply_details(result: dict[str, Any], details: dict[str, Any]) -> None:
    result["status"] = details.get("status", result["status"])
    result["artifacts"]["worker_details"] = details
    result["cipher"].update(details.get("cipher", {}))
    result["timing"].update(details.get("timing", {}))
    result["resources"].update({key: value for key, value in details.get("resources", {}).items() if value is not None})
    result["model"].update(details.get("model", {}))
    result["claasp_output"].update(details.get("claasp_output", {}))
    result["solver_output"].update(details.get("solver_output", {}))
    if "observed_threads" in details:
        result["execution"]["observed_threads"] = details["observed_threads"]


def _finalize_timing(result: dict[str, Any], started: float, start_usage: Any) -> None:
    end_usage = resource.getrusage(resource.RUSAGE_SELF)
    result["timing"]["wall_time_seconds"] = round(time.perf_counter() - started, 6)
    result["timing"]["cpu_time_seconds"] = round(
        (end_usage.ru_utime + end_usage.ru_stime) - (start_usage.ru_utime + start_usage.ru_stime),
        6,
    )
    current_peak = result["resources"].get("peak_memory_mb")
    if not isinstance(current_peak, numbers.Real):
        current_peak = 0
    result["resources"]["peak_memory_mb"] = max(
        current_peak or 0,
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
    if benchmark.execution.solver == "all_available" and task_kind in TASK_KIND_TO_METHOD:
        expanded_results = []
        for row in _available_solver_rows(benchmark):
            solver_family = row.get("family")
            item = _base_result(benchmark)
            item["benchmark_id"] = f"{benchmark.id}_{solver_family}_{row.get('solver_name')}"
            item["model_family"] = SOLVER_FAMILY_TO_MODEL_FAMILY.get(solver_family)
            item["execution"]["solver"] = row.get("solver_name")
            item["execution"]["claasp_method"] = _method_name(task_kind, solver_family)
            item["execution"]["machine"].update(_machine_metadata())
            solver_started = time.perf_counter()
            solver_usage = resource.getrusage(resource.RUSAGE_SELF)
            try:
                details, observed_threads = _monitor_solver(
                    benchmark,
                    row.get("solver_name"),
                    solver_family,
                    task.get("solver_timeout_seconds"),
                )
                details["observed_threads"] = observed_threads
                details["solver_output"].update(
                    {
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_options": row.get("options"),
                        "solver_selector": row.get("solver_selector"),
                        "solver_command_format": row.get("command_format"),
                        "solver_version": row.get("version"),
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
                        "method_name": _method_name(task_kind, solver_family),
                    }
                )
                item["solver_output"].update(
                    {
                        "solver_name": row.get("solver_name"),
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_options": row.get("options"),
                        "solver_selector": row.get("solver_selector"),
                        "solver_command_format": row.get("command_format"),
                        "solver_version": row.get("version"),
                        "solver_available": row.get("available"),
                    }
                )
            except Exception as exc:
                item["status"] = "error"
                item["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                item["claasp_output"].update(
                    {
                        "version": _claasp_version(),
                        "method_name": _method_name(task_kind, solver_family),
                    }
                )
                item["solver_output"].update(
                    {
                        "solver_name": row.get("solver_name"),
                        "solver_brand_name": row.get("solver_brand_name"),
                        "solver_family": row.get("family"),
                        "solver_source": row.get("source"),
                        "solver_executable": row.get("executable"),
                        "solver_options": row.get("options"),
                        "solver_selector": row.get("solver_selector"),
                        "solver_command_format": row.get("command_format"),
                        "solver_version": row.get("version"),
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
            details, observed_threads = _monitor_solver(
                benchmark,
                benchmark.execution.solver,
                (task.get("solver_families") or [None])[0],
                task.get("solver_timeout_seconds"),
            )
            details["observed_threads"] = observed_threads
        elif task_kind in {
            "claasp_sat_xor_differential_enumerate_fixed_weight",
            "claasp_xor_differential_enumerate_fixed_weight",
            "claasp_xor_differential_find_lowest_weight",
            "claasp_xor_linear_find_one",
            "claasp_xor_linear_enumerate_fixed_weight",
            "claasp_xor_linear_find_lowest_weight",
        }:
            details, observed_threads = _monitor_solver(
                benchmark,
                benchmark.execution.solver,
                (task.get("solver_families") or ["sat"])[0],
                task.get("solver_timeout_seconds"),
            )
            details["observed_threads"] = observed_threads
        elif task_kind == "synthetic":
            details = _run_synthetic(task)
        else:
            raise ValueError(f"unsupported worker task kind: {task_kind}")
        result["status"] = benchmark.execution.expected_status or "sat"
        if isinstance(details, dict):
            _apply_details(result, details)
            result["solver_output"].update(
                _solver_metadata_for(
                    benchmark,
                    benchmark.execution.solver,
                    (task.get("solver_families") or [None])[0],
                )
            )
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
            item["benchmark_id"] = f"{benchmark.id}_{row.get('family')}_{row.get('solver_name')}"
            item["model_family"] = SOLVER_FAMILY_TO_MODEL_FAMILY.get(row.get("family"))
            item["execution"]["solver"] = row.get("solver_name")
            item["execution"]["claasp_method"] = _method_name(task_kind, row.get("family"))
            item["solver_output"].update(
                {
                    "solver_name": row.get("solver_name"),
                    "solver_brand_name": row.get("solver_brand_name"),
                    "solver_family": row.get("family"),
                    "solver_source": row.get("source"),
                    "solver_executable": row.get("executable"),
                    "solver_options": row.get("options"),
                    "solver_selector": row.get("solver_selector"),
                    "solver_command_format": row.get("command_format"),
                    "solver_version": row.get("version"),
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


def _run_solver_with_timeout(
    benchmark: Any, solver_name: str, solver_family: str | None, timeout_seconds: Any
) -> dict[str, Any]:
    if not timeout_seconds:
        return _run_solver_task(benchmark, solver_name, solver_family)

    def timeout_handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"solver timed out after {timeout_seconds}s")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))
    try:
        return _run_solver_task(benchmark, solver_name, solver_family)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def _run_solver_task(benchmark: Any, solver_name: str, solver_family: str | None) -> dict[str, Any]:
    task_kind = benchmark.execution.task.get("kind")
    if task_kind == "claasp_sat_xor_differential_enumerate_fixed_weight":
        return _run_claasp_sat_xor_differential_enumerate_fixed_weight(benchmark, solver_name)
    if task_kind == "claasp_xor_differential_enumerate_fixed_weight":
        return _run_claasp_xor_differential_enumerate_fixed_weight(benchmark, solver_name, solver_family)
    if task_kind == "claasp_xor_differential_find_lowest_weight":
        return _run_claasp_xor_differential_find_lowest_weight(benchmark, solver_name, solver_family)
    if task_kind == "claasp_xor_linear_find_one":
        return _run_claasp_xor_linear_find_one(benchmark, solver_name, solver_family)
    if task_kind == "claasp_xor_linear_enumerate_fixed_weight":
        return _run_claasp_xor_linear_enumerate_fixed_weight(benchmark, solver_name, solver_family)
    if task_kind == "claasp_xor_linear_find_lowest_weight":
        return _run_claasp_xor_linear_find_lowest_weight(benchmark, solver_name, solver_family)
    return _run_claasp_xor_differential_find_one(benchmark, solver_name, solver_family)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m claasp_bench.worker /bench/benchmark.json", file=sys.stderr)
        return 2
    manifest_path = Path(args[0])
    return run_worker(manifest_path, manifest_path.with_name("result.json"))


if __name__ == "__main__":
    raise SystemExit(main())
