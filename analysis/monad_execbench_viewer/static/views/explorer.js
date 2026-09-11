import {
  h,
  icon,
  blueprint,
  tag,
  statusTag,
  valueOr,
  note,
  table,
  kv,
  fine,
  loading,
  segmented,
  muted,
  geometry,
  unitLabel,
} from "../dom.js";
import {
  bigSum,
  formatDecimal,
  formatInt,
  formatPct,
  formatUs,
  isUnavailable,
  opcodeHex,
  opcodeName,
  plural,
  share,
  toBigInt,
  truncateMiddle,
} from "../format.js";
import { PC_PAGE_SIZE, TREE_PAGE_SIZE } from "../state.js";

const OPCODE_ROWS = 12;
const MATCH_VARIANT = {
  exact: "tag-accent",
  masked: "tag-outline",
  ambiguous: "tag-dashed",
  unmatched: "tag-neutral",
  "creation-code": "tag-neutral",
};

function matchTag(match) {
  const status = match && typeof match.status === "string" ? match.status : "unknown";
  return tag(status, MATCH_VARIANT[status] ?? "tag-neutral");
}

function frameTree(frames) {
  const byId = new Map();
  const children = new Map();
  for (const frame of frames) {
    byId.set(frame.id, frame);
    children.set(frame.id, []);
  }
  for (const frame of frames)
    if (frame.parent !== null && children.has(frame.parent))
      children.get(frame.parent).push(frame);
  const root = frames.find((frame) => frame.parent === null) ?? null;
  const order = [];
  const visit = (frame) => {
    order.push(frame);
    for (const child of children.get(frame.id)) visit(child);
  };
  if (root) visit(root);
  return { byId, children, root, order };
}

/* ---------- Case list ---------- */

function caseList({ run, state, actions }) {
  return h(
    "div",
    { class: "case-list", role: "list", "aria-label": "Cases" },
    run.cases.map((item) =>
      h(
        "button",
        {
          type: "button",
          class: "case-item",
          role: "listitem",
          "aria-current": item.id === state.caseId ? "true" : null,
          "aria-label": `${item.name}, ${item.status}, ${formatInt(item.gas)} gas${item.profile ? ", profile attached" : ""}`,
          onclick: () => actions.selectCase(item.id),
        },
        h("span", { class: "name" }, item.name),
        h(
          "span",
          { class: "meta" },
          statusTag(item.status),
          h("span", { class: "num" }, `${formatInt(item.gas)} gas`),
        ),
        h("i", {
          class: `profile-dot ${item.profile ? "attached" : ""}`,
          "aria-hidden": "true",
        }),
      ),
    ),
  );
}

/* ---------- Detail: timing ---------- */

function titleBlock(item) {
  const statusNote =
    item.status === "revert"
      ? "An expected root revert recorded by the verifier: this is a correctly verified benchmark of a reverting path, and the reverted work still consumed gas."
      : item.status === "success"
        ? "Timed boundary: the root call plus nested execution through the production host. Excludes fixture parsing, RPC, base-state construction, cache preparation, state reset, correctness checks and serialization."
        : "Root status as recorded by the verifier.";
  return h(
    "div",
    { class: "detail-title" },
    h("h3", null, item.name),
    h(
      "div",
      { class: "inline" },
      statusTag(item.status),
      h("span", { class: "mono muted" }, item.id),
      item.profile ? tag(item.profile, "tag-accent tag-mono") : null,
    ),
    fine(statusNote, "fine"),
  );
}

function metricCards(item) {
  const reps = formatInt(item.repetitions);
  return h(
    "div",
    { class: "cards" },
    blueprint(
      { class: "metric" },
      h("h6", null, "Execution gas"),
      h("p", { class: "metric-value num" }, formatInt(item.gas)),
      h(
        "p",
        { class: "metric-note" },
        "Gross direct-call gas before refunds; a deterministic count, identical in every repetition.",
      ),
    ),
    blueprint(
      { class: "metric" },
      h("h6", null, "CPU median"),
      h("p", { class: "metric-value num" }, valueOr(formatUs(item.cpu.median))),
      h(
        "p",
        { class: "metric-note" },
        `Median of ${reps} repetition averages of process CPU time, µs per execution.`,
      ),
    ),
    blueprint(
      { class: "metric" },
      h("h6", null, "Wall median"),
      h("p", { class: "metric-value num" }, valueOr(formatUs(item.wall.median))),
      h(
        "p",
        { class: "metric-note" },
        `Median of ${reps} repetition averages of wall-clock time, µs per execution.`,
      ),
    ),
  );
}

