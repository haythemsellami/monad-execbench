// Entry point: loads summary.json once, then renders the rail, header and the
// hash-routed view. Case and frame files are fetched strictly on selection.

import { h, icon, tag, loading, fine } from "./dom.js";
import { formatInt, plural } from "./format.js";
import {
  METRICS,
  VIEWS,
  state,
  viewFromHash,
  resetForRun,
  resetForCase,
  resetForFrame,
} from "./state.js";
import { renderOverview } from "./views/overview.js";
import { renderScaling } from "./views/scaling.js";
import { renderComparisons } from "./views/comparisons.js";
import { renderExplorer } from "./views/explorer.js";
import { renderProvenance } from "./views/provenance.js";

const SCHEMA = "monad-execbench/viewer-v1";
const CASE_FILE = /^p[0-9]+-c[0-9]+$/;
const FRAME_FILE = /^p[0-9]+-c[0-9]+\/frame-[0-9]+\.json$/;

const rail = document.getElementById("rail");
const main = document.getElementById("main");

let data = null;
let caseById = new Map();
let caseToken = 0;
let frameToken = 0;
let copiedTimer = null;
const cache = new Map();

async function loadJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  cache.set(path, payload);
  return payload;
}

function currentRun() {
  if (!data) return null;
  return data.runs.find((run) => run.id === state.runId) ?? data.runs[0];
}

function currentCase(run) {
  if (!run || state.caseId === null) return null;
  return run.cases.find((item) => item.id === state.caseId) ?? null;
}

function distinctCounters(run) {
  return [...new Set(run.cases.flatMap((item) => Object.keys(item.counters)))];
}

function viewCount(key, run) {
  switch (key) {
    case "overview":
      return run.cases.length;
    case "scaling":
      return distinctCounters(run).length;
    case "comparisons":
      return data.comparisons.length;
    case "explorer":
      return run.cases.filter((item) => item.profile !== null).length;
    case "provenance":
      return run.warnings.length;
    default:
      return 0;
  }
}

const actions = {
  set(patch) {
    Object.assign(state, patch);
    render();
  },
  selectRun(id) {
    if (!data.runs.some((run) => run.id === id) || id === state.runId) return;
    caseToken += 1;
    frameToken += 1;
    state.runId = id;
    resetForRun();
    render();
  },
  selectCase(id, navigate = false) {
    const run = currentRun();
    const item = run?.cases.find((entry) => entry.id === id);
    if (!item) return;
    if (navigate) window.location.hash = "#explorer";
    if (state.caseId !== id) {
      caseToken += 1;
      frameToken += 1;
      state.caseId = id;
      resetForCase();
      requestCase(item);
    }
    render();
  },
  retryCase() {
    const item = currentCase(currentRun());
    if (item) {
      caseToken += 1;
      requestCase(item);
      render();
    }
  },
  selectFrame(id) {
    const profile = state.caseRequest?.data;
    const frame = profile?.frames.find((entry) => entry.id === id);
    if (!frame) return;
    if (state.frameId !== id || state.frameRequest?.status === "failed") {
      frameToken += 1;
      state.frameId = id;
      resetForFrame();
      requestFrame(frame);
    }
    render();
  },
  retryFrame() {
    const profile = state.caseRequest?.data;
    const frame = profile?.frames.find((entry) => entry.id === state.frameId);
    if (frame) {
      frameToken += 1;
      resetForFrame();
      requestFrame(frame);
      render();
    }
  },
  selectSource(index, scrollTo = null) {
    state.selectedSourceIndex = index;
    state.scrollTo = scrollTo;
    render();
  },
  scrollTo(id) {
    state.scrollTo = id;
    render();
  },
  copy(text, key) {
    const finish = () => {
      state.copied = key;
      clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        state.copied = null;
        render();
      }, 1400);
      render();
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(String(text)).then(finish, finish);
    } else finish();
  },
};

