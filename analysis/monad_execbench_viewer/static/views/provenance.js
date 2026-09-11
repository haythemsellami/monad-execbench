import { h, blueprint, tag, note, kv, fine } from "../dom.js";
import { formatInt, truncateMiddle } from "../format.js";

const LONG = /^(?:0x)?[0-9a-f]{40,}$/i;

function copyable(value, key, { state, actions }) {
  const text = String(value);
  const isLong = LONG.test(text) || text.length > 40;
  const shown = isLong ? truncateMiddle(text) : text;
  return h(
    "span",
    { class: "value-row" },
    h("span", { class: isLong ? "mono" : "wrap-any", title: isLong ? text : null }, shown),
    h(
      "button",
      {
        type: "button",
        class: "copy-btn",
        "aria-label": `Copy full value of ${key}`,
        onclick: () => actions.copy(text, key),
      },
      state.copied === key ? "copied" : "copy",
    ),
  );
}

function group(title, rows, context, prefix) {
  return h(
    "div",
    { class: "group" },
    h("h6", null, title),
    kv(
      rows.map(([key, value]) => [
        key,
        value === undefined || value === null
          ? h("span", { class: "unavailable" }, "unavailable")
          : copyable(value, `${prefix}:${key}`, context),
      ]),
    ),
  );
}

const CHECKS = [
  {
    key: "scaling",
    title: "CPU frequency scaling",
    test: /cpu.scaling/i,
    explain:
      "The runner records whether frequency scaling was enabled or unrecorded on the benchmark host. Scaling changes timings between repetitions and between runs.",
  },
  {
    key: "cv",
    title: "5% CV heuristic",
    test: /CV exceeds/i,
    explain:
      "A wall or CPU coefficient of variation above 5% is flagged. This is a diagnostic heuristic, not a confidence interval or significance test.",
  },
  {
    key: "reps",
    title: "Fewer than 50 repetitions",
    test: /repetitions;/i,
    explain:
      "The standard protocol uses at least 50 repetitions per case; smaller counts leave the distribution summaries less settled.",
  },
  {
    key: "build",
    title: "Optimized build and library",
    test: /build|release mode/i,
    explain:
      "The runner and Google Benchmark should both be optimized release-type builds.",
  },
  {
    key: "revision",
    title: "Identified Git revisions",
    test: /Git revision/i,
    explain:
      "Cross-file ratios require identified 40-character revisions for the runner and the client.",
  },
  {
    key: "zero",
    title: "Nonzero median timings",
    test: /median timing is zero/i,
    explain: "A zero median makes any ratio with that denominator unavailable.",
  },
];

function warnings(run) {
  const remaining = new Set(run.warnings);
  const rows = CHECKS.map((check) => {
    const matched = run.warnings.filter((warning) => check.test.test(warning));
    matched.forEach((warning) => remaining.delete(warning));
    return h(
      "div",
      { class: "warning-row" },
      matched.length ? tag("active", "tag-accent") : tag("clear", "tag-neutral"),
      h(
        "div",
        { class: "stack" },
        h("span", { class: "title" }, check.title),
        h("span", { class: "explain" }, check.explain),
        matched.length
          ? h("ul", null, matched.map((warning) => h("li", null, warning)))
          : null,
      ),
    );
  });
  if (remaining.size)
    rows.push(
      h(
        "div",
        { class: "warning-row" },
        tag("active", "tag-accent"),
        h(
          "div",
          { class: "stack" },
          h("span", { class: "title" }, "Other exporter warnings"),
          h("ul", null, [...remaining].map((warning) => h("li", null, warning))),
        ),
      ),
    );
  return rows;
}

function caches(value) {
  if (!Array.isArray(value)) return value === undefined ? undefined : JSON.stringify(value);
  return value
    .map((cache) =>
      [cache.type, cache.level !== undefined ? `L${cache.level}` : null, cache.size !== undefined ? `${formatInt(cache.size)} B` : null, cache.num_sharing !== undefined ? `shared by ${formatInt(cache.num_sharing)}` : null]
        .filter(Boolean)
        .join(" "),
    )
    .join("; ");
}

