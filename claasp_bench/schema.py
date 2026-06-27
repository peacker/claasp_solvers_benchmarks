"""Manifest and result schemas for CLAASP benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .taxonomy import RESULT_STATUSES, TAXONOMY

# Keys from the flat execution object that belong to the task context.
# Any unrecognised key in execution is silently ignored.
_TASK_KEYS = frozenset({
    "kind",
    "solver_timeout_seconds",
    "available_only",
    "solver_families",
    "solver_family",
    "solver_source",
    "fixed_weight",
    "show_solvers",
    "cipher_parameters",
    "synthetic_wall_time_seconds",
    "synthetic_build_time_seconds",
    "synthetic_solve_time_seconds",
    "model",
    "solver_output",
})


class SchemaError(ValueError):
    """Raised when a benchmark or result record does not match the schema."""


@dataclass(frozen=True)
class Execution:
    runner: str
    solver: str
    claasp_image: str = "tiicrc/claasp-base:latest"
    timeout_seconds: int = 600
    memory_mb: int | None = None
    seed: int | None = None
    expected_status: str | None = None
    num_threads: int | None = None
    task: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Benchmark:
    id: str
    tier: str
    primitive: str
    primitive_family: str
    goal: str
    analysis: str
    parameters: dict[str, Any]
    tags: list[str]
    execution: Execution
    source_path: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require_mapping(data: Any, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError(f"{context} must be an object")
    return data


def _require_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{context}.{key} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{key} must be a non-empty string when set")
    return value


def _require_enum(data: dict[str, Any], key: str, context: str) -> str:
    value = _require_string(data, key, context)
    allowed = TAXONOMY[key]
    if value not in allowed:
        raise SchemaError(f"{context}.{key} must be one of {', '.join(allowed)}")
    return value


def _optional_positive_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise SchemaError(f"{key} must be a positive integer when set")
    return value


def benchmark_from_dict(data: dict[str, Any], source_path: str | None = None) -> Benchmark:
    data = _require_mapping(data, "benchmark")
    execution_data = _require_mapping(data.get("execution"), "benchmark.execution")

    primitive_family = _require_enum(data, "primitive_family", "benchmark")
    goal = _require_enum(data, "goal", "benchmark")
    analysis = _require_enum(data, "analysis", "benchmark")

    expected_status = _optional_string(execution_data, "expected_status")
    if expected_status is not None and expected_status not in RESULT_STATUSES:
        raise SchemaError(f"execution.expected_status must be one of {', '.join(RESULT_STATUSES)}")

    runner = _require_string(execution_data, "runner", "benchmark.execution")
    if runner not in TAXONOMY["runner"]:
        raise SchemaError(f"benchmark.execution.runner must be one of {', '.join(TAXONOMY['runner'])}")

    # task dict is built from the flat execution-level keys
    task = {k: v for k, v in execution_data.items() if k in _TASK_KEYS}

    kind = task.get("kind", "claasp_import_check")
    if kind not in TAXONOMY["kind"]:
        raise SchemaError(f"benchmark.execution.kind must be one of {', '.join(TAXONOMY['kind'])}")

    for fam in task.get("solver_families", []):
        if fam not in TAXONOMY["solver_family"]:
            raise SchemaError(
                f"benchmark.execution.solver_families: {fam!r} must be one of {', '.join(TAXONOMY['solver_family'])}"
            )

    solver_source = task.get("solver_source")
    if solver_source is not None and solver_source not in TAXONOMY["solver_source"]:
        raise SchemaError(
            f"benchmark.execution.solver_source must be one of {', '.join(TAXONOMY['solver_source'])}"
        )

    execution = Execution(
        runner=runner,
        solver=_require_string(execution_data, "solver", "benchmark.execution"),
        claasp_image=execution_data.get("claasp_image", "tiicrc/claasp-base:latest"),
        timeout_seconds=execution_data.get("timeout_seconds", 600),
        memory_mb=_optional_positive_int(execution_data, "memory_mb"),
        seed=execution_data.get("seed"),
        expected_status=expected_status,
        num_threads=_optional_positive_int(execution_data, "num_threads"),
        task=task,
    )
    if not isinstance(execution.timeout_seconds, int) or execution.timeout_seconds <= 0:
        raise SchemaError("execution.timeout_seconds must be a positive integer")
    if execution.seed is not None and not isinstance(execution.seed, int):
        raise SchemaError("execution.seed must be an integer when set")

    return Benchmark(
        id=_require_string(data, "id", "benchmark"),
        tier=_require_string(data, "tier", "benchmark"),
        primitive=_require_string(data, "primitive", "benchmark"),
        primitive_family=primitive_family,
        goal=goal,
        analysis=analysis,
        parameters=_require_mapping(data.get("parameters", {}), "benchmark.parameters"),
        tags=list(data.get("tags", [])),
        execution=execution,
        source_path=source_path,
    )


def benchmark_to_dict(benchmark: Benchmark) -> dict[str, Any]:
    execution_dict: dict[str, Any] = {
        "runner": benchmark.execution.runner,
        "solver": benchmark.execution.solver,
        "claasp_image": benchmark.execution.claasp_image,
        "timeout_seconds": benchmark.execution.timeout_seconds,
        "memory_mb": benchmark.execution.memory_mb,
        "seed": benchmark.execution.seed,
        "expected_status": benchmark.execution.expected_status,
        "num_threads": benchmark.execution.num_threads,
    }
    execution_dict.update(benchmark.execution.task)
    return {
        "id": benchmark.id,
        "tier": benchmark.tier,
        "source_path": benchmark.source_path,
        "primitive": benchmark.primitive,
        "primitive_family": benchmark.primitive_family,
        "goal": benchmark.goal,
        "analysis": benchmark.analysis,
        "parameters": dict(benchmark.parameters),
        "tags": list(benchmark.tags),
        "execution": execution_dict,
    }


def validate_result(record: dict[str, Any]) -> None:
    required = ["schema_version", "benchmark_id", "primitive", "execution", "status", "timing"]
    for key in required:
        if key not in record:
            raise SchemaError(f"result missing {key}")
    if record["status"] not in RESULT_STATUSES:
        raise SchemaError(f"result.status must be one of {', '.join(RESULT_STATUSES)}")
    _require_mapping(record["execution"], "result.execution")
    _require_mapping(record["timing"], "result.timing")
