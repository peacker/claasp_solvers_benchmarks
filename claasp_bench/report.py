"""Human-readable benchmark reports."""

from __future__ import annotations

from pathlib import Path

from .results import load_result_records, summarize


def _fmt_seconds(value: object) -> str:
    return "-" if value is None else f"{float(value):.3f}s"


def markdown_report(results_dir: Path) -> str:
    records = load_result_records(results_dir)
    summary = summarize(records)
    lines = [
        "# CLAASP Benchmark Report",
        "",
        f"Benchmarks: {summary['count']}",
        f"Statuses: {summary['status_counts']}",
        f"Best wall time: {_fmt_seconds(summary['best_wall_time_seconds'])}",
        f"Median wall time: {_fmt_seconds(summary['median_wall_time_seconds'])}",
        "",
        "| Benchmark | Primitive | Family | Goal | Analysis | Model | Solver | Difficulty | Status | Time | Memory |",
        "|---|---|---|---|---|---|---|---|---|---:|---:|",
    ]
    for record in sorted(records, key=lambda item: item["benchmark_id"]):
        challenge = record["challenge"]
        execution = record["execution"]
        memory = record["resources"].get("peak_memory_mb")
        memory_text = "-" if memory is None else f"{float(memory):.1f} MB"
        lines.append(
            "| {benchmark} | {primitive} | {family} | {goal} | {analysis} | {model} | {solver} | "
            "{difficulty} | {status} | {time} | {memory} |".format(
                benchmark=record["benchmark_id"],
                primitive=challenge["primitive"],
                family=challenge["primitive_family"],
                goal=challenge["goal"],
                analysis=challenge["analysis"],
                model=challenge["model_family"],
                solver=execution["solver"],
                difficulty=challenge["difficulty"],
                status=record["status"],
                time=_fmt_seconds(record["timing"].get("wall_time_seconds")),
                memory=memory_text,
            )
        )
    return "\n".join(lines) + "\n"