export function renderProvenance(context) {
  const { data, run } = context;
  const c = run.context;
  const profiles = data.profiles;
  const diagnosticRows = profiles.length
    ? profiles.flatMap((profile) => [
        [`${profile.id} · file`, profile.file],
        [`${profile.id} · input schema`, profile.input_schema],
        [`${profile.id} · input SHA-256`, profile.input_sha256],
        [`${profile.id} · diagnostics SHA-256`, profile.diagnostics_sha256],
        [`${profile.id} · diagnostic runner SHA-256`, profile.runner_sha256],
        [`${profile.id} · runner revision`, profile.runner_commit],
        [`${profile.id} · client revision`, profile.monad_commit],
        [`${profile.id} · mode`, profile.mode],
        ...(Array.isArray(profile.build_info) ? profile.build_info : []).map(
          (build, index) => [
            `${profile.id} · build-info ${index + 1}`,
            `${build.file ?? "?"} · solc ${build.compiler ?? "?"} · ${build.sha256 ?? ""}`,
          ],
        ),
      ])
    : [["Diagnostic input", "none supplied · timing-only export"]];

  return h(
    "section",
    { class: "view", "aria-label": "Provenance and methodology" },
    h(
      "div",
      { class: "groups" },
      group(
        "Run identity & build",
        [
          ["Input name", run.name],
          ["Input file", run.file],
          ["Input SHA-256", run.sha256],
          ["Runner version", c.monad_execbench_version],
          ["Runner revision", c.monad_execbench_commit],
          ["Runner SHA-256", c.runner_sha256],
          ["Client revision", c.monad_commit],
          ["Compiler", c.compiler],
          ["Build type", c.build_type],
          ["Benchmark library", c.library_version],
          ["Library build", c.library_build_type],
        ],
        context,
        "run",
      ),
      group(
        "Fixture & environment",
        [
          ["Fixture schema", c.fixture_schema],
          ["Fixture created", c.fixture_created_at],
          ["Capture tool", c.capture_tool],
          ["Bundle SHA-256", c.fixture_bundle_sha256],
          ["Manifest SHA-256", c.fixture_manifest_sha256],
          ["Cases SHA-256", c.fixture_cases_sha256],
          ["State SHA-256", c.fixture_state_sha256],
          ["Execution environment", c.execution_env],
          ["Block number", c.block_number],
          ["Block hash", c.block_hash],
          ["Benchmark mode", c.benchmark_mode],
          ["Case filter", c.case_filter],
          ["Requested repetitions", c.requested_repetitions],
        ],
        context,
        "fixture",
      ),
      group(
        "Benchmark host as recorded",
        [
          ["Host name", c.host_name],
          ["CPUs", c.num_cpus],
          ["Nominal MHz per CPU", c.mhz_per_cpu],
          [
            "CPU scaling",
            c.cpu_scaling_enabled === undefined
              ? "not recorded"
              : c.cpu_scaling_enabled
                ? "enabled"
                : "disabled",
          ],
          ["Caches", caches(c.caches)],
        ],
        context,
        "host",
      ),
      group("Diagnostic input", diagnosticRows, context, "diag"),
    ),
    h(
      "div",
      { class: "stack" },
      h("h4", null, "Quality warnings retained by the exporter"),
      warnings(run),
      fine(
        "No active warning does not mean the run is production certified, statistically significant or from fully controlled hardware; it means these particular heuristics did not fire.",
      ),
    ),
    h(
      "div",
      { class: "cards" },
      blueprint(
        { class: "stack" },
        h("h6", null, "Timed boundary"),
        fine(
          "Each repetition times the root call plus every nested execution through the production host, then averages over calibrated iterations. Fixture parsing, RPC, base-state construction, cache preparation, state reset, correctness checks and serialization are outside the boundary.",
        ),
      ),
      blueprint(
        { class: "stack" },
        h("h6", null, "Modes"),
        fine(
          "dual-hot runs the dual VM with decoded and native code caches populated before sampling; interpreter-hot primes the decoded-code cache without native entry points. Both are warmed direct-VM measurements of the same fixture, not network conditions.",
        ),
      ),
      blueprint(
        { class: "stack" },
        h("h6", null, "Diagnostics"),
        fine(
          "Gas and instruction evidence comes from a separate verified interpreter replay of the same fixture. It carries no CPU timing per frame, opcode or source span, and its executable hash intentionally differs from the timing runner.",
        ),
      ),
      blueprint(
        { class: "stack" },
        h("h6", null, "Source mapping"),
        fine(
          "Solidity spans come from compiler source maps in the build-info of the compilation that produced the bytecode. Mapped spans are compiler hints for attribution of gas and visits, not invocation counts or ownership of CPU time.",
        ),
      ),
    ),
    note(
      "Hashes support reproducibility and identity checks; they do not authenticate an author, certify source truth or replace re-verification of the original fixture. Host facts absent from the export — CPU model, kernel, core isolation, governor and competing workload — stay unknown here. This page never reads the browser's hardware.",
    ),
  );
}
