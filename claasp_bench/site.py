"""Static GitHub Pages site generation."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .results import load_result_records, summarize, write_json
from .taxonomy import TAXONOMY


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CLAASP Benchmarks</title>
  <link rel="stylesheet" href="style.css?v=__ASSET_VERSION__">
</head>
<body>
  <header>
    <h1>CLAASP Solver Benchmarks</h1>
    <p>Filter by primitive, CLAASP method, model family, solver, status, and duration.</p>
  </header>
  <main>
    <section class="filter-panel" aria-label="Benchmark filters">
      <h2>Filters</h2>
      <div id="filters"></div>
    </section>
    <nav class="tabs" aria-label="Views">
      <button class="tab-button active" type="button" data-tab="summary-panel">Benchmark Summary</button>
      <button class="tab-button" type="button" data-tab="database-panel">Full Database</button>
    </nav>
    <section id="summary-panel" class="tab-panel active">
      <section class="summary">
        <h2 class="section-heading">Stats</h2>
        <div><strong id="count">0</strong><span>runs</span></div>
        <div><strong id="total-wall">-</strong><span>total wall time</span></div>
        <div><strong id="best">-</strong><span>best time</span></div>
        <div><strong id="median">-</strong><span>median time</span></div>
        <div><strong id="statuses">-</strong><span>statuses</span></div>
      </section>
      <div class="toolbar table-toolbar">
        <section>
          <h2>Display</h2>
          <div class="display-controls" aria-label="Summary cell display mode">
            <button type="button" class="display-button active" data-table="summary" data-mode="compact">Compact</button>
            <button type="button" class="display-button" data-table="summary" data-mode="wrap">Wrap Cells</button>
            <button type="button" class="display-button" data-table="summary" data-mode="expanded">Expand Lines</button>
          </div>
        </section>
      </div>
      <table id="summary-table" class="compact">
          <colgroup id="summary-colgroup"></colgroup>
          <thead>
            <tr id="summary-header"></tr>
          </thead>
          <tbody id="summary-rows"></tbody>
        </table>
    </section>
    <section id="database-panel" class="tab-panel">
      <div class="toolbar">
        <section>
          <h2>Columns</h2>
          <div id="column-controls" class="column-controls" aria-label="Column controls"></div>
        </section>
        <section>
          <h2>Display</h2>
          <div class="display-controls" aria-label="Cell display mode">
            <button type="button" class="display-button active" data-table="runs" data-mode="compact">Compact</button>
            <button type="button" class="display-button" data-table="runs" data-mode="wrap">Wrap Cells</button>
            <button type="button" class="display-button" data-table="runs" data-mode="expanded">Expand Lines</button>
          </div>
        </section>
      </div>
      <table id="runs-table" class="compact">
        <colgroup id="runs-colgroup"></colgroup>
        <thead>
          <tr id="runs-header"></tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </section>
  </main>
  <textarea id="cell-tooltip" readonly aria-hidden="true"></textarea>
  <script src="app.js?v=__ASSET_VERSION__"></script>
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
h2 {
  margin: 18px 0 10px;
  font-size: 18px;
}
p {
  margin: 0;
  color: #57606f;
}
.section-heading {
  grid-column: 1 / -1;
  position: sticky;
  left: 0;
  z-index: 2;
  background: #f7f8fa;
}
.filter-panel {
  margin-bottom: 16px;
}
#filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  min-width: 0;
}
.column-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-bottom: 10px;
}
.column-controls label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}
select {
  width: 100%;
  min-width: 0;
  min-height: 36px;
  border: 1px solid #ced6e0;
  border-radius: 6px;
  background: #ffffff;
  padding: 6px 8px;
}
.tabs {
  display: flex;
  gap: 8px;
  margin: 14px 0;
  border-bottom: 1px solid #dfe4ea;
}
button {
  min-height: 34px;
  border: 1px solid #ced6e0;
  border-radius: 6px;
  background: #ffffff;
  padding: 6px 10px;
  cursor: pointer;
}
.tab-button {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  border-bottom-color: transparent;
}
.tab-button.active,
.display-button.active {
  background: #17202a;
  border-color: #17202a;
  color: #ffffff;
}
.tab-panel {
  display: none;
}
.tab-panel.active {
  display: block;
}
.toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: start;
  position: sticky;
  left: 0;
  z-index: 3;
  width: fit-content;
  min-width: 100%;
  background: #f7f8fa;
  padding-bottom: 8px;
}
.table-toolbar {
  margin: 12px 0 8px;
}
.display-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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
  width: max-content;
  min-width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  background: #ffffff;
  border: 1px solid #dfe4ea;
}
th, td {
  padding: 9px 10px;
  border-bottom: 1px solid #edf0f2;
  text-align: left;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: top;
}
table.compact td {
  white-space: nowrap;
  max-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
table.wrap td {
  white-space: normal;
  max-width: 0;
  overflow: hidden;
  text-overflow: clip;
}
table.expanded {
  table-layout: auto;
  width: max-content;
}
table.expanded td {
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
}
th {
  background: #f1f3f5;
  position: sticky;
  top: 0;
  white-space: nowrap;
}
.resizable-th {
  position: relative;
}
.resize-handle {
  position: absolute;
  right: 0;
  top: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  user-select: none;
}
#cell-tooltip {
  display: none;
  position: fixed;
  z-index: 10;
  width: min(620px, calc(100vw - 32px));
  min-height: 96px;
  max-height: 240px;
  padding: 10px;
  border: 1px solid #a4b0be;
  border-radius: 6px;
  background: #ffffff;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.16);
  color: #17202a;
  font: 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  resize: both;
}
@media (max-width: 760px) {
  .toolbar {
    grid-template-columns: 1fr;
  }
}
"""

