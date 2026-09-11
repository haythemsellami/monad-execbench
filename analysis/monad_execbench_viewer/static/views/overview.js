import {
  h,
  icon,
  blueprint,
  tag,
  statusTag,
  valueOr,
  note,
  table,
  muted,
  unitLabel,
} from "../dom.js";
import {
  compareBig,
  compareNumber,
  compareText,
  formatInt,
  formatPct,
  formatUs,
  isUnavailable,
} from "../format.js";
import { SORT_KEYS } from "../state.js";

const COLUMNS = [
  { key: "name", label: "Case name" },
  { key: "status", label: "Root status" },
  { key: "gas", label: "Gas", class: "num" },
  { key: "cpu", label: "CPU median", unit: "µs", class: "num" },
  { key: "wall", label: "Wall median", unit: "µs", class: "num" },
  { key: "cv", label: "CPU CV", class: "num" },
  { key: "reps", label: "Reps", class: "num" },
  { key: "diagnostics", label: "Diagnostics" },
];

function matchesSearch(item, query) {
  if (!query) return true;
  const haystack = [
    item.name,
    ...Object.entries(item.labels).flat(),
    ...Object.entries(item.counters).flat(),
  ]
    .join("\n")
    .toLowerCase();
  return haystack.includes(query);
}

function matchesChip(item, chip) {
  if (!chip) return true;
  return Object.hasOwn(item.labels, chip.key) && item.labels[chip.key] === chip.value;
}

function sortCases(cases, key, dir) {
  const sortKey = SORT_KEYS.includes(key) ? key : "name";
  const sign = dir === "desc" ? -1 : 1;
  const compare = {
    name: (a, b) => compareText(a.name, b.name),
    status: (a, b) => compareText(a.status, b.status),
    gas: (a, b) => compareBig(a.gas, b.gas),
    cpu: (a, b) => compareNumber(a.cpu.median, b.cpu.median),
    wall: (a, b) => compareNumber(a.wall.median, b.wall.median),
    cv: (a, b) => compareNumber(a.cpu.cv, b.cpu.cv),
    reps: (a, b) => compareBig(a.repetitions, b.repetitions),
    diagnostics: (a, b) => compareText(a.profile ?? "", b.profile ?? ""),
  }[sortKey];
  return [...cases].sort(
    (a, b) => sign * compare(a, b) || compareText(a.name, b.name),
  );
}

function rangeCard(title, values, format, noteText) {
  const present = values.filter((value) => !isUnavailable(value));
  let text;
  if (!present.length) text = null;
  else {
    const sorted = [...present].sort((a, b) => compareNumber(a, b));
    const low = format(sorted[0]);
    const high = format(sorted[sorted.length - 1]);
    text = low === high ? low : `${low} – ${high}`;
  }
  return blueprint(
    { class: "metric" },
    h("h6", null, title),
    h("p", { class: "metric-value small num" }, valueOr(text)),
    h("p", { class: "metric-note" }, noteText),
  );
}

function gasRange(cases) {
  if (!cases.length) return null;
  const sorted = [...cases].sort((a, b) => compareBig(a.gas, b.gas));
  const low = formatInt(sorted[0].gas);
  const high = formatInt(sorted[sorted.length - 1].gas);
  return low === high ? low : `${low} – ${high}`;
}

