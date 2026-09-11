import {
  h,
  svg,
  blueprint,
  select,
  valueOr,
  note,
  table,
  fine,
  unitLabel,
} from "../dom.js";
import {
  compareBig,
  compareText,
  formatInt,
  formatPct,
  formatUs,
  toBigInt,
  truncateMiddle,
} from "../format.js";
import { METRICS } from "../state.js";

const PLOT = { x0: 46, x1: 740, y0: 268, y1: 22 };
const SERIES_CLASSES = ["accent-700", "accent-400", "neutral-600"];

function metricValue(item, metric) {
  if (metric === "gas") return item.gas;
  return item[metric].median;
}

function formatMetric(value, metric) {
  return metric === "gas" ? formatInt(value) : formatUs(value);
}

/** Scaled Number in [0, 1] for pixels only; labels use exact values. */
function fraction(value, low, high) {
  if (high === low) return 0.5;
  return Number(((value - low) * 1000000n) / (high - low)) / 1000000;
}

function yFraction(value, max) {
  if (max === 0) return 0;
  return Number(value) / max;
}

function gridLabel(max, metric, step) {
  if (metric === "gas") {
    const big = toBigInt(max) ?? 0n;
    return formatInt((big * BigInt(step)) / 4n);
  }
  return formatUs((Number(max) * step) / 4);
}