JS = """const assetVersion = "__ASSET_VERSION__";
const dimensions = [
  ["tier", "Tier", record => record.tier],
  ["primitive", "Primitive", record => record.challenge.primitive],
  ["primitive_family", "Primitive Family", record => record.challenge.primitive_family],
  ["claasp_method", "CLAASP Method", record => claaspMethod(record)],
  ["model_family", "Model", record => record.challenge.model_family],
  ["solver", "Solver", record => record.execution.solver],
  ["cores", "Cores", record => String((record.execution.machine || {}).usable_cpu_count ?? "NA")],
  ["duration", "Duration", record => durationBucket(record.timing.wall_time_seconds)],
  ["status", "Status", record => record.status],
];
const columnDescriptions = {
  tier: "Benchmark suite tier, such as smoke, nightly, or release.",
  benchmark: "Stable run identifier emitted by the benchmark runner.",
  primitive: "Concrete cipher or primitive under test.",
  cipher_parameters: "Cipher parameters reported by CLAASP, such as rounds, block size, and key size.",
  architecture: "CPU, usable cores, platform, and runtime architecture used for the run.",
  claasp_method: "CLAASP model method invoked for this run.",
  goal: "Taxonomy goal recorded in the benchmark manifest.",
  analysis: "Cryptanalytic analysis family recorded in the benchmark manifest.",
  model: "CLAASP modeling family used for this run.",
  solver: "Solver/backend used for this run.",
  solver_version: "Solver version detected from the executable, when available.",
  solver_options: "Executable, options, selector, and command format used to call the solver.",
  status: "Normalized run status.",
  cores: "Usable CPU cores seen by the worker process (from sched_getaffinity or cpu_count).",
  build: "Model building time reported by CLAASP, when available.",
  solve: "Solver time reported by CLAASP, when available.",
  wall: "End-to-end wall-clock time measured by the benchmark runner.",
  memory: "Peak memory in MB, preferring CLAASP/solver data when available.",
  model_size: "Model size fields such as variables, constraints, clauses, and generated file size.",
  claasp_output: "CLAASP metadata and method-specific fields.",
  solver_output: "Solver-specific metadata and output fields.",
  error: "Error details when a run fails or times out.",
  artifacts: "Captured stdout/stderr excerpts and worker details.",
};
const summaryColumnDescriptions = {
  instance: "Cipher, parameters, CLAASP method, and analysis defining this benchmark instance.",
  runs: "Number of run records in this summary group after filters are applied.",
  solvers: "Solvers represented in this summary group.",
  statuses: "Status counts for this summary group.",
  total_wall: "Sum of wall-clock time for all runs in this summary group.",
  best_wall: "Fastest wall-clock time in this summary group.",
  median_wall: "Median wall-clock time in this summary group.",
};
const summaryColumns = [
  ["instance", "Instance", item => item.key],
  ["runs", "Runs", item => item.runs],
  ["solvers", "Solvers", item => item.solvers],
  ["statuses", "Statuses", item => item.statuses],
  ["total_wall", "Total Wall", item => item.totalWall],
  ["best_wall", "Best Wall", item => item.bestWall],
  ["median_wall", "Median Wall", item => item.medianWall],
];
const runColumns = [
  ["tier", "Tier", record => record.tier],
  ["benchmark", "Benchmark", record => record.benchmark_id],
  ["primitive", "Primitive", record => record.challenge.primitive],
  ["cipher_parameters", "Cipher Parameters", record => cipherParameters(record)],
  ["architecture", "Architecture", record => architecture(record)],
  ["claasp_method", "CLAASP Method", record => claaspMethod(record)],
  ["goal", "Goal", record => record.challenge.goal],
  ["analysis", "Analysis", record => record.challenge.analysis],
  ["model", "Model", record => record.challenge.model_family],
  ["solver", "Solver", record => record.execution.solver],
  ["solver_version", "Solver Version", record => (record.solver_output || {}).solver_version],
  ["solver_options", "Solver Options", record => solverOptions(record)],
  ["status", "Status", record => record.status],
  ["cores", "Cores", record => (record.execution.machine || {}).usable_cpu_count],
  ["build", "Build", record => fmtSeconds(record.timing.build_time_seconds)],
  ["solve", "Solve", record => fmtSeconds(record.timing.solve_time_seconds)],
  ["wall", "Wall", record => fmtSeconds(record.timing.wall_time_seconds)],
  ["memory", "Memory", record => fmtMemory(record.resources.peak_memory_mb)],
  ["model_size", "Model Size", record => modelSize(record)],
  ["claasp_output", "CLAASP Output", record => fmtValue(record.claasp_output || {})],
  ["solver_output", "Solver Output", record => fmtValue(record.solver_output || {})],
  ["error", "Error", record => record.error],
  ["artifacts", "Artifacts", record => fmtValue(record.artifacts || {})],
];
let allResults = [];
let taxonomy = {};
let visibleColumns = new Set(runColumns.map(([id]) => id));
const tableState = {
  runs: {displayMode: "compact", columnWidths: {}},
  summary: {displayMode: "compact", columnWidths: {}},
};

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

function durationBucket(value) {
  if (typeof value !== "number") return "NA";
  if (value < 1) return "t < 1s";
  if (value < 60) return "1s <= t < 1m";
  if (value < 3600) return "1m <= t < 1h";
  return "t >= 1h";
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

function solverOptions(record) {
  const output = record.solver_output || {};
  return fmtValue({
    executable: output.solver_executable,
    options: output.solver_options,
    selector: output.solver_selector,
    format: output.solver_command_format,
  });
}

function architecture(record) {
  const machine = record.execution.machine || {};
  const cpu = machine.cpu_model || machine.processor || machine.machine;
  const cores = machine.usable_cpu_count || machine.cpu_count;
  return `${fmtValue(cpu)}; cores=${fmtValue(cores)}; ${fmtValue(machine.platform || machine.machine)}`;
}

function claaspMethod(record) {
  const method = record.execution.claasp_method || (record.claasp_output || {}).method_name;
  return method ? String(method).split(".").pop() : "NA";
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function fieldValue(record, fieldId) {
  const dimension = dimensions.find(([id]) => id === fieldId);
  return dimension ? dimension[2](record) : "";
}

function buildFilters() {
  const filters = document.getElementById("filters");
  filters.innerHTML = "";
  for (const [field, labelText, getter] of dimensions) {
    const values = [...new Set(allResults.map(record => getter(record)).filter(Boolean))].sort();
    const label = document.createElement("label");
    label.textContent = labelText;
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
    const selected = document.getElementById(`filter-${field[0]}`).value;
    return !selected || field[2](record) === selected;
  }));
}

function instanceKey(record) {
  return [
    record.challenge.primitive,
    cipherParameters(record),
    claaspMethod(record),
    record.challenge.analysis
  ].join(" | ");
}

function buildColumnControls() {
  const controls = document.getElementById("column-controls");
  controls.innerHTML = runColumns.map(([id, label]) => `
    <label><input type="checkbox" data-column="${id}" checked> ${escapeHtml(label)}</label>
  `).join("");
  controls.querySelectorAll("input[type='checkbox']").forEach(input => {
    input.addEventListener("change", event => {
      const id = event.target.dataset.column;
      if (event.target.checked) visibleColumns.add(id);
      else visibleColumns.delete(id);
      render();
    });
  });
}

function buildTabs() {
  document.querySelectorAll(".tab-button").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab-button").forEach(item => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(item => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.tab).classList.add("active");
    });
  });
}

function buildDisplayControls() {
  document.querySelectorAll(".display-button").forEach(button => {
    button.addEventListener("click", () => {
      const tableName = button.dataset.table;
      const state = tableState[tableName];
      state.displayMode = button.dataset.mode;
      if (state.displayMode === "compact") state.columnWidths = {};
      document.querySelectorAll(`.display-button[data-table="${tableName}"]`).forEach(item => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(`${tableName === "runs" ? "runs" : "summary"}-table`).className = state.displayMode;
      if (tableName === "runs") renderRunHeader();
      else renderSummaryHeader();
    });
  });
}

function minColumnWidth(label) {
  return Math.max(88, Math.ceil(label.length * 8.2) + 34);
}

function renderTableHeader({tableName, tableId, colgroupId, headerId, columns, descriptions}) {
  const state = tableState[tableName];
  const active = columns;
  document.getElementById(colgroupId).innerHTML = active.map(([id, label]) => `
    <col data-table="${tableName}" data-column="${id}" style="${state.displayMode === "expanded" ? "" : `width: ${state.columnWidths[id] || `${minColumnWidth(label)}px`}`}">
  `).join("");
  document.getElementById(headerId).innerHTML = active.map(([id, label]) => `
    <th class="resizable-th" data-column="${id}" title="${escapeHtml(descriptions[id] || label)}">${escapeHtml(label)}<span class="resize-handle" data-table="${tableName}" data-column="${id}"></span></th>
  `).join("");
  document.querySelectorAll(`#${tableId} .resize-handle`).forEach(handle => {
    handle.addEventListener("mousedown", startResize);
  });
}

function renderRunHeader() {
  const active = runColumns.filter(([id]) => visibleColumns.has(id));
  renderTableHeader({
    tableName: "runs",
    tableId: "runs-table",
    colgroupId: "runs-colgroup",
    headerId: "runs-header",
    columns: active,
    descriptions: columnDescriptions,
  });
}

function renderSummaryHeader() {
  renderTableHeader({
    tableName: "summary",
    tableId: "summary-table",
    colgroupId: "summary-colgroup",
    headerId: "summary-header",
    columns: summaryColumns,
    descriptions: summaryColumnDescriptions,
  });
}

function startResize(event) {
  event.preventDefault();
  const tableName = event.target.dataset.table;
  const columnId = event.target.dataset.column;
  const state = tableState[tableName];
  const col = document.querySelector(`col[data-table="${tableName}"][data-column="${columnId}"]`);
  const startX = event.clientX;
  const startWidth = col.getBoundingClientRect().width;
  function move(moveEvent) {
    const nextWidth = Math.max(70, startWidth + moveEvent.clientX - startX);
    state.columnWidths[columnId] = `${nextWidth}px`;
    col.style.width = state.columnWidths[columnId];
  }
  function stop() {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", stop);
  }
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", stop);
}

function renderBenchmarkSummary(records) {
  const groups = new Map();
  for (const record of records) {
    const key = instanceKey(record);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  }
  const summaryRows = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, items]) => {
    const durations = items.map(record => record.timing.wall_time_seconds).filter(value => typeof value === "number");
    const statuses = items.reduce((counts, record) => {
      counts[record.status] = (counts[record.status] || 0) + 1;
      return counts;
    }, {});
    const solvers = [...new Set(items.map(record => record.execution.solver).filter(Boolean))].sort();
    return {
      key,
      runs: items.length,
      solvers: solvers.join(", ") || "NA",
      statuses: Object.entries(statuses).map(([k, v]) => `${k}: ${v}`).join(", ") || "NA",
      totalWall: durations.length ? fmtSeconds(durations.reduce((total, value) => total + value, 0)) : "NA",
      bestWall: durations.length ? fmtSeconds(Math.min(...durations)) : "NA",
      medianWall: fmtSeconds(median(durations)),
    };
  });
  renderSummaryHeader();
  document.getElementById("summary-rows").innerHTML = summaryRows.map(item => `
      <tr>
        ${summaryColumns.map(([, , getter]) => {
          const value = fmtValue(getter(item));
          return `<td data-full="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
        }).join("")}
      </tr>
    `).join("");
}

function render() {
  const records = filteredResults();
  const durations = records.map(record => record.timing.wall_time_seconds).filter(value => typeof value === "number");
  const statusCounts = records.reduce((counts, record) => {
    counts[record.status] = (counts[record.status] || 0) + 1;
    return counts;
  }, {});
  document.getElementById("count").textContent = records.length;
  document.getElementById("total-wall").textContent = durations.length ? fmtSeconds(durations.reduce((total, value) => total + value, 0)) : "-";
  document.getElementById("best").textContent = durations.length ? fmtSeconds(Math.min(...durations)) : "-";
  document.getElementById("median").textContent = fmtSeconds(median(durations));
  document.getElementById("statuses").textContent = Object.entries(statusCounts).map(([k, v]) => `${k}: ${v}`).join(", ") || "-";
  renderBenchmarkSummary(records);
  renderRunHeader();
  const active = runColumns.filter(([id]) => visibleColumns.has(id));
  document.getElementById("rows").innerHTML = records.map(record => `
    <tr>
      ${active.map(([, , getter]) => {
        const value = fmtValue(getter(record));
        return `<td data-full="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
      }).join("")}
    </tr>
  `).join("");
  bindCellTooltips();
}

function bindCellTooltips() {
  const tooltip = document.getElementById("cell-tooltip");
  document.querySelectorAll("#runs-table td, #summary-table td").forEach(cell => {
    cell.addEventListener("mouseenter", event => {
      tooltip.value = event.currentTarget.dataset.full || "";
      tooltip.style.display = "block";
      tooltip.setAttribute("aria-hidden", "false");
      moveTooltip(event);
    });
    cell.addEventListener("mousemove", moveTooltip);
    cell.addEventListener("mouseleave", () => {
      tooltip.style.display = "none";
      tooltip.setAttribute("aria-hidden", "true");
    });
  });
}

function moveTooltip(event) {
  const tooltip = document.getElementById("cell-tooltip");
  const left = Math.min(event.clientX + 14, window.innerWidth - tooltip.offsetWidth - 16);
  const top = Math.min(event.clientY + 14, window.innerHeight - tooltip.offsetHeight - 16);
  tooltip.style.left = `${Math.max(12, left)}px`;
  tooltip.style.top = `${Math.max(12, top)}px`;
}

Promise.all([
  fetch(`results.json?v=${assetVersion}`).then(response => response.json()),
  fetch(`taxonomy.json?v=${assetVersion}`).then(response => response.json())
])
  .then(([results, taxonomyData]) => {
    allResults = results;
    taxonomy = taxonomyData;
    buildFilters();
    buildTabs();
    buildColumnControls();
    buildDisplayControls();
    render();
  });
"""


def generate_site(results_dir: Path, output_dir: Path) -> None:
    records = load_result_records(results_dir)
    asset_version = str(int(time.time()))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "results.json", records)
    write_json(output_dir / "summary.json", summarize(records))
    write_json(output_dir / "taxonomy.json", TAXONOMY)
    (output_dir / "index.html").write_text(HTML.replace("__ASSET_VERSION__", asset_version), encoding="utf-8")
    (output_dir / "style.css").write_text(CSS, encoding="utf-8")
    (output_dir / "app.js").write_text(JS.replace("__ASSET_VERSION__", asset_version), encoding="utf-8")
