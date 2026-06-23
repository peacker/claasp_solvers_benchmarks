"""Static GitHub Pages site generation."""

from __future__ import annotations

import json
from pathlib import Path

from .results import load_result_records, summarize, write_json
from .taxonomy import TAXONOMY


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CLAASP Benchmarks</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>CLAASP Solver Benchmarks</h1>
    <p>Filter by challenge goal, primitive family, analysis, model family, and difficulty.</p>
  </header>
  <main>
    <section id="filters" aria-label="Benchmark filters"></section>
    <section class="summary">
      <div><strong id="count">0</strong><span>runs</span></div>
      <div><strong id="best">-</strong><span>best time</span></div>
      <div><strong id="median">-</strong><span>median time</span></div>
      <div><strong id="statuses">-</strong><span>statuses</span></div>
    </section>
    <section>
      <table>
        <thead>
          <tr>
            <th>Benchmark</th><th>Primitive</th><th>Cipher Parameters</th><th>Architecture</th>
            <th>Goal</th><th>Analysis</th><th>Model</th><th>Solver</th><th>Status</th>
            <th>Build</th><th>Solve</th><th>Wall</th><th>Memory</th><th>Model Size</th><th>CLAASP Output</th><th>Solver Output</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""

CSS = """body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #17202a;
  background: #f7f8fa;
}
header, main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}
header {
  background: #ffffff;
  border-bottom: 1px solid #dfe4ea;
}
h1 {
  margin: 0 0 8px;
  font-size: 28px;
}
p {
  margin: 0;
  color: #57606f;
}
#filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
select {
  min-height: 36px;
  border: 1px solid #ced6e0;
  border-radius: 6px;
  background: #ffffff;
  padding: 6px 8px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin: 16px 0;
}
.summary div {
  background: #ffffff;
  border: 1px solid #dfe4ea;
  border-radius: 8px;
  padding: 14px;
}
.summary strong {
  display: block;
  font-size: 22px;
}
.summary span {
  color: #57606f;
}
section {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: #ffffff;
  border: 1px solid #dfe4ea;
  min-width: 1480px;
}
th, td {
  padding: 9px 10px;
  border-bottom: 1px solid #edf0f2;
  text-align: left;
  font-size: 13px;
}
th {
  background: #f1f3f5;
  position: sticky;
  top: 0;
}
"""

JS = """const dimensions = ["primitive", "primitive_family", "goal", "analysis", "model_family", "solver", "difficulty", "io_mode", "model_mode"];
const taxonomyFields = new Set(["primitive_family", "goal", "analysis", "model_family", "difficulty", "io_mode", "model_mode"]);
let allResults = [];
let taxonomy = {};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtValue(value) {
  if (value === null || value === undefined || value === "") return "NA";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (Array.isArray(value)) return `[${value.map(fmtValue).join(", ")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined);
    if (!entries.length) return "NA";
    return entries.sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${key}=${fmtValue(item)}`).join(", ");
  }
  return String(value);
}

function fmtSeconds(value) {
  return value === null || value === undefined ? "NA" : `${Number(value).toFixed(3)}s`;
}

function fmtMemory(value) {
  return value === null || value === undefined ? "NA" : `${Number(value).toFixed(1)} MB`;
}

function cipherParameters(record) {
  const cipher = record.cipher || {};
  const parameters = {...(cipher.parameters || {})};
  for (const key of ["number_of_rounds", "block_bit_size", "key_bit_size", "state_bit_size"]) {
    if (cipher[key] !== null && cipher[key] !== undefined && parameters[key] === undefined) {
      parameters[key] = cipher[key];
    }
  }
  return fmtValue(parameters);
}

function modelSize(record) {
  return fmtValue(record.model || {});
}

function architecture(record) {
  const machine = record.execution.machine || {};
  return fmtValue(machine.platform || machine.machine);
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function fieldValue(record, field) {
  return field === "solver" ? record.execution.solver : record.challenge[field];
}

function buildFilters() {
  const filters = document.getElementById("filters");
  filters.innerHTML = "";
  for (const field of dimensions) {
    const values = taxonomyFields.has(field)
      ? [...(taxonomy[field] || [])]
      : [...new Set(allResults.map(record => fieldValue(record, field)).filter(Boolean))].sort();
    const label = document.createElement("label");
    label.textContent = field.replaceAll("_", " ");
    const select = document.createElement("select");
    select.id = `filter-${field}`;
    select.innerHTML = `<option value="">All</option>` + values.map(value => `<option>${value}</option>`).join("");
    select.addEventListener("change", render);
    label.appendChild(select);
    filters.appendChild(label);
  }
}

function filteredResults() {
  return allResults.filter(record => dimensions.every(field => {
    const selected = document.getElementById(`filter-${field}`).value;
    return !selected || fieldValue(record, field) === selected;
  }));
}

function render() {
  const records = filteredResults();
  const durations = records.map(record => record.timing.wall_time_seconds).filter(value => typeof value === "number");
  const statusCounts = records.reduce((counts, record) => {
    counts[record.status] = (counts[record.status] || 0) + 1;
    return counts;
  }, {});
  document.getElementById("count").textContent = records.length;
  document.getElementById("best").textContent = durations.length ? fmtSeconds(Math.min(...durations)) : "-";
  document.getElementById("median").textContent = fmtSeconds(median(durations));
  document.getElementById("statuses").textContent = Object.entries(statusCounts).map(([k, v]) => `${k}: ${v}`).join(", ") || "-";
  document.getElementById("rows").innerHTML = records.map(record => `
    <tr>
      <td>${escapeHtml(record.benchmark_id)}</td>
      <td>${escapeHtml(record.challenge.primitive)}</td>
      <td>${escapeHtml(cipherParameters(record))}</td>
      <td>${escapeHtml(architecture(record))}</td>
      <td>${escapeHtml(record.challenge.goal)}</td>
      <td>${escapeHtml(record.challenge.analysis)}</td>
      <td>${escapeHtml(record.challenge.model_family)}</td>
      <td>${escapeHtml(record.execution.solver)}</td>
      <td>${escapeHtml(record.status)}</td>
      <td>${escapeHtml(fmtSeconds(record.timing.build_time_seconds))}</td>
      <td>${escapeHtml(fmtSeconds(record.timing.solve_time_seconds))}</td>
      <td>${escapeHtml(fmtSeconds(record.timing.wall_time_seconds))}</td>
      <td>${escapeHtml(fmtMemory(record.resources.peak_memory_mb))}</td>
      <td>${escapeHtml(modelSize(record))}</td>
      <td>${escapeHtml(fmtValue(record.claasp_output || {}))}</td>
      <td>${escapeHtml(fmtValue(record.solver_output || {}))}</td>
    </tr>
  `).join("");
}

Promise.all([
  fetch("results.json").then(response => response.json()),
  fetch("taxonomy.json").then(response => response.json())
])
  .then(([results, taxonomyData]) => {
    allResults = results;
    taxonomy = taxonomyData;
    buildFilters();
    render();
  });
"""


def generate_site(results_dir: Path, output_dir: Path) -> None:
    records = load_result_records(results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "results.json", records)
    write_json(output_dir / "summary.json", summarize(records))
    write_json(output_dir / "taxonomy.json", TAXONOMY)
    (output_dir / "index.html").write_text(HTML, encoding="utf-8")
    (output_dir / "style.css").write_text(CSS, encoding="utf-8")
    (output_dir / "app.js").write_text(JS, encoding="utf-8")