function distributions(item) {
  const rows = [
    ["Median", "median"],
    ["Mean", "mean"],
    ["Min", "minimum"],
    ["Max", "maximum"],
    ["Std dev (n−1)", "stddev"],
    ["CV", "cv"],
  ].map(([label, key]) => ({
    cells: [
      label,
      valueOr(key === "cv" ? formatPct(item.cpu[key]) : formatUs(item.cpu[key])),
      valueOr(key === "cv" ? formatPct(item.wall[key]) : formatUs(item.wall[key])),
    ],
  }));
  const reps = Number(item.repetitions);
  const explanation =
    reps >= 2
      ? `Over ${formatInt(reps)} equally weighted repetition averages. Min and max are extrema of those averages, not the fastest or slowest individual call. No quartiles, percentiles or confidence intervals exist in this export.`
      : "One repetition: standard deviation and CV are unavailable, not zero, and min and max equal the single repetition average.";
  return h(
    "div",
    { class: "stack" },
    h("h6", null, "Distribution summaries"),
    h(
      "div",
      { class: "table-wrap" },
      table({
        caption: "Timing distribution summaries",
        columns: [
          { label: "Statistic" },
          { label: unitLabel("CPU", "µs"), class: "num" },
          { label: unitLabel("Wall", "µs"), class: "num" },
        ],
        rows,
      }),
    ),
    fine(explanation),
  );
}

function metadata(item) {
  const rows = [
    ["Repetitions", formatInt(item.repetitions)],
    ["Total iterations", formatInt(item.iterations)],
    ...Object.entries(item.labels).map(([key, value]) => [
      `label · ${key}`,
      h("span", { class: "wrap-any" }, value),
    ]),
    ...Object.entries(item.counters).map(([key, value]) => [
      `counter · ${key}`,
      h("span", { class: "mono" }, value),
    ]),
    ["Output bytes", `${formatInt(item.output_bytes)} (byte count, not decoded output)`],
    ["Logs", `${formatInt(item.logs)} (count, not contents)`],
  ];
  return h(
    "div",
    { class: "stack" },
    h("h6", null, "Workload metadata"),
    kv(rows),
  );
}

/* ---------- Detail: evidence ---------- */

function noProfile(data) {
  if (!data.profiles.length)
    return h(
      "div",
      { class: "empty" },
      h("h4", null, "Timing-only export"),
      h(
        "p",
        null,
        "Gas and instruction evidence needs a diagnostics-v1 or attribution-v1 input at export time. The whole-call metrics above are the complete record for this case.",
      ),
    );
  return h(
    "div",
    { class: "empty" },
    h("h4", null, "No compatible profile"),
    h(
      "p",
      null,
      "Attachment requires the fixture bundle, block, environment, runner and client revisions, compiler build, case name, gas and root status to match. A shared case name is insufficient, and an ambiguous attachment is rejected at export.",
    ),
  );
}

function totals(profile) {
  const entries = [
    ["Whole-call gas", formatInt(profile.gas), "Verified execution gas of the replay."],
    [
      "Instruction visits",
      formatInt(profile.steps),
      "Includes attempted faulting opcodes.",
    ],
    [
      "Interpreter frames",
      formatInt(profile.frames.length),
      "Precompiles create none.",
    ],
    [
      "Outside-VM gas",
      formatInt(profile.outside_vm_gas),
      "Charged outside every interpreter frame.",
    ],
  ];
  return h(
    "div",
    { class: "totals" },
    entries.map(([label, value, hint]) =>
      blueprint(
        { class: "metric" },
        h("h6", null, label),
        h("p", { class: "metric-value small num" }, value),
        h("p", { class: "metric-note" }, hint),
      ),
    ),
  );
}

