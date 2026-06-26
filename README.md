# CLAASP Solver Benchmark Harness

Automated cryptanalysis benchmarks for [CLAASP](https://github.com/Crypto-TII/claasp) — a Python/Sage library for the algebraic analysis of symmetric cryptographic primitives.

**Live benchmark dashboard:** https://peacker.github.io/claasp_solvers_benchmarks/

Each benchmark encodes a cryptanalytic challenge (XOR differential/linear trail search, bound proving, trail enumeration) for a specific cipher, then runs a solver sweep across all available SAT, SMT, MILP, and CP (MiniZinc) backends. Results are reported as build time, solve time, peak memory, and model size for every (cipher, model, solver) triple.

---

## Benchmark taxonomy

A benchmark manifest describes:

| Field | Description |
|---|---|
| `id` | Unique stable identifier |
| `tier` | `smoke` (runs on every push to main), `nightly` (scheduled daily), `fixtures` (deterministic, no Docker) |
| `challenge.primitive` | Cipher under test (e.g. `Speck-32/64`, `AES-128`, `Ascon`) |
| `challenge.primitive_family` | Cipher family (`ARX`, `word_based_SPN`, `bit_based_SPN`, `Feistel`, `permutation`, …) |
| `challenge.goal` | `find_one_trail`, `prove_bound`, `enumerate_trails`, `estimate_probability`, … |
| `challenge.analysis` | `differential`, `linear`, `impossible_differential`, … |
| `challenge.model_family` | `SAT`, `SMT`, `MILP`, `CP_MiniZinc`, `hybrid` |
| `challenge.difficulty` | `tutorial`, `benchmark`, `boundary`, `open_challenge` |
| `challenge.parameters` | Cipher parameters (`number_of_rounds`, `block_bit_size`, `key_bit_size`, …) |
| `execution.solver` | Solver name or `all_available` to sweep every installed solver |
| `execution.timeout_seconds` | Wall-clock timeout for the entire Docker run |
| `execution.task.kind` | Worker task (`claasp_xor_differential_find_one`, `claasp_xor_differential_find_lowest_weight`, …) |

---

## Adding a new benchmark

**Adding a benchmark requires only one file change.**

Create a JSON file in the appropriate tier directory:

- `benchmarks/smoke/` — runs on every push to `main` (keep fast, ≤ 5 min total)
- `benchmarks/nightly/` — runs on the daily schedule (longer runs OK)
- `benchmarks/fixtures/` — deterministic synthetic fixtures (no Docker, used for validation)

### Example: new Speck differential find-one benchmark

Create `benchmarks/smoke/speck_find_one_sat.json`:

```json
{
  "id": "smoke_speck32_xor_differential_find_one_sat",
  "tier": "smoke",
  "challenge": {
    "id": "speck32_64_r3_xor_diff_find_one",
    "name": "Speck-32/64 XOR differential find-one (SAT)",
    "primitive": "Speck-32/64",
    "primitive_family": "ARX",
    "goal": "find_one_trail",
    "analysis": "differential",
    "model_family": "SAT",
    "difficulty": "tutorial",
    "parameters": {
      "number_of_rounds": 3,
      "block_bit_size": 32,
      "key_bit_size": 64
    },
    "tags": ["smoke", "docker", "claasp", "speck"]
  },
  "execution": {
    "runner": "docker",
    "solver": "all_available",
    "claasp_image": "tiicrc/claasp-base:latest",
    "timeout_seconds": 300,
    "expected_status": "sat",
    "task": {
      "kind": "claasp_xor_differential_find_one",
      "claasp_method_name": "find_one_xor_differential_trail",
      "status": "sat",
      "available_only": true,
      "solver_families": ["sat", "smt", "milp", "cp"],
      "solver_source": "external",
      "solver_timeout_seconds": 30
    }
  }
}
```

Then open a pull request. CI will validate the manifest, run fixture benchmarks, and generate the dashboard preview. Benchmarks are only re-run when manifests or the Docker image change.

### Validation

Before opening a PR, validate locally:

```bash
python -m claasp_bench validate benchmarks
```

---

## Commands

Validate all benchmark definitions:

```bash
python -m claasp_bench validate benchmarks
```

Run deterministic fixture benchmarks (no Docker required):

```bash
python -m claasp_bench run benchmarks/fixtures --output results --runner synthetic
```

Run the smoke benchmark suite with Docker:

```bash
python -m claasp_bench run benchmarks/smoke --output results --runner docker
```

Generate reports:

```bash
python -m claasp_bench report results --output results/report.md
python -m claasp_bench site results --output _site
```

---

## Docker image

Benchmarks run inside the published CLAASP base image:

```
tiicrc/claasp-base:latest
```

This is the `claasp-base` target from CLAASP's `docker/Dockerfile`. It contains the solver and Sage environment; the CLAASP source tree is mounted at runtime. Override via the `CLAASP_DOCKER_IMAGE` repository variable or environment variable.

Set `CLAASP_SOURCE_DIR` if the CLAASP checkout is not at `./claasp` or `../claasp`.

---

## Continuous benchmark site

Every push validates manifests and runs the fixture suite. Pushes to `main`, scheduled runs, and manual dispatches also execute the Docker-backed smoke sweep. The nightly schedule additionally runs the `benchmarks/nightly/` suite.

**Benchmark results are cached** by a hash of the benchmark manifests and the Docker image digest. If neither has changed since the last run, Docker benchmarks are skipped and the site is regenerated from cached results.

The generated dashboard and results are always uploaded as the `claasp-benchmark-results` workflow artifact.

If the repository is public, pushes to `main` also deploy the dashboard at:

```
https://peacker.github.io/claasp_solvers_benchmarks/
```

Pull requests and non-`main` branch pushes generate a preview artifact instead.

---

## Result schema

Each result record contains:

- **Taxonomy**: primitive, primitive family, goal, analysis, model family, difficulty
- **Cipher**: CLAASP cipher ID, parameter values, component count
- **Execution**: runner, solver, image, timeout, observed thread count
- **Timing**: wall time, CPU time, build time, solve time
- **Resources**: peak memory (MB)
- **Model**: variable count, constraint/clause count, file size
- **CLAASP output**: version, method name, model-specific fields
- **Solver output**: version, executable, options, command format
- **Artifacts**: Docker stdout/stderr excerpts, worker details

Missing fields are reported as `NA` in the dashboard and Markdown report.
