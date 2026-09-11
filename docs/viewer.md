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

When explicitly serving on port 80, both the omitted and explicit `:80`
Host/Origin forms are accepted. Other ports must match the bound port exactly.

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

- **Overview:** choose a run and filter names, labels or counters. Review gas,
  wall/process-CPU medians, variability, repetitions and recorded provenance.
- **Workload scaling:** choose any exported numeric counter, timing/gas metric,
  and optional grouping label. Points are descriptive; no scaling law or
  statistical significance is inferred. Counter values remain exact strings;
  plotting uses relative positions, not rounded integers as case identifiers.
- **Comparisons:** ratios from the supplied manifest, using the same validation
  and statistics as Markdown reports. Incompatible cross-mode, cross-fixture,
  cross-build or cross-host pairs are rejected during export.
- **Case explorer:** distributions and metadata, an expandable VM-frame tree,
  self/inclusive gas, opcode totals, and lazy per-frame bytecode positions.
  Select a mapped position or hotspot for its supplied source snippet.

Each raw repetition is already an average over calibrated executions. Aggregate
rows are not extra observations. Gas is gross direct-call gas before refunds,
not receipt gas or transaction fees. Reverted work remains included. Frame
recipient is storage context, not necessarily the executing code address.
Precompiles may consume gas without their own interpreter frame.

There is no per-opcode or per-Solidity CPU timing, chronological opcode replay,
full-transaction latency, or node-throughput view. Source gas must not be used
to apportion whole-call CPU time. Missing source remains unmapped; optimized
source ranges and function labels are compiler hints, not invocation counts.

## Export format and validation

The output directory is a derived, versioned `monad-execbench/viewer-v1`
dataset. Export refuses an existing output and preserves original inputs. Input
files are capped at 512 MiB each; importing large JSON may still require
substantial transient memory. Export happens once, outside the HTTP server.

The complete dataset is staged beside the destination, then published with one
directory rename after exclusively reserving the output name. Publication errors
clean up the empty reservation and staged data so the same output can be retried.
If another writer modifies the reserved directory, cleanup preserves its contents
rather than recursively deleting them. This is not a crash-durability guarantee;
an uncatchable process termination can leave staging or an empty reservation.

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

Profile provenance is restricted to known fields. Build-info provenance retains
only each file's name, SHA-256 digest and compiler identity; additional imported
payloads are not copied into the summary. Malformed profile object/array shapes
and invalid build provenance are reported as CLI validation errors.

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
that the HTML, CSS and JavaScript assets survive wheel and sdist installation.
JavaScript syntax can additionally be checked by maintainers with
`node --check analysis/monad_execbench_viewer/static/app.js`.