function coverage(profile, state, actions) {
  const metric = state.coverageMetric === "visits" ? "visits" : "gas";
  const field = metric === "gas" ? "gas" : "steps";
  const cov = profile.coverage ?? {};
  const pick = (kind) => cov[kind]?.[field] ?? 0;
  const denominator = metric === "gas" ? profile.gas : profile.steps;
  const segments = [
    ["Solidity-mapped", pick("solidity"), "cov-solidity"],
    ["Compiler-generated", pick("generated"), "cov-generated"],
    ["Unmapped", pick("unmapped"), "cov-unmapped"],
  ];
  if (metric === "gas")
    segments.push(["Outside-VM remainder", profile.outside_vm_gas, "cov-outside"]);
  const bar = h(
    "div",
    { class: "coverage-bar", role: "img", "aria-label": segments.map(([label, value]) => `${label} ${formatInt(value)}`).join(", ") },
    segments.map(([, value, cls]) =>
      geometry(h("i", { class: cls }), { width: `${share(value, denominator)}%` }),
    ),
  );
  const legend = h(
    "div",
    { class: "legend" },
    segments.map(([label, value, cls]) =>
      h(
        "span",
        null,
        h("i", { class: `swatch filled ${cls.replace("cov-", "c-").replace("c-solidity", "c-accent-700").replace("c-generated", "c-accent-400").replace("c-unmapped", "c-neutral-400").replace("c-outside", "c-neutral-600")}`, "aria-hidden": "true" }),
        h("span", { class: "num" }, `${label} ${formatInt(value)}`),
      ),
    ),
  );
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "section-head" },
      h("h6", null, "Source coverage"),
      segmented(
        [
          ["gas", "Gas"],
          ["visits", "Visits"],
        ],
        metric,
        (value) => actions.set({ coverageMetric: value }),
        "Coverage metric",
      ),
    ),
    bar,
    legend,
    fine(
      metric === "gas"
        ? `The denominator is whole-call gas (${formatInt(profile.gas)}), so the three mapping categories are not forced to 100%: the outside-VM remainder is its own segment.`
        : `Instruction coverage counts recorded interpreter visits out of ${formatInt(profile.steps)}; it is not line or test coverage.`,
    ),
  );
}

function icicle(profile, tree, state, actions) {
  const total = toBigInt(profile.gas) ?? 0n;
  const rows = [];
  const row = (depth) => {
    while (rows.length <= depth) rows.push([]);
    return rows[depth];
  };
  const place = (frame, offset) => {
    const inclusive = toBigInt(frame.gas_used) ?? 0n;
    const self = toBigInt(frame.self_gas) ?? 0n;
    row(frame.depth).push({ kind: "inclusive", frame, x: offset, w: inclusive });
    row(frame.depth + 1).push({ kind: "self", frame, x: offset, w: self });
    let cursor = offset + self;
    for (const child of tree.children.get(frame.id) ?? []) {
      place(child, cursor);
      cursor += toBigInt(child.gas_used) ?? 0n;
    }
  };
  if (tree.root) place(tree.root, 0n);
  const outside = toBigInt(profile.outside_vm_gas) ?? 0n;
  row(0).push({ kind: "outside", x: total - outside, w: outside });

  return h(
    "div",
    { class: "icicle", role: "group", "aria-label": "Gas icicle of interpreter frames" },
    rows.map((blocks, depth) =>
      h(
        "div",
        { class: "icicle-row" },
        blocks
          .filter((block) => block.w > 0n)
          .map((block) => {
            const left = share(block.x, total);
            const width = share(block.w, total);
            let label;
            let text;
            if (block.kind === "outside") {
              label = `Outside-VM gas ${formatInt(block.w)}, no interpreter frame`;
              text = `outside-VM ${formatInt(block.w)}`;
            } else {
              const f = block.frame;
              label = `f${f.id} ${block.kind === "self" ? "self" : "inclusive"} block: self ${formatInt(f.self_gas)} gas, inclusive ${formatInt(f.gas_used)} gas, depth ${formatInt(f.depth)}, ${f.status}`;
              text =
                block.kind === "self"
                  ? `self ${formatInt(f.self_gas)}`
                  : `f${f.id} · ${formatInt(f.gas_used)}`;
            }
            const el = h(
              "button",
              {
                type: "button",
                class: `icicle-block ${block.kind} ${block.frame && block.frame.id === state.frameId ? "is-selected" : ""}`,
                title: label,
                "aria-label": label,
                "aria-pressed": block.frame ? (block.frame.id === state.frameId ? "true" : "false") : null,
                disabled: block.kind === "outside" ? true : null,
                onclick: block.frame ? () => actions.selectFrame(block.frame.id) : null,
              },
              text,
            );
            geometry(el, { left: `${left}%`, width: `${width}%` });
            void depth;
            return el;
          }),
      ),
    ),
  );
}

