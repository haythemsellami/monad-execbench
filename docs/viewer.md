# Local results viewer

The viewer reads saved benchmark results. It never starts a fork, contacts an
RPC, compiles contracts, runs the C++ engine, or modifies the original inputs.
It is contract/protocol agnostic: names, labels, counters and source annotations
come from the imported files. Execution support remains the runner's current
`MONAD_TEN` scope, not an arbitrary-chain performance model.

## Install and run

The viewer ships in the existing Python distribution; no Node.js, frontend
build, database, browser extension, CDN, or C++ installation is needed to use it.

```bash
python -m pip install .

monad-execbench-viewer export \
  --input dual=results/dual-hot.json \
  --input interpreter=results/interpreter-hot.json \
  --comparisons results/comparisons.json \
  --profile results/attribution.json \
  --output results/viewer

monad-execbench-viewer serve results/viewer
```

Open the printed `http://127.0.0.1:PORT` URL. The port defaults to an available
ephemeral port; `--port 8765` requests a specific one. The server runs until
Ctrl-C. It cannot bind to a public interface and does not automatically open a
browser. Do not expose it through a public proxy.

Use at least one `--input NAME=FILE`. Names follow the generic report command's
alias rules. Repeat inputs to display multiple modes/runs separately. The
`--comparisons` manifest is optional and uses the existing
[explicit comparison format](reporting.md#explicit-implementation-comparisons).
No automatic baseline, implementation, token, amount, or business semantics
are inferred from names.

`--profile` is optional and repeatable. It accepts either:

- Native `monad-execbench/diagnostics-v1` JSON: frame and opcode accounting,
  without Solidity mapping.
- `monad-execbench/attribution-v1` JSON: the same accounting plus source spans,
  snippets, enclosing function labels and mapping coverage.

Without profiles, timing and comparisons still work. A profile case must have
a compatible timing case: fixture bundle, block, environment, runner/client
revision, compiler and build must agree, as must case name, gas and status.
Duplicate/ambiguous associations are rejected. Normal and diagnostic executable
hashes intentionally differ and are retained separately. A profile may attach
to matching cases in both timing modes; diagnostic gas is not another timing
mode. Supply timing inputs covering every case in each supplied profile.

## Explore

The page is a single local document with five hash-routed views. The left rail
lists the views with their counts and the timing runs as radios; switching the
run resets the selected case and frame. The header shows the run's mode,
environment, pinned block and caution count, and "Export summary" downloads the
loaded `summary.json` (it is not a reproducibility bundle). When the exporter
retained quality warnings they appear beneath the header as measurement
cautions: heuristics, not errors, and the data stays viewable.

- **Results overview:** ranges (never totals) of gas, CPU median and CPU CV
  across the run's independent cases; search over names, labels and counters;
  single-select label chips; a sortable case table. Status is shown as text
  plus a glyph; an expected root revert is a valid result, not a failure.
- **Workload scaling:** any exported numeric counter against CPU median, wall
  median or gas, optionally split into series by a string label. Counter values
  stay exact decimal strings; points are connected in counter order for reading
  only and no scaling law is fitted or implied. Runs without counters show an
  empty state, not an error.
- **Comparisons:** one card per manifest entry with baseline and candidate
  identities, exact values, the candidate ÷ baseline ratio as a bar with a
  1.00× marker, and the percentage change. Pairings are never inferred.
- **Case explorer:** whole-call metrics, distribution summaries and workload
  metadata for the selected case, followed by the diagnostic evidence when a
  profile is attached: totals, source coverage over whole-call gas (with the
  outside-VM remainder as its own segment), the interpreter-frame tree as a gas
  icicle or a tree table, opcode totals, the selected frame's aggregated PC rows
  (paginated, loaded lazily) and ranked source-span hotspots with the supplied
  snippet. Timing-only exports, cases without a compatible profile, zero-frame
  precompile calls and unmatched artifacts each have an explicit state.
- **Provenance & methodology:** run identity and build, fixture and
  environment, the benchmark host as recorded, diagnostic inputs, every quality
  warning with an active/clear tag, and the methodology notes. Long values are
  truncated on screen; the copy control copies the full value.

Each raw repetition is already an average over calibrated executions. Aggregate
rows are not extra observations. Gas is gross direct-call gas before refunds,
not receipt gas or transaction fees. Reverted work remains included. Frame
recipient is storage context, not necessarily the executing code address.
Precompiles may consume gas without their own interpreter frame.

There is no per-opcode or per-Solidity CPU timing, chronological opcode replay,
full-transaction latency, or node-throughput view. Source gas must not be used
to apportion whole-call CPU time. Missing source remains unmapped; optimized
source ranges and function labels are compiler hints, not invocation counts.
Integers past `2^53 - 1` are decimal strings and are shown, sorted and copied
exactly; `null` statistics read "unavailable", never zero.

## Frontend

The frontend is plain HTML, CSS and vanilla ES modules under
`analysis/monad_execbench_viewer/static/` with no build step: `index.html`,
`style.css`, `app.js` (bootstrap, routing, lazy requests), `dom.js`,
`format.js`, `state.js` and one module per view under `views/`. The stylesheet
carries the design tokens as custom properties and the Barlow and Barlow
Condensed faces are vendored as local WOFF2 files under `static/fonts/` with
their SIL Open Font License; nothing is fetched from the network. Only
`summary.json` is requested on load; `p{N}-c{M}.json` is fetched when a case is
selected and `p{N}-c{M}/frame-{K}.json` when a frame is selected. All imported
text is bound as text, never as markup, and the page runs under the server's
content-security policy with no inline script, inline handlers, `eval`, workers
or remote resources. The server reads the packaged assets once at start-up and
serves only that allowlist plus the export's narrowly named JSON files.

## Export format and validation

The output directory is a derived, versioned `monad-execbench/viewer-v1`
dataset. Export refuses an existing output and preserves original inputs. Input
files are capped at 512 MiB each; importing large JSON may still require
substantial transient memory. Export happens once, outside the HTTP server.

```text
viewer/
  summary.json              # run/case statistics, comparisons and provenance
  p0-c0.json                # one diagnostic case: frames, sources, opcode totals
  p0-c0/frame-0.json         # one frame's PC counts, gas and source indexes
  ...
```

Identifiers and filenames are generated locally, never derived from untrusted
contract/source names. Source descriptions are deduplicated per case; bytecode
blobs and original build-info contents are not copied into the browser dataset.
Large integer values are serialized as decimal strings instead of silently
rounding in JavaScript. Only the selected case/frame details are fetched.

Timing import reuses the report library's raw-repetition validation,
distributions, comparison rules and quality warnings. Profile import reuses
the diagnostic attribution validator for bytecode hashes, PC boundaries and
gas/instruction conservation, then checks source annotation structure and
coverage totals. Imported source labels are **not independently authenticated
against compiler output**: run `monad-execbench-attribute` with matching
build-info to regenerate them. Input SHA-256 digests and supplied provenance
remain visible. Consistency checks do not certify input authenticity or replay
contracts; retain the original fixture/results for independent verification.

The server exposes only its packaged assets and narrowly named export JSON
files, rejects paths escaping the dataset, checks Host/Origin, disables CORS,
and applies a restrictive content-security policy. It has no upload endpoint,
write API, arbitrary file browser, execution button or archive extraction path.
Source snippets and labels are rendered as text, never executable HTML.

Use explicit files from an extracted results bundle to export; arbitrary archive
upload/import and remote hosting are not supported. Exports can contain private
calldata metadata, source snippets and host information: keep them local unless
you deliberately choose to share them. Treat exported datasets as immutable
while the server is running.

## Validation

```bash
python -m unittest discover -s tests/viewer -v
python tests/packaging/check_distributions.py
```

CI checks the viewer on the existing Python/Linux/macOS matrix and verifies
that the HTML, CSS, JavaScript modules and font files survive wheel and sdist
installation and are served from the installed package. `tests/viewer` also
asserts the gas accounting identities against a real export, round-trips
hostile case names, exports and serves a representative large dataset, and
checks that no asset references a remote URL. When a `node` executable is
available the modules are syntax-checked and the exact-value formatting rules
are exercised; Node is never required to serve or view results.