function requestCase(item) {
  const profile = item.profile;
  if (typeof profile !== "string" || !CASE_FILE.test(profile)) {
    state.caseRequest = null;
    return;
  }
  const path = `/${profile}.json`;
  const token = caseToken;
  state.caseRequest = { path, status: "loading", data: null, error: null };
  loadJSON(path).then(
    (payload) => {
      if (token !== caseToken) return;
      if (!payload || !Array.isArray(payload.frames) || !Array.isArray(payload.sources)) {
        state.caseRequest = {
          path,
          status: "failed",
          data: null,
          error: "The case file is not a viewer-v1 case document.",
        };
        render();
        return;
      }
      state.caseRequest = { path, status: "ready", data: payload, error: null };
      state.selectedSourceIndex = 0;
      state.pcPage = 1;
      state.treePage = 1;
      const root = payload.frames.find((frame) => frame.parent === null) ?? null;
      state.frameId = root ? root.id : null;
      if (root) requestFrame(root);
      render();
    },
    (error) => {
      if (token !== caseToken) return;
      state.caseRequest = { path, status: "failed", data: null, error: error.message };
      render();
    },
  );
}

function requestFrame(frame) {
  const file = frame.file;
  if (typeof file !== "string" || !FRAME_FILE.test(file)) {
    state.frameRequest = {
      path: String(file),
      status: "failed",
      data: null,
      error: "The frame path in the case file is not a lazy frame file.",
    };
    return;
  }
  const path = `/${file}`;
  const token = frameToken;
  state.frameRequest = { path, status: "loading", data: null, error: null };
  loadJSON(path).then(
    (payload) => {
      if (token !== frameToken) return;
      if (!payload || !Array.isArray(payload.pcs)) {
        state.frameRequest = {
          path,
          status: "failed",
          data: null,
          error: "The frame file is not a viewer-v1 frame document.",
        };
      } else state.frameRequest = { path, status: "ready", data: payload, error: null };
      render();
    },
    (error) => {
      if (token !== frameToken) return;
      state.frameRequest = { path, status: "failed", data: null, error: error.message };
      render();
    },
  );
}

function renderRail(run) {
  const nav = h(
    "nav",
    { "aria-label": "Sections" },
    VIEWS.map(([key, label]) =>
      h(
        "a",
        {
          class: "nav-row",
          href: `#${key}`,
          "aria-current": state.view === key ? "page" : null,
        },
        h("span", null, label),
        h("span", { class: "nav-count" }, formatInt(viewCount(key, run))),
      ),
    ),
  );
  const runs = h(
    "div",
    { class: "stack" },
    h("h6", null, "Timing runs"),
    h(
      "div",
      { class: "runs", role: "radiogroup", "aria-label": "Timing run" },
      data.runs.map((entry) =>
        h(
          "label",
          { class: `run-radio ${entry.id === run.id ? "is-active" : ""}` },
          h("input", {
            type: "radio",
            name: "run",
            value: entry.id,
            "aria-label": `${entry.name}: ${plural(entry.cases.length, "case")}, ${plural(entry.warnings.length, "caution")}`,
            checked: entry.id === run.id ? true : null,
            onchange: () => actions.selectRun(entry.id),
          }),
          h(
            "span",
            null,
            h("span", { class: "run-name" }, entry.name),
            h(
              "span",
              { class: "run-meta" },
              `${plural(entry.cases.length, "case")} · ${plural(entry.warnings.length, "caution")}`,
            ),
          ),
        ),
      ),
    ),
  );
  rail.replaceChildren(
    h(
      "div",
      { class: "wordmark" },
      h("a", { class: "wordmark-title", href: "#overview", style: null }, "Execbench"),
      h(
        "div",
        { class: "wordmark-meta" },
        tag("viewer-v1", "tag-outline tag-mono"),
        h("span", { class: "fine-sm" }, "read-only · local"),
      ),
    ),
    nav,
    runs,
    h(
      "p",
      { class: "fine-sm rail-foot" },
      "Saved results only. No RPC, no execution, no uploads.",
    ),
  );
}