function shareBar(part, total) {
  const pct = share(part, total);
  return h(
    "div",
    { class: "bar bar-mini", role: "img", "aria-label": `${formatPct(pct / 100)} of whole-call gas` },
    geometry(h("i"), { width: `${pct}%` }),
  );
}

function treeTable(profile, tree, state, actions) {
  const total = profile.gas;
  const shown = tree.order.slice(0, state.treePage * TREE_PAGE_SIZE);
  const rows = shown.map((frame) => {
    const label = h(
      "button",
      {
        type: "button",
        class: "label",
        "aria-pressed": frame.id === state.frameId ? "true" : "false",
        onclick: () => actions.selectFrame(frame.id),
      },
      `f${frame.id} · depth ${formatInt(frame.depth)} · ${frame.code_kind}`,
    );
    const cell = h(
      "div",
      { class: "tree-frame" },
      label,
      h(
        "span",
        { class: "mono muted" },
        `${truncateMiddle(frame.recipient, 10, 6)} · ${frame.selector || "0x"} · ${truncateMiddle(frame.code_hash, 10, 6)}`,
      ),
    );
    geometry(cell, { paddingLeft: `${Number(frame.depth) * 18}px` });
    return {
      frame,
      cells: [
        cell,
        statusTag(frame.status),
        formatInt(frame.self_gas),
        shareBar(frame.self_gas, total),
        formatInt(frame.gas_used),
        formatInt(frame.steps),
        matchTag(frame.artifact_match),
      ],
    };
  });
  rows.push({
    outside: true,
    cells: [
      h("span", null, "Outside-VM gas ", muted("· no interpreter frame")),
      muted("—"),
      formatInt(profile.outside_vm_gas),
      shareBar(profile.outside_vm_gas, total),
      muted("—"),
      muted("—"),
      muted("—"),
    ],
  });
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "table-wrap table-wide" },
      table({
        caption: "Interpreter-frame tree",
        columns: [
          { label: "Frame" },
          { label: "Status" },
          { label: "Self gas", class: "num" },
          { label: "Self share" },
          { label: "Inclusive gas", class: "num" },
          { label: "Steps", class: "num" },
          { label: "Artifact match" },
        ],
        rows,
        rowAttrs: (row) => ({
          class: row.outside
            ? "outside-row"
            : `clickable ${row.frame.id === state.frameId ? "is-selected" : ""}`,
          onclick: row.frame
            ? (event) => {
                if (event.target.closest("button")) return;
                actions.selectFrame(row.frame.id);
              }
            : null,
        }),
      }),
    ),
    tree.order.length > shown.length
      ? h(
          "div",
          { class: "pager" },
          h("span", null, `showing ${formatInt(shown.length)} of ${formatInt(tree.order.length)} frames`),
          h(
            "button",
            { type: "button", class: "btn btn-ghost btn-sm", onclick: () => actions.set({ treePage: state.treePage + 1 }) },
            "Load next page",
          ),
        )
      : null,
  );
}

function frameSection(profile, tree, state, actions) {
  const viz = state.frameViz === "tree" ? "tree" : "icicle";
  const zero = !tree.root;
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "section-head" },
      h("h6", null, "Interpreter-frame tree"),
      segmented(
        [
          ["icicle", "Gas icicle"],
          ["tree", "Tree table"],
        ],
        viz,
        (value) => actions.set({ frameViz: value }),
        "Frame visualisation",
      ),
    ),
    fine(
      "Gas-weighted interpreter frames from the diagnostic replay: not an RPC call-tracer tree and not a timeline.",
    ),
    zero
      ? h(
          "div",
          { class: "empty" },
          h("h4", null, "Zero interpreter frames"),
          h(
            "p",
            null,
            `A precompile-only root call creates no interpreter frame. All ${formatInt(profile.outside_vm_gas)} gas is outside-VM gas and the accounting still balances against ${formatInt(profile.gas)} whole-call gas.`,
          ),
        )
      : null,
    viz === "icicle"
      ? h(
          "div",
          { class: "stack" },
          icicle(profile, tree, state, actions),
          fine(
            "Width is gas, never time. Rows are nesting depth, left-to-right order is tree order.",
          ),
        )
      : treeTable(profile, tree, state, actions),
    note(
      "Inclusive gas contains child work: do not sum that column. The identity is Σ self gas + outside-VM gas = whole-call execution gas. Call type, code address, calldata and value are absent from the schema, so no edge carries a CALL or DELEGATECALL label.",
    ),
  );
}

