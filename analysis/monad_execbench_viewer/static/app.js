const $ = (id) => document.getElementById(id);
const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = String(text);
  if (className) el.className = className;
  return el;
};
const fmt = (value) =>
  value === null || value === undefined
    ? "n/a"
    : typeof value === "number"
      ? value.toLocaleString(undefined, { maximumFractionDigits: 3 })
      : String(value);
const pct = (value) =>
  value === null || value === undefined ? "n/a" : `${fmt(value * 100)}%`;
let dataset;
let selected;
let requestId = 0;
let frameRequestId = 0;
const colors = [
  "#00766a",
  "#255db7",
  "#a44591",
  "#a86716",
  "#6c54ac",
  "#316976",
];
const opcodeNames = {
  0: "STOP",
  1: "ADD",
  2: "MUL",
  3: "SUB",
  4: "DIV",
  16: "LT",
  17: "GT",
  20: "EQ",
  21: "ISZERO",
  22: "AND",
  23: "OR",
  24: "XOR",
  25: "NOT",
  27: "SHL",
  28: "SHR",
  32: "KECCAK256",
  48: "ADDRESS",
  49: "BALANCE",
  51: "CALLER",
  53: "CALLDATALOAD",
  54: "CALLDATASIZE",
  55: "CALLDATACOPY",
  59: "EXTCODESIZE",
  61: "RETURNDATASIZE",
  62: "RETURNDATACOPY",
  63: "EXTCODEHASH",
  64: "BLOCKHASH",
  80: "POP",
  81: "MLOAD",
  82: "MSTORE",
  83: "MSTORE8",
  84: "SLOAD",
  85: "SSTORE",
  86: "JUMP",
  87: "JUMPI",
  88: "PC",
  89: "MSIZE",
  90: "GAS",
  91: "JUMPDEST",
  92: "TLOAD",
  93: "TSTORE",
  94: "MCOPY",
  95: "PUSH0",
  240: "CREATE",
  241: "CALL",
  242: "CALLCODE",
  243: "RETURN",
  244: "DELEGATECALL",
  245: "CREATE2",
  250: "STATICCALL",
  253: "REVERT",
  254: "INVALID",
  255: "SELFDESTRUCT",
};
const opcode = (code) =>
  `${opcodeNames[code] || (code >= 96 && code <= 127 ? `PUSH${code - 95}` : code >= 128 && code <= 143 ? `DUP${code - 127}` : code >= 144 && code <= 159 ? `SWAP${code - 143}` : code >= 160 && code <= 164 ? `LOG${code - 160}` : "OP")} · 0x${code.toString(16).padStart(2, "0")}`;
const svgNode = (tag, attrs, text) => {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) =>
    el.setAttribute(key, String(value)),
  );
  if (text !== undefined) el.textContent = text;
  return el;
};
const allCases = () =>
  dataset.runs.flatMap((run) => run.cases.map((item) => ({ ...item, run })));
