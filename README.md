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

The Docker runner uses the published CLAASP base image by default:

```text
tiicrc/claasp-base:latest
```

This is the `claasp-base` target built from CLAASP's `docker/Dockerfile`. It
contains the solver and Sage environment, while the CLAASP source tree is
mounted into the container at runtime. Set `CLAASP_SOURCE_DIR` if the CLAASP
checkout is not at `./claasp` or `../claasp`.

## Continuous Benchmark Site

Every push runs the fixture benchmark suite, generates `results.jsonl`, renders
a Markdown report, and builds the static dashboard. The generated dashboard is
always uploaded as the `claasp-benchmark-results` workflow artifact.

If the repository is public, runs on `main` also deploy the dashboard with
GitHub Pages. The public site URL is:

```text
https://peacker.github.io/claasp_solvers_benchmarks/
```

Private repositories on plans without GitHub Pages support cannot deploy the
site; in that case, use the uploaded workflow artifact. Pull requests and
non-`main` branch pushes also upload the generated site as an artifact instead
of deploying it.

The Docker smoke job uses `tiicrc/claasp-base:latest` by default and checks out
`Crypto-TII/claasp` during CI. Set the repository variable
`CLAASP_DOCKER_IMAGE` only if you want to override the image reference.

## Result Storage

Runs append records to `results.jsonl`. The generated site copies those records
to `results.json`, writes `summary.json` and `taxonomy.json`, and serves a
static faceted browser suitable for GitHub Pages.

Each result records the benchmark taxonomy, CLAASP cipher parameters, execution
architecture, build/solve/wall-clock timings, peak memory, model size fields,
CLAASP metadata, and solver-specific output when available. Missing fields are
reported as `NA` in the human-readable report and dashboard.
