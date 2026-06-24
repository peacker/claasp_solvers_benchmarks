"""Human-readable benchmark reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .results import load_result_records, summarize


def _fmt_seconds(value: object) -> str:
    return "NA" if value is None else f"{float(value):.3f}s"


def _fmt_value(value: Any) -> str:
    if value is None or value == "":
        return "NA"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, dict):
        if not value:
            return "NA"
        return ", ".join(f"{key}={_fmt_value(item)}" for key, item in sorted(value.items()))
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_value(item) for item in value) + "]"
    return str(value)


def _fmt_memory(value: object) -> str:
    return "NA" if value is None else f"{float(value):.1f} MB"


def _fmt_arch(machine: dict[str, Any]) -> str:
    cpu = machine.get("cpu_model") or machine.get("processor") or machine.get("machine")
    cores = machine.get("usable_cpu_count") or machine.get("cpu_count")
    return f"{_fmt_value(cpu)}; cores={_fmt_value(cores)}; {_fmt_value(machine.get('platform') or machine.get('machine'))}"


def _fmt_cipher_parameters(cipher: dict[str, Any]) -> str:
    parameters = dict(cipher.get("parameters") or {})
    for key in ["number_of_rounds", "block_bit_size", "key_bit_size", "state_bit_size"]:
        value = cipher.get(key)
        if value is not None:
            parameters.setdefault(key, value)
    return _fmt_value(parameters)


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
        "| Benchmark | Primitive | Cipher Parameters | Architecture | CLAASP Method | Goal | Analysis | Model | Solver | Solver Version | Solver Options | Status | Build | Solve | Wall | Memory | Model Size | CLAASP Output | Solver Output | Error | Artifacts |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---|",
    ]
    for record in sorted(records, key=lambda item: item["benchmark_id"]):
        challenge = record["challenge"]
        execution = record["execution"]
        cipher = record.get("cipher", {})
        model = record.get("model", {})
        lines.append(
            "| {benchmark} | {primitive} | {params} | {arch} | {method} | {goal} | {analysis} | {model_family} | {solver} | "
            "{solver_version} | {solver_options} | {status} | {build} | {solve} | {wall} | {memory} | {model_size} | {claasp_output} | {solver_output} | "
            "{error} | {artifacts} |".format(
                benchmark=record["benchmark_id"],
                primitive=challenge["primitive"],
                params=_fmt_cipher_parameters(cipher),
                arch=_fmt_arch(execution.get("machine", {})),
                method=_fmt_value(execution.get("claasp_method")),
                goal=challenge["goal"],
                analysis=challenge["analysis"],
                model_family=challenge["model_family"],
                solver=execution["solver"],
                solver_version=_fmt_value(record.get("solver_output", {}).get("solver_version")),
                solver_options=_fmt_value(
                    {
                        "executable": record.get("solver_output", {}).get("solver_executable"),
                        "options": record.get("solver_output", {}).get("solver_options"),
                        "selector": record.get("solver_output", {}).get("solver_selector"),
                        "format": record.get("solver_output", {}).get("solver_command_format"),
                    }
                ),
                status=record["status"],
                build=_fmt_seconds(record["timing"].get("build_time_seconds")),
                solve=_fmt_seconds(record["timing"].get("solve_time_seconds")),
                wall=_fmt_seconds(record["timing"].get("wall_time_seconds")),
                memory=_fmt_memory(record["resources"].get("peak_memory_mb")),
                model_size=_fmt_value(model),
                claasp_output=_fmt_value(record.get("claasp_output", {})),
                solver_output=_fmt_value(record.get("solver_output", {})),
                error=_fmt_value(record.get("error")),
                artifacts=_fmt_value(record.get("artifacts", {})),
            )
        )
    return "\n".join(lines) + "\n"