function opcodeTotals(profile) {
  const list = Array.isArray(profile.opcodes) ? profile.opcodes : [];
  const top = list.slice(0, OPCODE_ROWS);
  const rest = list.slice(OPCODE_ROWS);
  const max = top.length ? top[0].gas : 0;
  const rows = top.map((entry) => ({
    cells: [
      h(
        "span",
        null,
        h("span", { class: "opcode-name" }, opcodeName(entry.opcode)),
        h("span", { class: "opcode-hex" }, opcodeHex(entry.opcode)),
      ),
      h(
        "div",
        { class: "bar bar-mini", "aria-hidden": "true" },
        geometry(h("i"), { width: `${share(entry.gas, max)}%` }),
      ),
      formatInt(entry.gas),
      muted(formatInt(entry.steps)),
    ],
  }));
  if (rest.length)
    rows.push({
      other: true,
      cells: [
        `${plural(rest.length, "other opcode")}`,
        "",
        formatInt(bigSum(rest.map((entry) => entry.gas))),
        muted(formatInt(bigSum(rest.map((entry) => entry.steps)))),
      ],
    });
  return h(
    "div",
    { class: "stack" },
    h("h6", null, "Opcode totals"),
    h(
      "div",
      { class: "table-wrap" },
      table({
        caption: "Gas and visits by opcode",
        columns: [
          { label: "Opcode" },
          { label: "Gas share" },
          { label: "Gas", class: "num" },
          { label: "Visits", class: "num" },
        ],
        rows,
        rowAttrs: (row) => ({ class: row.other ? "other-row" : null }),
      }),
    ),
    fine(
      "Gas is the observed execution delta per opcode, not a static base price; host-side costs beneath a call can be charged to the invoking opcode.",
    ),
  );
}

function rankIndexOf(profile, sourceId) {
  return profile.source_totals.findIndex((entry) => entry.source === sourceId);
}

function pcRows(profile, tree, state, actions) {
  const frame = state.frameId === null ? null : tree.byId.get(state.frameId) ?? null;
  const request = state.frameRequest;
  const head = h(
    "div",
    { class: "stack" },
    h("h6", null, frame ? `Selected frame — PC rows · f${frame.id}` : "Selected frame — PC rows"),
    frame ? h("span", { class: "mono muted" }, `/${frame.file}`) : null,
  );
  let body;
  if (!frame) body = fine("No interpreter frame exists in this case, so there are no PC rows to load.");
  else if (!request || request.status === "loading") body = loading("Loading frame file…");
  else if (request.status === "failed")
    body = h(
      "div",
      { class: "error-panel", role: "alert" },
      h("p", null, h("strong", null, "Frame request failed: "), h("span", { class: "mono" }, request.path)),
      fine(`${request.error}. The rest of this page stays usable: totals and the frame tree came from the already-loaded case file.`),
      h(
        "button",
        { type: "button", class: "btn btn-sm", onclick: () => actions.retryFrame() },
        icon("refresh"),
        "Retry",
      ),
    );
  else {
    const pcs = request.data.pcs;
    const shown = pcs.slice(0, state.pcPage * PC_PAGE_SIZE);
    const rows = shown.map((pc) => {
      const count = toBigInt(pc.count) ?? 0n;
      const gas = toBigInt(pc.gas) ?? 0n;
      const perVisit =
        count > 0n
          ? `${formatDecimal(Number((gas * 100n) / count) / 100, 2)} avg`
          : null;
      const mappable =
        pc.mapping === "mapped" && pc.source !== null && profile.sources[pc.source];
      const mapping = mappable
        ? h(
            "button",
            {
              type: "button",
              class: "tag tag-accent",
              "aria-label": `Show source for PC ${pc.pc}`,
              onclick: () => actions.selectSource(Math.max(0, rankIndexOf(profile, pc.source)), "hotspots"),
            },
            "mapped",
          )
        : tag(String(pc.mapping), "tag-neutral");
      return {
        cells: [
          { node: formatInt(pc.pc), class: "pc" },
          h(
            "span",
            null,
            h("span", { class: "opcode-name" }, opcodeName(pc.opcode)),
            h("span", { class: "opcode-hex" }, opcodeHex(pc.opcode)),
          ),
          formatInt(pc.count),
          formatInt(pc.gas),
          valueOr(perVisit),
          mapping,
        ],
      };
    });
    body = h(
      "div",
      { class: "stack" },
      h(
        "div",
        { class: "table-wrap bounded" },
        table({
          caption: `Aggregated PC rows in frame f${frame.id}`,
          columns: [
            { label: "PC", class: "pc" },
            { label: "Opcode" },
            { label: "Visits", class: "num" },
            { label: "Gas", class: "num" },
            { label: "Gas per visit", class: "num" },
            { label: "Mapping" },
          ],
          rows,
        }),
      ),
      h(
        "div",
        { class: "pager" },
        h(
          "span",
          null,
          `showing ${formatInt(shown.length)} of ${formatInt(pcs.length)} aggregated PC rows in f${frame.id}`,
        ),
        pcs.length > shown.length
          ? h(
              "button",
              {
                type: "button",
                class: "btn btn-ghost btn-sm",
                onclick: () => actions.set({ pcPage: state.pcPage + 1 }),
              },
              "Load next page",
            )
          : null,
      ),
    );
  }
  return h(
    "div",
    { class: "stack", id: "pc-rows" },
    head,
    body,
    fine(
      "Aggregated counters, not chronological structLogs: repeated visits to a loop instruction collapse into one row, gas per visit is an average over those visits, and no stack or memory snapshot exists.",
    ),
  );
}

