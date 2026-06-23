# CLAASP Solver Benchmark Harness

This repository is a manifest-driven benchmark harness for CLAASP solver
experiments. Each benchmark is classified by a challenge taxonomy covering
goal, primitive family, analysis type, model family, difficulty, I/O mode, and
model mode.

## Commands

Validate benchmark definitions:

```bash
python -m claasp_bench validate benchmarks
```

Run deterministic fixture benchmarks for local checks:

```bash
python -m claasp_bench run benchmarks/fixtures --output results --runner synthetic
```

Run the Docker-backed CLAASP smoke benchmark:

```bash
python -m claasp_bench run benchmarks/smoke --output results --runner docker
```

Generate human-readable outputs:

```bash
python -m claasp_bench report results --output results/report.md
python -m claasp_bench site results --output docs
```

The Docker runner expects a local `claasp:latest` image. It mounts this
workspace into the container, sets `PYTHONPATH=/workspace/claasp:/workspace`,
and executes the worker with `sage -python`.

## Result Storage

Runs append records to `results.jsonl`. The generated site copies those records
to `results.json`, writes `summary.json` and `taxonomy.json`, and serves a
static faceted browser suitable for GitHub Pages.
