"""Result serialization and aggregation helpers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .schema import validate_result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            validate_result(record)
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False))
            handle.write("\n")


def load_result_records(path: Path) -> list[dict[str, Any]]:
    from .schema import SchemaError
    files = [path] if path.is_file() else sorted(path.rglob("*.jsonl")) + sorted(path.rglob("*.json"))
    records: list[dict[str, Any]] = []
    for file_path in files:
        if file_path.suffix == ".jsonl":
            with file_path.open("r", encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    if line.strip():
                        record = json.loads(line)
                        try:
                            validate_result(record)
                        except SchemaError as exc:
                            print(f"WARNING: skipping invalid record in {file_path}:{lineno}: {exc}")
                            continue
                        records.append(record)
        elif file_path.name != "summary.json":
            with file_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            items = data if isinstance(data, list) else [data]
            for record in items:
                try:
                    validate_result(record)
                except SchemaError as exc:
                    print(f"WARNING: skipping invalid record in {file_path}: {exc}")
                    continue
                records.append(record)
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(record["status"] for record in records)
    durations = [
        record["timing"].get("wall_time_seconds")
        for record in records
        if isinstance(record["timing"].get("wall_time_seconds"), (int, float))
    ]
    fastest = min(
        (record for record in records if isinstance(record["timing"].get("wall_time_seconds"), (int, float))),
        key=lambda record: record["timing"]["wall_time_seconds"],
        default=None,
    )
    grouped: dict[str, dict[str, Any]] = {}
    for field_name in ["primitive", "primitive_family", "goal", "analysis", "model_family", "solver"]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            key = record["execution"].get("solver") if field_name == "solver" else record.get(field_name)
            buckets[str(key)].append(record)
        grouped[field_name] = {
            key: {
                "count": len(items),
                "status_counts": dict(Counter(item["status"] for item in items)),
                "best_wall_time_seconds": min(
                    (
                        item["timing"].get("wall_time_seconds")
                        for item in items
                        if isinstance(item["timing"].get("wall_time_seconds"), (int, float))
                    ),
                    default=None,
                ),
            }
            for key, items in sorted(buckets.items())
        }
    return {
        "count": len(records),
        "status_counts": dict(status_counts),
        "best_wall_time_seconds": min(durations) if durations else None,
        "median_wall_time_seconds": median(durations) if durations else None,
        "fastest_benchmark_id": fastest["benchmark_id"] if fastest else None,
        "groups": grouped,
    }
