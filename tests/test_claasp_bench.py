from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from claasp_bench.cli import main
from claasp_bench.loader import load_benchmarks
from claasp_bench.results import load_result_records
from claasp_bench.taxonomy import TAXONOMY


ROOT = Path(__file__).resolve().parents[1]


class ClaaspBenchTests(unittest.TestCase):
    def test_fixture_manifests_cover_representative_taxonomy(self) -> None:
        benchmarks = load_benchmarks(ROOT / "benchmarks" / "fixtures")
        self.assertGreaterEqual(len(benchmarks), 4)
        families = {benchmark.challenge.primitive_family for benchmark in benchmarks}
        goals = {benchmark.challenge.goal for benchmark in benchmarks}
        analyses = {benchmark.challenge.analysis for benchmark in benchmarks}
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
        self.assertEqual(len(TAXONOMY["model_family"]), 6)

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