export function renderOverview({ run, state, actions }) {
  const query = state.search.trim().toLowerCase();
  const filtered = run.cases.filter(
    (item) => matchesSearch(item, query) && matchesChip(item, state.labelChip),
  );
  const sorted = sortCases(filtered, state.sortKey, state.sortDir);
  const chips = [];
  const seen = new Set();
  for (const item of run.cases)
    for (const [key, value] of Object.entries(item.labels)) {
      const id = JSON.stringify([key, value]);
      if (!seen.has(id)) {
        seen.add(id);
        chips.push({ key, value });
      }
    }

  const cards = h(
    "div",
    { class: "cards" },
    blueprint(
      { class: "metric" },
      h("h6", null, "Cases in run"),
      h("p", { class: "metric-value num" }, formatInt(run.cases.length)),
      h("p", { class: "metric-note" }, "Independent workloads. Never summed."),
    ),
    blueprint(
      { class: "metric" },
      h("h6", null, "Execution gas range"),
      h("p", { class: "metric-value small num" }, valueOr(gasRange(run.cases))),
      h("p", { class: "metric-note" }, "Lowest to highest gross execution gas across cases."),
    ),
    rangeCard(
      "CPU median range",
      run.cases.map((item) => item.cpu.median),
      formatUs,
      "Lowest to highest per-case CPU median, µs per execution.",
    ),
    rangeCard(
      "CPU CV range",
      run.cases.map((item) => item.cpu.cv),
      formatPct,
      "Coefficient of variation of CPU repetition averages; unavailable with one repetition.",
    ),
  );

  const filters = h(
    "div",
    { class: "filters", role: "search" },
    h(
      "label",
      { class: "search" },
      h("span", { class: "visually-hidden" }, "Search cases by name, label or counter"),
      icon("search"),
      h("input", {
        id: "search",
        type: "search",
        placeholder: "Search name, labels, counters",
        value: state.search,
        autocomplete: "off",
        oninput: (event) => actions.set({ search: event.target.value }),
      }),
    ),
    chips.length
      ? h(
          "div",
          { class: "chips", role: "group", "aria-label": "Filter by label" },
          chips.map((chip) => {
            const active =
              state.labelChip &&
              state.labelChip.key === chip.key &&
              state.labelChip.value === chip.value;
            return h(
              "button",
              {
                type: "button",
                class: "chip",
                "aria-pressed": active ? "true" : "false",
                onclick: () => actions.set({ labelChip: active ? null : chip }),
              },
              `${chip.key}: ${chip.value}`,
            );
          }),
        )
      : null,
    h(
      "span",
      { class: "count", "aria-live": "polite" },
      `${formatInt(sorted.length)} of ${formatInt(run.cases.length)}`,
    ),
  );

  const columns = COLUMNS.map((column) => ({
    ...column,
    head: h(
      "button",
      {
        type: "button",
        class: "sort",
        "aria-sort":
          state.sortKey === column.key
            ? state.sortDir === "desc"
              ? "descending"
              : "ascending"
            : null,
        onclick: () =>
          actions.set(
            state.sortKey === column.key
              ? { sortDir: state.sortDir === "asc" ? "desc" : "asc" }
              : { sortKey: column.key, sortDir: "asc" },
          ),
      },
      column.unit ? unitLabel(column.label, column.unit) : column.label,
      state.sortKey === column.key
        ? h("span", { class: "sort-glyph", "aria-hidden": "true" }, state.sortDir === "desc" ? "▼" : "▲")
        : null,
    ),
  }));

  const rows = sorted.map((item) => {
    const sub = [
      ...Object.entries(item.labels).map(([key, value]) => `${key}: ${value}`),
      ...Object.entries(item.counters).map(([key, value]) => `${key} = ${value}`),
    ].join(" · ");
    const cv = item.cpu.cv;
    return {
      item,
      cells: [
        h(
          "div",
          null,
          h(
            "button",
            {
              type: "button",
              class: "row-link cell-title",
              onclick: () => actions.selectCase(item.id, true),
            },
            item.name,
          ),
          sub ? h("div", { class: "cell-sub" }, sub) : null,
        ),
        statusTag(item.status),
        formatInt(item.gas),
        valueOr(formatUs(item.cpu.median)),
        valueOr(formatUs(item.wall.median)),
        {
          node: valueOr(formatPct(cv)),
          class: !isUnavailable(cv) && Number(cv) > 0.05 ? "cv-high" : null,
        },
        formatInt(item.repetitions),
        item.profile ? tag(item.profile, "tag-accent tag-mono") : muted("—"),
      ],
    };
  });

  const body = sorted.length
    ? h(
        "div",
        { class: "table-wrap table-wide" },
        table({
          columns,
          rows,
          caption: "Cases in the selected timing run",
          rowAttrs: (row) => ({
            class: `clickable ${row.item.id === state.caseId ? "is-selected" : ""}`,
            onclick: (event) => {
              if (event.target.closest("button")) return;
              actions.selectCase(row.item.id, true);
            },
          }),
        }),
      )
    : h(
        "div",
        { class: "empty" },
        h("h4", null, "No cases match these filters"),
        h("p", null, `${formatInt(run.cases.length)} cases are loaded for this run.`),
        h(
          "button",
          {
            type: "button",
            class: "btn",
            onclick: () => actions.set({ search: "", labelChip: null }),
          },
          icon("x"),
          "Clear filters",
        ),
      );

  return h(
    "section",
    { class: "view", "aria-label": "Results overview" },
    cards,
    filters,
    body,
    note(
      "Gas is gross direct-call execution gas before refunds and excludes intrinsic gas: not receipt gas and not fees. CPU and wall are medians of repetition averages on the recorded host, in µs per execution. Cases are independent workloads and are deliberately not summed.",
    ),
  );
}
