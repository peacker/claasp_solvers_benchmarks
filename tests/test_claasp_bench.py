from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from claasp_bench.cli import main
from claasp_bench.loader import BENCHMARK_FILE_NAME_RE, check_file_names, load_benchmarks
from claasp_bench.results import load_result_records
from claasp_bench.taxonomy import PRIMITIVES, TAXONOMY


ROOT = Path(__file__).resolve().parents[1]


class ClaaspBenchTests(unittest.TestCase):
    def test_benchmark_file_names_follow_naming_convention(self) -> None:
        bad = check_file_names(ROOT / "benchmarks")
        self.assertEqual(
            bad,
            [],
            msg="Non-standard benchmark file names:\n" + "\n".join(bad),
        )

    def test_benchmark_file_name_pattern_accepts_valid_names(self) -> None:
        valid = [
            # minimal: rounds only
            "speck_differential_find_one_r5b32k64_sat.json",
            # full params: rounds + block + key
            "aes_linear_find_optimal_r2b128k128_milp.json",
            # rounds + block + key + weight
            "present_differential_find_all_fixed_weight_r3b64k80_cp.json",
            # state-based primitive (permutation): rounds + state
            "gimli_differential_find_one_r2s384_smt.json",
            # modifier before params
            "ascon_linear_find_all_fixed_weight_unsat_r2s320w1_all_models.json",
            "speck_differential_find_all_fixed_weight_multicores_r2b32k64w1_all_models.json",
            # two modifiers
            "speck_differential_find_all_fixed_weight_multicores_unsat_r3b8k16w1_all_models.json",
            # optional note at the end
            "speck_differential_find_one_r5b32k64_sat_v2.json",
            "aes_linear_find_optimal_r2b128k128_milp_strong_rc.json",
            # other analyses and tasks
            "cipher_impossible_differential_find_one_r4b64k128_sat.json",
            "cipher_rotational_xor_enumerate_r6b64_all_models.json",
        ]
        for name in valid:
            with self.subTest(name=name):
                self.assertIsNotNone(BENCHMARK_FILE_NAME_RE.match(name), f"Should match: {name}")

    def test_benchmark_file_name_pattern_rejects_invalid_names(self) -> None:
        invalid = [
            # legacy / free-form names
            "claasp_import.json",
            "taxonomy_examples.json",
            "speck_nightly_sat.json",
            # missing analysis
            "aes_find_one_r2b128k128_all_models.json",
            # uppercase
            "SPECK_differential_find_one_r5b32k64_sat.json",
            # missing params slot entirely
            "speck_differential_find_one_sat.json",
            # missing solver scope
            "speck_differential_find_one_r5b32k64.json",
            # params not starting with r
            "speck_differential_find_one_b32k64_sat.json",
            # unknown analysis
            "speck_unknown_analysis_find_one_r5b32k64_sat.json",
        ]
        for name in invalid:
            with self.subTest(name=name):
                self.assertIsNone(BENCHMARK_FILE_NAME_RE.match(name), f"Should not match: {name}")

    def test_fixture_manifests_cover_representative_taxonomy(self) -> None:
        benchmarks = load_benchmarks(ROOT / "benchmarks" / "fixtures")
        self.assertGreaterEqual(len(benchmarks), 4)
        families = {benchmark.primitive_family for benchmark in benchmarks}
        goals = {benchmark.goal for benchmark in benchmarks}
        analyses = {benchmark.analysis for benchmark in benchmarks}
        self.assertIn("ARX", families)
        self.assertIn("bit_based_SPN", families)
        self.assertIn("word_based_SPN", families)
        self.assertIn("permutation", families)
        self.assertIn("find_one_trail", goals)
        self.assertIn("enumerate_trails", goals)
        self.assertIn("prove_bound", goals)
        self.assertIn("differential", analyses)
        self.assertIn("linear", analyses)

    def test_taxonomy_contains_expected_dimensions(self) -> None:
        self.assertEqual(len(TAXONOMY["goal"]), 6)
        self.assertEqual(len(TAXONOMY["primitive_family"]), 6)
        self.assertEqual(len(TAXONOMY["analysis"]), 6)

    def test_benchmark_fields_use_allowed_values(self) -> None:
        """CI validation: every benchmark JSON uses only taxonomy-approved values."""
        benchmarks = load_benchmarks(ROOT / "benchmarks")
        for b in benchmarks:
            ctx = b.source_path or b.id
            with self.subTest(benchmark=ctx):
                self.assertIn(
                    b.primitive, PRIMITIVES,
                    f"{ctx}: unknown primitive {b.primitive!r} — add it to PRIMITIVES in taxonomy.py",
                )
                self.assertIn(b.primitive_family, TAXONOMY["primitive_family"])
                self.assertIn(b.goal, TAXONOMY["goal"])
                self.assertIn(b.analysis, TAXONOMY["analysis"])
                self.assertIn(b.execution.runner, TAXONOMY["runner"])
                kind = b.execution.task.get("kind", "claasp_import_check")
                self.assertIn(
                    kind, TAXONOMY["kind"],
                    f"{ctx}: unknown kind {kind!r} — add it to TAXONOMY['kind'] in taxonomy.py",
                )
                for fam in b.execution.task.get("solver_families", []):
                    self.assertIn(fam, TAXONOMY["solver_family"])

    def test_run_report_and_site_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results_dir = tmp_path / "results"
            site_dir = tmp_path / "site"
            report_path = tmp_path / "report.md"

            self.assertEqual(
                main(["run", str(ROOT / "benchmarks" / "fixtures"), "--output", str(results_dir), "--runner", "synthetic"]),
                0,
            )
            records = load_result_records(results_dir)
            self.assertEqual(len(records), 4)
            self.assertIn("cipher", records[0])
            self.assertIn("build_time_seconds", records[0]["timing"])
            self.assertIn("solver_output", records[0])

            self.assertEqual(main(["report", str(results_dir), "--output", str(report_path)]), 0)
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("CLAASP Benchmark Report", report)
            self.assertIn("Speck-32/64", report)
            self.assertIn("Cipher Parameters", report)
            self.assertIn("Architecture", report)
            self.assertIn("CLAASP Output", report)
            self.assertIn("Solver Output", report)

            self.assertEqual(main(["site", str(results_dir), "--output", str(site_dir)]), 0)
            self.assertTrue((site_dir / "index.html").exists())
            self.assertTrue((site_dir / "results.json").exists())
            app_js = (site_dir / "app.js").read_text(encoding="utf-8")
            index_html = (site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("primitive_family", app_js)
            self.assertIn("cipherParameters", app_js)
            self.assertIn("buildColumnControls", app_js)
            self.assertIn("renderBenchmarkSummary", app_js)
            self.assertIn("solver_output", app_js)
            self.assertIn("column-controls", index_html)
            self.assertIn("Benchmark Summary", index_html)


if __name__ == "__main__":
    unittest.main()