function renderHeader(run) {
  const view = VIEWS.find(([key]) => key === state.view);
  const notes = {
    overview:
      "Per-case distributions of whole-call execution time and gross execution gas. Cases are independent workloads.",
    scaling:
      "Metrics against an exported numeric counter. Points are connected for reading order only.",
    comparisons:
      "Explicit candidate ÷ baseline ratios from the supplied manifest. Nothing is paired by name.",
    explorer:
      "From whole-call measurement to the gas and instruction evidence that supports it.",
    provenance:
      "What the export recorded about the run, the fixture, the host and the diagnostic input.",
  };
  const cautions = run.warnings.length;
  const facts = [
    ["Mode", run.context.benchmark_mode],
    ["Environment", run.context.execution_env],
    ["Pinned block", formatInt(run.context.block_number)],
    ["Quality", cautions ? plural(cautions, "caution") : "no cautions"],
  ];
  const header = h(
    "header",
    { class: "page-header" },
    h(
      "div",
      { class: "page-title" },
      h("p", { class: "kicker" }, `${run.name} · ${run.context.benchmark_mode}`),
      h("h3", null, view ? view[1] : "Results overview"),
      h("p", { class: "muted" }, notes[state.view] ?? ""),
    ),
    h(
      "div",
      { class: "page-facts" },
      h(
        "div",
        { class: "facts" },
        facts.map(([key, value]) =>
          h(
            "div",
            { class: "fact" },
            h("span", { class: "fact-key" }, key),
            h("span", { class: "fact-value" }, value),
          ),
        ),
      ),
      h(
        "a",
        { class: "btn", href: "/summary.json", download: "summary.json" },
        icon("download"),
        "Export summary",
      ),
    ),
  );
  const caution = cautions
    ? h(
        "section",
        { class: "caution", "aria-label": "Measurement cautions" },
        h("h6", null, "Measurement cautions"),
        h(
          "ul",
          null,
          run.warnings.map((warning) => h("li", null, warning)),
        ),
        fine(
          "These are exporter heuristics retained with the run, not errors: the data stays viewable and nothing here is a confidence interval or significance test.",
        ),
      )
    : null;
  return [header, caution];
}

function renderView(run) {
  const context = {
    data,
    run,
    state,
    actions,
    caseById,
    selected: currentCase(run),
    metrics: METRICS,
  };
  switch (state.view) {
    case "scaling":
      return renderScaling(context);
    case "comparisons":
      return renderComparisons(context);
    case "explorer":
      return renderExplorer(context);
    case "provenance":
      return renderProvenance(context);
    default:
      return renderOverview(context);
  }
}

function render() {
  if (!data) return;
  const run = currentRun();
  state.runId = run.id;
  const active = document.activeElement;
  const focusId = active && active.id ? active.id : null;
  const selection =
    active && typeof active.selectionStart === "number"
      ? [active.selectionStart, active.selectionEnd]
      : null;
  renderRail(run);
  main.setAttribute("aria-busy", "false");
  main.replaceChildren(...renderHeader(run), renderView(run));
  if (focusId) {
    const restored = document.getElementById(focusId);
    if (restored) {
      restored.focus({ preventScroll: true });
      if (selection && typeof restored.setSelectionRange === "function") {
        try {
          restored.setSelectionRange(selection[0], selection[1]);
        } catch {
          /* non-text input */
        }
      }
    }
  }
  if (state.scrollTo) {
    const target = document.getElementById(state.scrollTo);
    state.scrollTo = null;
    if (target) {
      target.scrollIntoView({ block: "start" });
      if (target.tabIndex < 0) target.tabIndex = -1;
      target.focus({ preventScroll: true });
    }
  }
}

function fatal(message) {
  main.setAttribute("aria-busy", "false");
  main.replaceChildren(
    h(
      "div",
      { class: "error-panel", role: "alert" },
      h("h4", null, "The export could not be loaded"),
      h("p", null, `summary.json: ${message}`),
      fine(
        "Serve a directory produced by `monad-execbench-viewer export`. Nothing else was fetched.",
      ),
      h(
        "button",
        { class: "btn", type: "button", onclick: () => window.location.reload() },
        icon("refresh"),
        "Retry",
      ),
    ),
  );
}

window.addEventListener("hashchange", () => {
  state.view = viewFromHash(window.location.hash);
  render();
});

try {
  const summary = await loadJSON("/summary.json");
  if (!summary || summary.schema !== SCHEMA) throw new Error("not a viewer-v1 export");
  if (!Array.isArray(summary.runs) || summary.runs.length === 0)
    throw new Error("the export contains no timing runs");
  for (const key of ["comparisons", "profiles"])
    if (!Array.isArray(summary[key])) summary[key] = [];
  data = summary;
  caseById = new Map();
  for (const run of data.runs)
    for (const item of run.cases) caseById.set(item.id, { ...item, run });
  state.view = viewFromHash(window.location.hash);
  state.runId = data.runs[0].id;
  render();
} catch (error) {
  fatal(error.message);
}