function hotspots(profile, tree, state, actions) {
  const ranked = Array.isArray(profile.source_totals) ? profile.source_totals : [];
  const head = h(
    "div",
    { class: "stack" },
    h("h4", null, "Source-span hotspots"),
    fine(
      "Compiler-span attribution of gas and visits. Visits are not function calls, and none of this is CPU time.",
    ),
  );
  if (!ranked.length || !profile.sources.length) {
    const root = tree.root;
    const status = root?.artifact_match?.status;
    return h(
      "div",
      { class: "stack", id: "hotspots" },
      head,
      h(
        "div",
        { class: "empty" },
        h("h4", null, "No source mapping"),
        h(
          "p",
          null,
          `${status ? `The root frame's artifact match is ${status}: ` : ""}all gas and visits are unmapped. Gas and opcode evidence above is still complete. Mapping needs build-info from the compilation that produced the bytecode; an address name or ABI is not sufficient.`,
        ),
      ),
    );
  }
  const index = Math.min(Math.max(0, state.selectedSourceIndex), ranked.length - 1);
  const selectedEntry = ranked[index];
  const source = profile.sources[selectedEntry.source];
  const rows = ranked.map((entry, rank) => {
    const item = profile.sources[entry.source];
    const label = item
      ? `line ${formatInt(item.line)}, byte col ${formatInt(item.column_bytes)} · ${item.function ? item.function.name : "no function label"} · ${item.kind}`
      : "unknown source";
    return {
      rank,
      cells: [
        h(
          "div",
          null,
          h(
            "button",
            {
              type: "button",
              class: "row-link cell-title",
              "aria-pressed": rank === index ? "true" : "false",
              onclick: () => actions.selectSource(rank),
            },
            item ? item.file : "unknown",
          ),
          h("div", { class: "cell-sub" }, label),
        ),
        formatInt(entry.gas),
        formatInt(entry.steps),
      ],
    };
  });
  const left = h(
    "div",
    { class: "table-wrap" },
    table({
      caption: "Ranked source spans",
      columns: [{ label: "Span" }, { label: "Gas", class: "num" }, { label: "Visits", class: "num" }],
      rows,
      rowAttrs: (row) => ({
        class: `clickable ${row.rank === index ? "is-selected" : ""}`,
        onclick: (event) => {
          if (event.target.closest("button")) return;
          actions.selectSource(row.rank);
        },
      }),
    }),
  );
  const shaKey = `sha:${selectedEntry.source}`;
  const end = (toBigInt(source.start) ?? 0n) + (toBigInt(source.length) ?? 0n);
  const right = blueprint(
    { class: "stack" },
    h(
      "div",
      { class: "inline" },
      tag(source.kind, source.kind === "solidity" ? "tag-accent" : "tag-outline"),
      h("span", { class: "cell-title wrap-any" }, source.file),
    ),
    h(
      "span",
      { class: "fine num" },
      `line ${formatInt(source.line)} · byte column ${formatInt(source.column_bytes)} · ${formatInt(source.length)} bytes mapped`,
    ),
    h("pre", { class: "snippet" }, source.snippet),
    h(
      "div",
      { class: "source-meta" },
      h(
        "span",
        null,
        source.function
          ? `function ${source.function.name} · declared scope bytes ${formatInt(source.function.start)}–${formatInt((toBigInt(source.function.start) ?? 0n) + (toBigInt(source.function.length) ?? 0n))}`
          : "no enclosing function label",
      ),
      h("span", { class: "num" }, `byte span ${formatInt(source.start)}–${formatInt(end)}`),
      h("span", { class: "mono muted" }, `source_sha256 ${truncateMiddle(source.source_sha256)}`),
    ),
    h(
      "div",
      { class: "inline" },
      h(
        "button",
        {
          type: "button",
          class: "btn btn-sm",
          onclick: () => actions.copy(source.source_sha256, shaKey),
        },
        icon(state.copied === shaKey ? "check" : "copy"),
        state.copied === shaKey ? "Copied source_sha256" : "Copy source_sha256",
      ),
      state.frameId !== null
        ? h(
            "button",
            {
              type: "button",
              class: "btn btn-ghost btn-sm",
              onclick: () => actions.scrollTo("pc-rows"),
            },
            icon("arrow-left"),
            `Back to frame f${state.frameId}`,
          )
        : null,
    ),
  );
  return h(
    "div",
    { class: "stack", id: "hotspots" },
    head,
    h("div", { class: "band" }, left, right),
    note(
      "The snippet is a supplied excerpt of at most 240 bytes from the mapped span, not the source file; the path is a compiler-provided name, not a location to open; the function label is a declared enclosing scope, not a measured invocation. Optimized spans can overlap; offsets are UTF-8 byte offsets, and snippets may be short, multiline, truncated or contain replacement characters.",
    ),
  );
}