export function renderScaling({ run, state, actions }) {
  // Counters ordered by how many cases carry them, so the default X axis is
  // the one most of the run can be plotted against.
  const coverage = new Map();
  for (const item of run.cases)
    for (const key of Object.keys(item.counters))
      coverage.set(key, (coverage.get(key) ?? 0) + 1);
  const counters = [...coverage.keys()].sort(
    (a, b) => coverage.get(b) - coverage.get(a) || compareText(a, b),
  );
  const labels = [
    ...new Set(run.cases.flatMap((item) => Object.keys(item.labels))),
  ].sort(compareText);

  if (!counters.length)
    return h(
      "section",
      { class: "view", "aria-label": "Workload scaling" },
      h(
        "div",
        { class: "empty" },
        h("h4", null, "No numeric counters in this run"),
        h(
          "p",
          null,
          "Counters are optional workload metadata supplied in the benchmark label. This dataset is valid without them; there is nothing to plot against.",
        ),
      ),
    );

  const counterX = counters.includes(state.scaling.counterX)
    ? state.scaling.counterX
    : counters[0];
  const metricY = METRICS.some(([key]) => key === state.scaling.metricY)
    ? state.scaling.metricY
    : "cpu";
  const seriesBy = labels.includes(state.scaling.seriesBy)
    ? state.scaling.seriesBy
    : null;
  const metricLabel = METRICS.find(([key]) => key === metricY)[1];
  const update = (patch) =>
    actions.set({ scaling: { counterX, metricY, seriesBy, ...patch } });

  const controls = h(
    "div",
    { class: "chart-controls" },
    select("X · counter", counters.map((key) => [key, key]), counterX, (value) =>
      update({ counterX: value }),
    ),
    select("Y · metric", METRICS, metricY, (value) => update({ metricY: value })),
    select(
      "Series · label",
      [["", "none"], ...labels.map((key) => [key, key])],
      seriesBy ?? "",
      (value) => update({ seriesBy: value || null }),
    ),
  );

  const points = run.cases
    .filter((item) => Object.hasOwn(item.counters, counterX))
    .map((item) => ({
      item,
      x: toBigInt(item.counters[counterX]) ?? 0n,
      raw: item.counters[counterX],
      y: metricValue(item, metricY),
      series: seriesBy ? (item.labels[seriesBy] ?? "(no label)") : "all cases",
    }))
    .sort((a, b) => compareBig(a.x, b.x) || compareText(a.item.name, b.item.name));

  const xs = points.map((point) => point.x);
  const low = xs.reduce((min, x) => (x < min ? x : min), xs[0] ?? 0n);
  const high = xs.reduce((max, x) => (x > max ? x : max), xs[0] ?? 0n);
  const yMax =
    metricY === "gas"
      ? points.reduce((max, point) => {
          const big = toBigInt(point.y) ?? 0n;
          return big > max ? big : max;
        }, 0n)
      : points.reduce((max, point) => Math.max(max, Number(point.y)), 0);
  const yScale = Number(yMax);
  const seriesNames = [...new Set(points.map((point) => point.series))];

  const px = (x) => PLOT.x0 + fraction(x, low, high) * (PLOT.x1 - PLOT.x0);
  const py = (y) => PLOT.y0 - yFraction(y, yScale) * (PLOT.y0 - PLOT.y1);

  const grid = [0, 1, 2, 3, 4].map((step) => {
    const y = PLOT.y0 - (step / 4) * (PLOT.y0 - PLOT.y1);
    return [
      svg("line", { class: "grid", x1: PLOT.x0, x2: PLOT.x1, y1: y, y2: y }),
      svg(
        "text",
        { class: "label", x: PLOT.x0 - 6, y: y + 3.5, "text-anchor": "end" },
        gridLabel(yMax, metricY, step),
      ),
    ];
  });
  const distinct = [...new Set(points.map((point) => point.raw))];
  const labelEvery = Math.max(1, Math.ceil(distinct.length / 12));
  const ticks = distinct.map((raw, index) => {
    const x = px(toBigInt(raw) ?? 0n);
    return [
      svg("line", { class: "axis", x1: x, x2: x, y1: PLOT.y0, y2: PLOT.y0 + 4 }),
      index % labelEvery === 0
        ? svg(
            "text",
            { class: "label", x, y: PLOT.y0 + 15, "text-anchor": "middle" },
            svg("title", null, raw),
            truncateMiddle(raw, 8, 4),
          )
        : null,
    ];
  });
  const series = seriesNames.map((name, index) => {
    const cls = SERIES_CLASSES[index % SERIES_CLASSES.length];
    const own = points.filter((point) => point.series === name);
    const path = own.map((point) => `${px(point.x)},${py(point.y)}`).join(" ");
    return svg(
      "g",
      null,
      own.length > 1
        ? svg("polyline", { class: `series series-${cls}`, points: path })
        : null,
      own.map((point) =>
        svg(
          "rect",
          {
            class: `marker series-${cls}`,
            x: px(point.x) - 4.5,
            y: py(point.y) - 4.5,
            width: 9,
            height: 9,
          },
          svg(
            "title",
            null,
            `${point.item.name} · ${counterX} = ${point.raw} · ${metricLabel} ${formatMetric(point.y, metricY)} · exact ${String(point.y)}`,
          ),
        ),
      ),
    );
  });

  const chart = svg(
    "svg",
    {
      class: "chart",
      viewBox: "0 0 760 300",
      role: "img",
      "aria-label": `${metricLabel} against the ${counterX} counter for ${points.length} cases${seriesBy ? `, one series per ${seriesBy} label` : ""}. Exact values follow in the table.`,
    },
    grid,
    svg("line", { class: "axis", x1: PLOT.x0, x2: PLOT.x1, y1: PLOT.y0, y2: PLOT.y0 }),
    svg("line", { class: "axis", x1: PLOT.x0, x2: PLOT.x0, y1: PLOT.y1, y2: PLOT.y0 }),
    ticks,
    series,
    svg(
      "text",
      { class: "axis-title", x: PLOT.x1, y: 292, "text-anchor": "end" },
      `${counterX} · counter value, no assumed unit`,
    ),
    svg(
      "text",
      { class: "axis-title", x: PLOT.x0, y: 12, "text-anchor": "start" },
      metricY === "gas" ? "Execution gas" : `${metricLabel} · µs`,
    ),
  );

  const legend = h(
    "div",
    { class: "legend" },
    seriesNames.map((name, index) =>
      h(
        "span",
        { class: `c-${SERIES_CLASSES[index % SERIES_CLASSES.length]}` },
        h("i", { class: "swatch", "aria-hidden": "true" }),
        h("span", { class: "muted" }, seriesBy ? `${seriesBy}: ${name}` : name),
      ),
    ),
  );

  const rows = points.map((point) => ({
    cells: [
      h("span", { class: "wrap-any" }, point.item.name),
      h("span", { class: "mono" }, point.raw),
      valueOr(formatMetric(point.y, metricY)),
      formatInt(point.item.repetitions),
      valueOr(formatPct(point.item.cpu.cv)),
    ],
  }));

  return h(
    "section",
    { class: "view", "aria-label": "Workload scaling" },
    controls,
    blueprint({ class: "stack" }, chart, legend),
    h(
      "div",
      { class: "table-wrap" },
      table({
        caption: "Exact values plotted above",
        columns: [
          { label: "Case" },
          { label: counterX },
          {
            label: metricY === "gas" ? "Gas" : unitLabel(metricLabel, "µs"),
            class: "num",
          },
          { label: "Repetitions", class: "num" },
          { label: "CPU CV", class: "num" },
        ],
        rows,
      }),
    ),
    points.length < run.cases.length
      ? fine(
          `${formatInt(run.cases.length - points.length)} cases without the ${counterX} counter are omitted from the plot.`,
        )
      : null,
    note(
      "Counters are arbitrary unsigned metadata shown as exact decimal strings, with no unit or token meaning. Points are connected in counter order for reading only: no scaling law is fitted or implied.",
    ),
  );
}
