import { h, blueprint, tag, valueOr, note, table, geometry } from "../dom.js";
import {
  formatChange,
  formatInt,
  formatRatio,
  formatUs,
  isUnavailable,
} from "../format.js";

const MARKER = (1 / 1.5) * 100;

function ratioCell(ratio) {
  const width = isUnavailable(ratio)
    ? 0
    : Math.max(0, Math.min(100, (Number(ratio) / 1.5) * 100));
  const bar = h(
    "div",
    { class: "bar", "aria-hidden": "true" },
    geometry(h("i"), { width: `${width}%` }),
    geometry(h("b"), { left: `${MARKER}%` }),
  );
  return h(
    "div",
    { class: "stack" },
    bar,
    h(
      "span",
      { class: "bar-caption" },
      isUnavailable(ratio) ? valueOr(null) : `${formatRatio(ratio)} · 1.00× marker`,
    ),
  );
}

function identity(role, entry, cls) {
  return h(
    "div",
    { class: `identity ${cls}` },
    h("span", { class: "identity-role" }, role),
    h("span", { class: "identity-name" }, entry ? entry.name : "unknown case"),
    entry
      ? h("span", { class: "mono muted" }, `${entry.run.name} · ${entry.id}`)
      : null,
  );
}

export function renderComparisons({ data, caseById }) {
  if (!data.comparisons.length)
    return h(
      "section",
      { class: "view", "aria-label": "Comparisons" },
      h(
        "div",
        { class: "empty" },
        h("h4", null, "No comparisons supplied"),
        h(
          "p",
          null,
          "Pairings come from an explicit comparisons-v1 manifest passed to the exporter. They are never inferred from case names, labels or run order.",
        ),
      ),
    );

  const cards = data.comparisons.map((comparison) => {
    const baseline = caseById.get(comparison.baseline) ?? null;
    const candidate = caseById.get(comparison.candidate) ?? null;
    const metrics = [
      ["Execution gas", baseline?.gas, candidate?.gas, comparison.gas_ratio, formatInt],
      [
        "CPU median",
        baseline?.cpu.median,
        candidate?.cpu.median,
        comparison.cpu_ratio,
        formatUs,
      ],
      [
        "Wall median",
        baseline?.wall.median,
        candidate?.wall.median,
        comparison.wall_ratio,
        formatUs,
      ],
    ];
    return blueprint(
      { class: "comparison" },
      h(
        "div",
        { class: "comparison-head" },
        h("h4", { class: "comparison-name" }, comparison.name),
        tag(`mode ${comparison.mode}`, "tag-neutral"),
        h("span", { class: "ratio-note num" }, "ratio = candidate ÷ baseline"),
      ),
      h(
        "div",
        { class: "identities" },
        identity("Baseline", baseline, "baseline"),
        identity("Candidate", candidate, "candidate"),
      ),
      h(
        "div",
        { class: "table-wrap" },
        table({
          caption: `Metrics for ${comparison.name}`,
          columns: [
            { label: "Metric" },
            { label: "Baseline", class: "num" },
            { label: "Candidate", class: "num" },
            { label: "Ratio" },
            { label: "Change", class: "num" },
          ],
          rows: metrics.map(([label, left, right, ratio, format]) => ({
            cells: [
              label,
              valueOr(isUnavailable(left) ? null : format(left)),
              valueOr(isUnavailable(right) ? null : format(right)),
              ratioCell(ratio),
              valueOr(formatChange(ratio)),
            ],
          })),
        }),
      ),
    );
  });

  return h(
    "section",
    { class: "view", "aria-label": "Comparisons" },
    cards,
    note(
      "Validation at export requires matching mode, fixture and block identity, runner and client revisions, binary, compiler build, host context and root status; incompatible pairs are rejected rather than badged. CPU and wall ratios use medians. A ratio is a measured quotient of two medians on the recorded host, not a statistical claim, and matching context does not prove functional equivalence.",
    ),
  );
}
