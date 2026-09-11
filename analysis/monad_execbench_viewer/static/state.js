// Client state. Every key has a valid default; accessors validate before
// dereferencing. Nothing here is persisted or shared.

export const VIEWS = [
  ["overview", "Results overview"],
  ["scaling", "Workload scaling"],
  ["comparisons", "Comparisons"],
  ["explorer", "Case explorer"],
  ["provenance", "Provenance"],
];

export const METRICS = [
  ["cpu", "CPU median"],
  ["wall", "Wall median"],
  ["gas", "Gas"],
];

export const SORT_KEYS = [
  "name",
  "status",
  "gas",
  "cpu",
  "wall",
  "cv",
  "reps",
  "diagnostics",
];

export const PC_PAGE_SIZE = 12;
export const TREE_PAGE_SIZE = 200;

export const state = {
  view: "overview",
  runId: null,
  caseId: null,
  frameId: null,
  frameViz: "icicle",
  coverageMetric: "gas",
  search: "",
  labelChip: null,
  sortKey: "name",
  sortDir: "asc",
  scaling: { counterX: null, metricY: "cpu", seriesBy: null },
  selectedSourceIndex: 0,
  pcPage: 1,
  treePage: 1,
  caseRequest: null,
  frameRequest: null,
  copied: null,
  scrollTo: null,
};

export function isView(value) {
  return VIEWS.some(([key]) => key === value);
}

export function viewFromHash(hash) {
  const key = String(hash ?? "").replace(/^#\/?/, "");
  return isView(key) ? key : "overview";
}

export function resetForRun() {
  state.caseId = null;
  state.frameId = null;
  state.caseRequest = null;
  state.frameRequest = null;
  state.selectedSourceIndex = 0;
  state.pcPage = 1;
  state.treePage = 1;
  state.labelChip = null;
  state.scaling = { counterX: null, metricY: state.scaling.metricY, seriesBy: null };
}

export function resetForCase() {
  state.frameId = null;
  state.caseRequest = null;
  state.frameRequest = null;
  state.selectedSourceIndex = 0;
  state.pcPage = 1;
  state.treePage = 1;
}

export function resetForFrame() {
  state.frameRequest = null;
  state.pcPage = 1;
}
