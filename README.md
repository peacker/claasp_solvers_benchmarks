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
| `tier` | `smoke` (runs on every push to main), `nightly` (scheduled daily), `fixture` (deterministic, no Docker) |
| `primitive` | Cipher under test (e.g. `Speck-32/64`, `AES-128`, `Ascon`) |
| `primitive_family` | Cipher family — must be one of: `ARX`, `word_based_SPN`, `bit_based_SPN`, `Feistel`, `permutation`, `hash_component` |
| `goal` | Cryptanalytic goal — must be one of: `find_one_trail`, `prove_bound`, `enumerate_trails`, `estimate_probability`, `key_recovery`, `hash_collision` |
| `analysis` | Analysis type — must be one of: `differential`, `linear`, `differential_linear`, `rotational_xor`, `impossible_differential`, `integral` |
| `parameters` | Cipher parameters (`number_of_rounds`, `block_bit_size`, `key_bit_size`, `state_bit_size`, …) |
| `tags` | Free-form labels (e.g. `["smoke", "docker", "claasp"]`) |
| `execution.runner` | `docker` or `synthetic` |
| `execution.solver` | Solver name or `all_available` to sweep every installed solver |
| `execution.timeout_seconds` | Wall-clock timeout for the entire Docker container |
| `execution.solver_timeout_seconds` | Per-solver time limit passed into CLAASP (e.g. CP `timelimit`, or SIGALRM for SAT/MILP/SMT) |
| `execution.kind` | Worker task — must be one of the values in `TAXONOMY["kind"]` in `taxonomy.py` |
| `execution.solver_families` | Solver families to include (e.g. `["sat", "smt", "milp", "cp"]`) |
| `execution.solver_source` | `external` or `internal` |
| `execution.expected_status` | Expected result status (`sat`, `unsat`, `optimum`, …) |

All controlled-vocabulary fields are validated on load against the lists in [`claasp_bench/taxonomy.py`](claasp_bench/taxonomy.py). `primitive` is validated against the `PRIMITIVES` list in the same file — extend it when adding benchmarks for new ciphers.

> **Note:** `model_family` (e.g. `SAT`, `MILP`, `CP_MiniZinc`, `hybrid`) is not stored in benchmark manifests — it is derived at runtime from the actual solver family used and written into each result record for display and filtering on the dashboard.

---

## File naming convention

Every benchmark JSON file must follow this pattern:

```
{primitive}_{analysis}_{task}[_{modifier}]*_{params}_{solver_scope}[_{note}].json
```

| Segment | Position | Description | Allowed values / format |
|---|---|---|---|
| `primitive` | 1 | Lowercase cipher slug | `speck`, `aes`, `ascon`, `present`, `gimli`, … |
| `analysis` | 2 | Cryptanalytic model | `differential`, `linear`, `differential_linear`, `rotational_xor`, `impossible_differential`, `integral` |
| `task` | 3 | What the benchmark does | `find_one`, `find_optimal`, `find_all_fixed_weight`, `enumerate`, `estimate`, `key_recovery`, `hash_collision` |
| `modifier` | 4 (optional, repeatable) | Expected outcome or execution mode | `unsat`, `multicores` |
| `params` | 5 | Primitive instance: rounds + sizes/weight | `r{N}` always required, then any of `b{N}` (block bits), `k{N}` (key bits), `s{N}` (state bits), `w{N}` (fixed weight), all concatenated without separators |
| `solver_scope` | 6 | Target solver family | `sat`, `milp`, `cp`, `smt`, `all_models` |
| `note` | 7 (optional) | Free-form tag for versioning, disambiguation, etc. | any lowercase snake\_case string, e.g. `v2`, `strong_rc`, `seed42` |

All segments are lowercase and separated by underscores. The params segment uses letter-prefixed numbers concatenated without internal separators: `r5b32k64`, `r2s384`, `r3b64k80w1`.

**Task keyword mapping to `goal`:**

| Filename task | JSON `goal` |
|---|---|
| `find_one` | `find_one_trail` |
| `find_optimal` | `prove_bound` |
| `find_all_fixed_weight` | `enumerate_trails` (fixed weight) |
| `enumerate` | `enumerate_trails` (generic) |
| `estimate` | `estimate_probability` |
| `key_recovery` | `key_recovery` |
| `hash_collision` | `hash_collision` |

**Examples:**

| File name | Reads as |
|---|---|
| `speck_differential_find_one_r5b32k64_sat.json` | Speck-32/64 · XOR differential · find one trail · 5 rounds · SAT |
| `aes_linear_find_optimal_r2b128k128_milp.json` | AES-128 · linear · find optimal (prove bound) · 2 rounds · MILP |
| `ascon_differential_find_all_fixed_weight_unsat_r2s320w1_all_models.json` | Ascon · differential · enumerate fixed-weight-1 · expected UNSAT · 2 rounds, 320-bit state · all model families |
| `speck_linear_find_all_fixed_weight_multicores_r2b8k16w1_all_models.json` | Speck-8/16 · linear · enumerate fixed-weight-1 · multi-core · 2 rounds · all model families |
| `speck_differential_find_one_r5b32k64_sat_v2.json` | same as first row, second version (note: `v2`) |

The naming convention is enforced by `python -m claasp_bench validate benchmarks` (run in CI on every push and pull request) and by the unit test `test_benchmark_file_names_follow_naming_convention`.

---

## Adding a new benchmark

**Adding a benchmark requires only one file change.**

Create a JSON file in the appropriate tier directory:

- `benchmarks/smoke/` — runs on every push to `main` (keep fast, ≤ 5 min total)
- `benchmarks/nightly/` — runs on the daily schedule (longer runs OK)
- `benchmarks/fixtures/` — deterministic synthetic fixtures (no Docker, used for validation)

### Example: Speck differential find-one, all solver families

Create `benchmarks/smoke/speck_differential_find_one_r3b32k64_all_models.json`:

```json
{
  "id": "smoke_speck_xor_differential_find_one_r3_all_models",
  "tier": "smoke",
  "primitive": "Speck-32/64",
  "primitive_family": "ARX",
  "goal": "find_one_trail",
  "analysis": "differential",
  "parameters": {
    "number_of_rounds": 3,
    "block_bit_size": 32,
    "key_bit_size": 64
  },
  "tags": ["smoke", "docker", "claasp", "speck"],
  "execution": {
    "runner": "docker",
    "solver": "all_available",
    "claasp_image": "tiicrc/claasp-base:latest",
    "timeout_seconds": 300,
    "memory_mb": 2048,
    "expected_status": "sat",
    "kind": "claasp_xor_differential_find_one",
    "available_only": true,
    "solver_families": ["sat", "smt", "milp", "cp"],
    "solver_source": "external",
    "solver_timeout_seconds": 30
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

- **Primitive metadata**: `primitive`, `primitive_family`, `goal`, `analysis`
- **Cipher**: CLAASP cipher ID, parameter values, component count
- **Execution**: runner, solver, image, timeout, observed thread count
- **Model family**: derived from the actual solver used (e.g. `SAT`, `MILP`, `CP_MiniZinc`); written per result, not stored in the manifest
- **Timing**: wall time, CPU time, build time, solve time
- **Resources**: peak memory (MB)
- **Model**: variable count, constraint/clause count, file size
- **CLAASP output**: version, method name, model-specific fields
- **Solver output**: version, executable, options, command format
- **Artifacts**: Docker stdout/stderr excerpts, worker details

Missing fields are reported as `NA` in the dashboard and Markdown report.
