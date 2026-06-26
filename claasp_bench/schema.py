"""Manifest and result schemas for CLAASP benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .taxonomy import RESULT_STATUSES, TAXONOMY


class SchemaError(ValueError):
    """Raised when a benchmark or result record does not match the schema."""


@dataclass(frozen=True)
class Challenge:
    id: str
    name: str
    primitive: str
    primitive_family: str
    goal: str
    analysis: str
    model_family: str
    difficulty: str
    io_mode: str
    model_mode: str
    parameters: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


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
    challenge: Challenge
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
    challenge_data = _require_mapping(data.get("challenge"), "benchmark.challenge")
    execution_data = _require_mapping(data.get("execution"), "benchmark.execution")

    challenge = Challenge(
        id=_require_string(challenge_data, "id", "benchmark.challenge"),
        name=_require_string(challenge_data, "name", "benchmark.challenge"),
        primitive=_require_string(challenge_data, "primitive", "benchmark.challenge"),
        primitive_family=_require_enum(challenge_data, "primitive_family", "benchmark.challenge"),
        goal=_require_enum(challenge_data, "goal", "benchmark.challenge"),
        analysis=_require_enum(challenge_data, "analysis", "benchmark.challenge"),
        model_family=_require_enum(challenge_data, "model_family", "benchmark.challenge"),
        difficulty=_require_enum(challenge_data, "difficulty", "benchmark.challenge"),
        io_mode=challenge_data.get("io_mode", "fixed_io"),
        model_mode=challenge_data.get("model_mode", "fixed_model"),
        parameters=_require_mapping(challenge_data.get("parameters", {}), "benchmark.challenge.parameters"),
        tags=list(challenge_data.get("tags", [])),
    )

    expected_status = _optional_string(execution_data, "expected_status")
    if expected_status is not None and expected_status not in RESULT_STATUSES:
        raise SchemaError(f"execution.expected_status must be one of {', '.join(RESULT_STATUSES)}")

    execution = Execution(
        runner=_require_string(execution_data, "runner", "benchmark.execution"),
        solver=_require_string(execution_data, "solver", "benchmark.execution"),
        claasp_image=execution_data.get("claasp_image", "tiicrc/claasp-base:latest"),
        timeout_seconds=execution_data.get("timeout_seconds", 600),
        memory_mb=_optional_positive_int(execution_data, "memory_mb"),
        seed=execution_data.get("seed"),
        expected_status=expected_status,
        num_threads=_optional_positive_int(execution_data, "num_threads"),
        task=_require_mapping(execution_data.get("task", {}), "benchmark.execution.task"),
    )
    if not isinstance(execution.timeout_seconds, int) or execution.timeout_seconds <= 0:
        raise SchemaError("execution.timeout_seconds must be a positive integer")
    if execution.seed is not None and not isinstance(execution.seed, int):
        raise SchemaError("execution.seed must be an integer when set")

    return Benchmark(
        id=_require_string(data, "id", "benchmark"),
        tier=_require_string(data, "tier", "benchmark"),
        challenge=challenge,
        execution=execution,
        source_path=source_path,
    )


def benchmark_to_dict(benchmark: Benchmark) -> dict[str, Any]:
    return {
        "id": benchmark.id,
        "tier": benchmark.tier,
        "source_path": benchmark.source_path,
        "challenge": benchmark.challenge.__dict__,
        "execution": benchmark.execution.__dict__,
    }


def validate_result(record: dict[str, Any]) -> None:
    required = ["schema_version", "benchmark_id", "challenge", "execution", "status", "timing"]
    for key in required:
        if key not in record:
            raise SchemaError(f"result missing {key}")
    if record["status"] not in RESULT_STATUSES:
        raise SchemaError(f"result.status must be one of {', '.join(RESULT_STATUSES)}")
    _require_mapping(record["challenge"], "result.challenge")
    _require_mapping(record["execution"], "result.execution")
    _require_mapping(record["timing"], "result.timing")