const current = () => dataset.runs.find((run) => run.id === $("run").value);
function error(message) {
  $("error").hidden = false;
  $("error").textContent = message;
}
async function json(path) {
  const response = await fetch(path);
  if (!response.ok)
    throw new Error(`Unable to load results (${response.status}).`);
  return response.json();
}
function definition(parent, key, value) {
  parent.append(
    node("dt", key),
    node("dd", typeof value === "object" ? JSON.stringify(value) : value),
  );
}
function makeTable(headers, rows) {
  const table = node("table");
  const head = node("thead");
  const tr = node("tr");
  headers.forEach((text) => tr.append(node("th", text)));
  head.append(tr);
  const body = node("tbody");
  for (const values of rows) {
    const row = node("tr");
    values.forEach((value) => {
      const td = node("td");
      td.append(
        value instanceof Node ? value : document.createTextNode(String(value)),
      );
      row.append(td);
    });
    body.append(row);
  }
  table.append(head, body);
  return table;
}
function render() {
  const run = current();
  const query = $("search").value.toLowerCase();
  const cases = run.cases.filter((item) =>
    JSON.stringify([item.name, item.labels, item.counters])
      .toLowerCase()
      .includes(query),
  );
  $("metrics").replaceChildren(
    ...[
      [run.context.benchmark_mode, "Execution mode"],
      [cases.length, "Visible cases"],
      [run.context.block_number, "Replay block"],
      [run.context.requested_repetitions, "Repetitions / case"],
    ].map(([value, label]) => {
      const el = node("div", undefined, "metric");
      el.append(node("strong", value), node("span", label));
      return el;
    }),
  );
  $("warnings").replaceChildren(
    ...(run.warnings.length
      ? run.warnings
      : [
          "No automatic quality warnings. Host control and correctness still require independent review.",
        ]
    ).map((value) => node("li", value)),
  );
  $("quality").open = run.warnings.length > 0;
  $("cases")
    .querySelector("tbody")
    .replaceChildren(
      ...cases.map((item) => {
        const tr = node("tr");
        const td = node("td");
        const button = node("button", item.name);
        button.addEventListener("click", () => inspect(item));
        td.append(button);
        tr.append(td);
        const status = node("td");
        status.append(node("span", item.status, `tag ${item.status}`));
        tr.append(status);
        [
          fmt(item.gas),
          fmt(item.cpu.median),
          fmt(item.wall.median),
          pct(item.cpu.cv),
          fmt(item.repetitions),
        ].forEach((value) => tr.append(node("td", value)));
        return tr;
      }),
    );
  $("empty").hidden = cases.length > 0;
  $("provenance").replaceChildren();
  definition($("provenance"), "Input SHA-256", run.sha256);
  Object.entries(run.context).forEach(([key, value]) =>
    definition($("provenance"), key, value),
  );
  renderComparisons();
  renderChart(cases);
}
function renderComparisons() {
  const lookup = new Map(allCases().map((item) => [item.id, item]));
  $("comparison-empty").hidden = dataset.comparisons.length > 0;
  $("comparison-table").replaceChildren(
    makeTable(
      [
        "Comparison",
        "Mode",
        "Baseline",
        "Candidate",
        "Gas ratio",
        "CPU ratio",
        "Wall ratio",
      ],
      dataset.comparisons.map((item) => [
        item.name,
        item.mode,
        lookup.get(item.baseline).name,
        lookup.get(item.candidate).name,
        ...[item.gas_ratio, item.cpu_ratio, item.wall_ratio].map((value) =>
          value === null ? "n/a" : `${fmt(value)}×`,
        ),
      ]),
    ),
  );
}
async function inspect(item) {
  selected = item;
  const request = ++requestId;
  $("case-prompt").hidden = true;
  const detail = $("case-detail");
  detail.replaceChildren(node("h3", item.name));
  detail.append(
    makeTable(
      [
        "Metric",
        "Median",
        "Mean",
        "Minimum",
        "Maximum",
        "Std. deviation",
        "CV",
      ],
      [
        ["CPU µs", item.cpu],
        ["Wall µs", item.wall],
      ].map(([label, dist]) => [
        label,
        ...[
          dist.median,
          dist.mean,
          dist.minimum,
          dist.maximum,
          dist.stddev,
        ].map(fmt),
        pct(dist.cv),
      ]),
    ),
  );
  const labels = node("dl");
  Object.entries({ ...item.labels, ...item.counters }).forEach(([key, value]) =>
    definition(labels, key, value),
  );
  detail.append(labels);
  detail.append(
    node(
      "p",
      `${fmt(item.iterations)} calibrated executions. Each repetition is an average, not an individual transaction latency sample.`,
      "muted",
    ),
  );
  if (!item.profile)
    detail.append(node("p", "No diagnostic profile attached to this case."));
  $("explorer").scrollIntoView({ behavior: "smooth", block: "start" });
  if (item.profile) {
    const loading = node("p", "Loading case diagnostics…", "profile-loading");
    detail.append(loading);
    try {
      const profile = await json(`/${item.profile}.json`);
      if (request !== requestId) return;
      loading.remove();
      renderProfile(detail, profile, request);
    } catch (reason) {
      if (request === requestId) {
        loading.textContent = reason.message;
        loading.setAttribute("role", "alert");
      }
    }
  }
}
function renderChart(cases) {
  const section = $("counter-chart");
  section.replaceChildren();
  const counters = [
    ...new Set(cases.flatMap((item) => Object.keys(item.counters))),
  ];
  section.hidden = counters.length === 0 || cases.length === 0;
  if (section.hidden) return;
  section.append(node("h2", "Workload scaling"));
  const controls = node("div", undefined, "chart-controls");
  function select(label, options) {
    const wrapper = node("label", label);
    const input = node("select");
    options.forEach(([value, text]) => {
      const option = node("option", text);
      option.value = value;
      input.append(option);
    });
    wrapper.append(input);
    controls.append(wrapper);
    return input;
  }
  const x = select(
    "Counter",
    counters.map((key) => [key, key]),
  );
  const y = select("Metric", [
    ["cpu", "CPU median · µs"],
    ["wall", "Wall median · µs"],
    ["gas", "Execution gas"],
  ]);
  const group = select("Group by label", [
    ["", "All cases"],
    ...[...new Set(cases.flatMap((item) => Object.keys(item.labels)))].map(
      (key) => [key, key],
    ),
  ]);
  const chart = node("div");
  section.append(controls, chart);
  function draw() {
    chart.replaceChildren();
    const points = cases
      .filter((item) => item.counters[x.value] !== undefined)
      .map((item) => ({
        item,
        x: BigInt(item.counters[x.value]),
        y: y.value === "gas" ? Number(item.gas) : item[y.value].median,
        group: group.value
          ? (item.labels[group.value] ?? "(unlabelled)")
          : "All cases",
      }));
    if (!points.length) return;
    const sorted = points
      .map((point) => point.x)
      .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    const lo = sorted[0],
      hi = sorted.at(-1);
    const maxY = Math.max(1, ...points.map((point) => point.y));
    const chartSvg = svgNode("svg", {
      viewBox: "0 0 900 300",
      role: "img",
      "aria-label": `${y.selectedOptions[0].textContent} by ${x.value}. Exact values are available in the case details.`,
      class: "chart",
    });
    chartSvg.append(
      svgNode("line", { x1: 90, y1: 245, x2: 860, y2: 245, class: "axis" }),
      svgNode("line", { x1: 90, y1: 20, x2: 90, y2: 245, class: "axis" }),
    );
    [0, 0.25, 0.5, 0.75, 1].forEach((fraction) =>
      chartSvg.append(
        svgNode(
          "text",
          { x: 80, y: 249 - fraction * 220, "text-anchor": "end" },
          fmt(maxY * fraction),
        ),
      ),
    );
    chartSvg.append(
      svgNode("text", { x: 90, y: 275 }, String(lo)),
      svgNode("text", { x: 860, y: 275, "text-anchor": "end" }, String(hi)),
    );
    const groups = [...new Set(points.map((point) => point.group))];
    for (const point of points) {
      const px =
        hi === lo
          ? 475
          : 90 + Number(((point.x - lo) * 770000n) / (hi - lo)) / 1000;
      const py = 245 - (point.y / maxY) * 220;
      const circle = svgNode("circle", {
        cx: px,
        cy: py,
        r: 6,
        fill: colors[groups.indexOf(point.group) % colors.length],
        class: "point",
      });
      circle.append(
        svgNode(
          "title",
          {},
          `${point.item.name}: ${x.value}=${point.x}; ${fmt(point.y)}`,
        ),
      );
      chartSvg.append(circle);
    }
    const legend = node("div", undefined, "legend");
    groups.forEach((name, index) => {
      const label = node("span");
      const swatch = svgNode("svg", {
        width: 12,
        height: 12,
        "aria-hidden": "true",
      });
      swatch.append(
        svgNode("circle", {
          cx: 6,
          cy: 6,
          r: 5,
          fill: colors[index % colors.length],
        }),
      );
      label.append(swatch, document.createTextNode(name));
      legend.append(label);
    });
    chart.append(
      chartSvg,
      legend,
      node(
        "p",
        "Points show repetition-average medians, not individual transaction latency or a fitted scaling model.",
        "muted",
      ),
    );
  }
  [x, y, group].forEach((input) => input.addEventListener("change", draw));
  draw();
}
function renderProfile(parent, profile, request) {
  parent.append(
    node("h3", "Diagnostic evidence"),
    node(
      "p",
      "Interpreter frames, not a complete RPC trace. Recipient is storage context; precompile work is charged to the calling opcode. Gas is gross, before refunds.",
      "muted",
    ),
  );
  const coverage = node("div", undefined, "coverage");
  Object.entries(profile.coverage).forEach(([kind, value]) =>
    coverage.append(
      node(
        "span",
        `${kind}: ${fmt(value.gas)} gas · ${pct(profile.gas ? Number(value.gas) / Number(profile.gas) : null)}`,
      ),
    ),
  );
  parent.append(coverage);
  parent.append(
    node(
      "p",
      `${fmt(profile.steps)} instruction visits · ${profile.frames.length} VM frames · ${fmt(profile.outside_vm_gas)} gas outside VM frames.`,
      "muted",
    ),
  );
  const layout = node("div", undefined, "explorer-grid"),
    left = node("div"),
    right = node("div");
  left.append(node("h3", "Call-frame tree"));
  const tree = node("div", undefined, "frame-list");
  left.append(tree);
  const opcodeTable = node("div", undefined, "table-scroll bounded-table");
  opcodeTable.append(
    makeTable(
      ["Opcode", "Self gas", "Visits"],
      profile.opcodes.map((item) => [
        opcode(item.opcode),
        fmt(item.gas),
        fmt(item.steps),
      ]),
    ),
  );
  right.append(node("h3", "Opcode gas across the call"), opcodeTable);
  layout.append(left, right);
  parent.append(layout);
  const framePanel = node("section");
  framePanel.id = "frame-pcs";
  parent.append(framePanel);
  const sourcePanel = node("section");
  parent.append(sourcePanel);
  const branches = new Map();
  for (const frame of profile.frames) {
    const branch = node("details", undefined, "frame");
    branch.open = frame.parent === null;
    const contract =
      frame.artifact_match.candidates.length === 1
        ? frame.artifact_match.candidates[0]
        : frame.code_hash;
    branch.append(
      node(
        "summary",
        `#${frame.id} ${contract} · ${frame.status} · ${fmt(frame.gas_used)} gas`,
      ),
    );
    const content = node("div");
    const button = node(
      "button",
      `Inspect #${frame.id} · self ${fmt(frame.self_gas)} gas`,
    );
    button.addEventListener("click", () => showFrame(frame));
    content.append(button);
    branch.append(content);
    branches.set(frame.id, content);
    (frame.parent === null ? tree : branches.get(frame.parent)).append(branch);
  }
  const sourceTable = node("div", undefined, "table-scroll bounded-table");
  sourceTable.append(
    makeTable(
      ["Source hotspot", "Self gas", "Visits"],
      profile.source_totals.map((item) => {
        const source = profile.sources[item.source];
        const button = node(
          "button",
          `${source.file}:${source.line} · ${source.function?.name ?? "compiler range"}`,
          "source-button",
        );
        button.addEventListener("click", () => showSource(source));
        return [button, fmt(item.gas), fmt(item.steps)];
      }),
    ),
  );
  parent.append(
    node("h3", "Solidity / generated-source hotspots"),
    node(
      "p",
      "Compiler source spans can overlap or be inlined. These are gas/count attributions—not function timings or invocation counts.",
      "muted",
    ),
    sourceTable,
  );
  if (!profile.source_totals.length)
    parent.append(
      node(
        "p",
        "No mapped source spans. Supply attribution output with matching compiler build-info to enable source exploration.",
      ),
    );
  const provenance = dataset.profiles.find(
    (item) => item.id === profile.id.split("-")[0],
  );
  if (provenance) {
    const section = node("details");
    section.append(
      node("summary", "Diagnostic provenance"),
      node(
        "p",
        "Imported source labels are consistency-checked, not recompiled or independently authenticated. Re-run the attribution tool with matching build-info to regenerate mapping evidence.",
        "notice",
      ),
    );
    const values = node("dl");
    Object.entries(provenance).forEach(([key, value]) =>
      definition(values, key, value),
    );
    section.append(values);
    parent.append(section);
  }
  function showSource(source) {
    sourcePanel.replaceChildren(
      node("h3", `${source.file}:${source.line}:${source.column_bytes}`),
      node(
        "p",
        `${source.kind} · source bytes ${source.start}–${BigInt(source.start) + BigInt(source.length)} · ${source.function?.name ?? "compiler range"}`,
        "muted",
      ),
      node("pre", source.snippet),
      node("p", `Source SHA-256: ${source.source_sha256}`, "muted"),
    );
    sourcePanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function showFrame(frame) {
    const frameRequest = ++frameRequestId;
    framePanel.replaceChildren(node("h3", `Frame #${frame.id}`));
    const info = node("dl");
    [
      "recipient",
      "sender",
      "selector",
      "code_hash",
      "code_kind",
      "status",
      "gas_used",
      "self_gas",
      "steps",
    ].forEach((key) => definition(info, key, frame[key]));
    definition(info, "artifact_match", frame.artifact_match);
    framePanel.append(info);
    const loading = node("p", "Loading bytecode positions…", "profile-loading");
    framePanel.append(loading);
    try {
      const detail = await json(`/${frame.file}`);
      if (request !== requestId || frameRequest !== frameRequestId) return;
      loading.remove();
      const scroll = node("div", undefined, "table-scroll");
      scroll.append(
        makeTable(
          ["PC", "Opcode", "Self gas", "Visits", "Source / reason"],
          detail.pcs.map((pc) => {
            let location = pc.mapping;
            if (pc.source !== null) {
              const source = profile.sources[pc.source];
              location = node(
                "button",
                `${source.file}:${source.line}`,
                "source-button",
              );
              location.addEventListener("click", () => showSource(source));
            }
            return [
              fmt(pc.pc),
              opcode(pc.opcode),
              fmt(pc.gas),
              fmt(pc.count),
              location,
            ];
          }),
        ),
      );
      framePanel.append(scroll);
    } catch (reason) {
      if (request === requestId && frameRequest === frameRequestId) {
        loading.textContent = reason.message;
        loading.setAttribute("role", "alert");
      }
    }
  }
}
$("run").addEventListener("change", () => {
  ++requestId;
  selected = null;
  $("case-detail").replaceChildren();
  $("case-prompt").hidden = false;
  render();
});
$("search").addEventListener("input", render);
try {
  dataset = await json("/summary.json");
  if (dataset.schema !== "monad-execbench/viewer-v1" || !dataset.runs.length)
    throw new Error("Unsupported or empty viewer export.");
  $("run").replaceChildren(
    ...dataset.runs.map((run) => {
      const option = node(
        "option",
        `${run.name} · ${run.context.benchmark_mode}`,
      );
      option.value = run.id;
      return option;
    }),
  );
  render();
} catch (reason) {
  error(reason.message);
}
