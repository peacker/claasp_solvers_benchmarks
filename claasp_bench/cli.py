"""CLI for CLAASP benchmark runs, reports, and static sites."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import check_file_names, load_benchmarks
from .report import markdown_report
from .results import append_jsonl, summarize, write_json
from .runner import runner_for
from .site import generate_site


def _cmd_validate(args: argparse.Namespace) -> int:
    bad_names = check_file_names(args.path)
    if bad_names:
        for path in bad_names:
            print(f"error: non-standard benchmark file name: {path}", file=sys.stderr)
        print(
            "File names must follow: {primitive}_{analysis}_{task}[_{modifier}]_{solver_scope}.json",
            file=sys.stderr,
        )
        return 1
    benchmarks = load_benchmarks(args.path)
    print(f"Validated {len(benchmarks)} benchmark manifest(s)")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    benchmarks = load_benchmarks(args.path)
    output_dir = args.output.resolve()
    selected_runner = runner_for(args.runner)
    records = []
    for benchmark in benchmarks:
        result = selected_runner.run(benchmark, output_dir)
        if isinstance(result, list):
            records.extend(result)
        else:
            records.append(result)
    append_jsonl(output_dir / "results.jsonl", records)
    write_json(output_dir / "summary.json", summarize(records))
    print(f"Wrote {len(records)} result(s) to {output_dir}")
    if args.fail_on_benchmark_error and any(record["status"] in {"error", "timeout"} for record in records):
        return 1
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    report = markdown_report(args.results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote report to {args.output}")
    else:
        print(report, end="")
    return 0


def _cmd_site(args: argparse.Namespace) -> int:
    generate_site(args.results, args.output)
    print(f"Wrote site to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claasp-bench")
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate", help="validate benchmark manifests")
    validate.add_argument("path", type=Path)
    validate.set_defaults(func=_cmd_validate)

    run = subcommands.add_parser("run", help="run benchmark manifests")
    run.add_argument("path", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--runner", choices=["docker", "synthetic"], default="docker")
    run.add_argument("--fail-on-benchmark-error", action="store_true")
    run.set_defaults(func=_cmd_run)

    report = subcommands.add_parser("report", help="render a Markdown report")
    report.add_argument("results", type=Path)
    report.add_argument("--format", choices=["markdown"], default="markdown")
    report.add_argument("--output", type=Path)
    report.set_defaults(func=_cmd_report)

    site = subcommands.add_parser("site", help="generate a static GitHub Pages site")
    site.add_argument("results", type=Path)
    site.add_argument("--output", type=Path, required=True)
    site.set_defaults(func=_cmd_site)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
