"""Load benchmark manifests from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from .schema import Benchmark, benchmark_from_dict


def iter_manifest_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*.json") if p.is_file())


def load_benchmarks(path: Path) -> list[Benchmark]:
    benchmarks = []
    for manifest_path in iter_manifest_paths(path):
        with manifest_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            benchmarks.extend(benchmark_from_dict(item, str(manifest_path)) for item in data)
        else:
            benchmarks.append(benchmark_from_dict(data, str(manifest_path)))
    return benchmarks
