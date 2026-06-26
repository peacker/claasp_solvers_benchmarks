"""Load benchmark manifests from JSON files."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import Benchmark, SchemaError, benchmark_from_dict

# Controlled vocabularies for each filename segment (lowercase).
_ANALYSES = "|".join([
    "differential", "linear", "differential_linear",
    "rotational_xor", "impossible_differential", "integral",
])
_TASKS = "|".join([
    "find_one", "find_optimal", "find_all_fixed_weight",
    "enumerate", "estimate", "key_recovery", "hash_collision",
])
_MODIFIERS = "|".join(["unsat", "multicores"])
_SOLVER_SCOPES = "|".join(["sat", "milp", "cp", "smt", "all_models"])

# Pattern:
#   {primitive}_{analysis}_{task}[_{modifier}]*
#   _r{rounds}[b{block}][k{key}][s{state}][w{weight}]
#   _{solver_scope}[_{note}]
#   .json
#
# The params slot always starts with r{N} (rounds).  Additional size/weight
# dimensions are appended without separator: r5b32k64w1, r2s384, etc.
# The optional trailing note is a free-form snake_case token for versioning,
# tagging, or disambiguation: e.g. _v2, _strong_rc, _seed42.
BENCHMARK_FILE_NAME_RE = re.compile(
    rf"^[a-z][a-z0-9]*"
    rf"_(?:{_ANALYSES})"
    rf"_(?:{_TASKS})"
    rf"(?:_(?:{_MODIFIERS}))*"
    rf"_r\d+(?:[bksw]\d+)*"
    rf"_(?:{_SOLVER_SCOPES})"
    rf"(?:_[a-z][a-z0-9]*(?:_[a-z0-9]+)*)?"
    rf"\.json$"
)


def check_file_names(path: Path) -> list[str]:
    """Return paths of benchmark JSON files whose names violate the naming convention."""
    return [
        str(p)
        for p in iter_manifest_paths(path)
        if not BENCHMARK_FILE_NAME_RE.match(p.name)
    ]


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
