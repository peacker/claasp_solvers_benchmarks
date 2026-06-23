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

## Continuous Benchmark Site

Every push runs the fixture benchmark suite, generates `results.jsonl`, renders
a Markdown report, and builds the static dashboard. Runs on `main` also deploy
the dashboard with GitHub Pages.

The public site URL is:

```text
https://peacker.github.io/claasp_solvers_benchmarks/
```

Pull requests and non-`main` branch pushes upload the generated site as an
artifact instead of deploying it.

The optional Docker smoke job is manual-only until the repository has access to
a published CLAASP image. To enable it, set the repository variable
`CLAASP_DOCKER_IMAGE` to the image reference to use, then run the workflow with
`workflow_dispatch`.

## Result Storage

Runs append records to `results.jsonl`. The generated site copies those records
to `results.json`, writes `summary.json` and `taxonomy.json`, and serves a
static faceted browser suitable for GitHub Pages.