function evidence(item, context) {
  const { data, state, actions } = context;
  if (!item.profile) return noProfile(data);
  const request = state.caseRequest;
  const head = h(
    "div",
    { class: "evidence-head" },
    h(
      "div",
      { class: "inline" },
      h("h4", null, "Gas & instruction evidence"),
      tag(item.profile, "tag-accent tag-mono"),
    ),
    fine(
      "A separate verified interpreter replay of the same fixture, with no CPU timing per frame, opcode or source span.",
    ),
  );
  if (!request || request.status === "loading")
    return h("div", { class: "stack" }, head, loading(`Loading case file /${item.profile}.json…`));
  if (request.status === "failed")
    return h(
      "div",
      { class: "stack" },
      head,
      h(
        "div",
        { class: "error-panel", role: "alert" },
        h("p", null, h("strong", null, "Case file request failed: "), h("span", { class: "mono" }, request.path)),
        fine(`${request.error}. Timing metrics above are unaffected; they came from summary.json.`),
        h(
          "button",
          { type: "button", class: "btn btn-sm", onclick: () => actions.retryCase() },
          icon("refresh"),
          "Retry",
        ),
      ),
    );
  const profile = request.data;
  const tree = frameTree(profile.frames);
  return h(
    "div",
    { class: "detail" },
    h("div", { class: "stack" }, head, totals(profile)),
    coverage(profile, state, actions),
    frameSection(profile, tree, state, actions),
    h("div", { class: "band" }, opcodeTotals(profile), pcRows(profile, tree, state, actions)),
    hotspots(profile, tree, state, actions),
  );
}

export function renderExplorer(context) {
  const { selected } = context;
  const detail = selected
    ? h(
        "div",
        { class: "detail" },
        titleBlock(selected),
        metricCards(selected),
        h("div", { class: "band" }, distributions(selected), metadata(selected)),
        evidence(selected, context),
      )
    : h(
        "div",
        { class: "empty" },
        h("h4", null, "Select a case"),
        h(
          "p",
          null,
          "Choose a case from the list to read its timing distributions, workload metadata and, when a profile is attached, its gas and instruction evidence.",
        ),
      );
  return h(
    "section",
    { class: "explorer", "aria-label": "Case explorer" },
    caseList(context),
    detail,
  );
}
