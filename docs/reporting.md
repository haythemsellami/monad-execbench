# Offline benchmark reports

`monad-execbench-report` converts saved Google Benchmark JSON from
`monad-execbench run` into a deterministic Markdown report. It never starts a
fork, contacts an RPC, verifies a fixture, or executes the C++ runner. The same
inputs and options produce identical report bytes, including the recorded
input paths.

## Installation

Python 3.11 or newer is required. Reporting uses only the Python standard
library. It ships alongside capture in the existing Python distribution, so
the normal project installation provides both commands:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/monad-execbench-report --help
```

For report-only use directly from a source checkout, no Python dependencies or
C++ build are needed:

```bash
PYTHONPATH=analysis python3 -m monad_execbench_report --help
```

## Summarize saved results

Inputs have user-chosen names used by comparison manifests. Repeat `--input`
to put several runs into one report; each input retains its own tables and
provenance.

```bash
.venv/bin/monad-execbench-report \
  --input dual=results/dual-hot.json \
  --input interpreter=results/interpreter-hot.json \
  --output results/report.md
```

Names may contain ASCII letters, digits, dots, dashes, and underscores and
must begin with a letter or digit. Names and input files must be unique. Paths
containing spaces should be quoted as part of the entire `NAME=PATH` argument.
Inputs resolve relative to the current working directory.

The report includes:

- Case status, execution gas, log count, return-data size, repetitions, and
  total calibrated iterations.
- Wall and process-CPU median, mean, minimum, maximum, sample standard
  deviation, and coefficient of variation (CV).
- Exact unsigned metadata counters and string labels from the JSON label.
- Source-file SHA-256 digests and every recorded context field, including
  runner and fixture hashes, client revision, execution environment, block,
  mode, compiler, build, and available host information.
- Measurement boundaries, interpretation limitations, and quality warnings.

`--title 'My benchmark report'` changes the document heading. Input-controlled
text is escaped as literal text instead of being interpreted as Markdown or
HTML. No contract names, addresses, ABIs, selectors, or workload sizes are
built into the reporter.

Existing output is preserved unless `--force` is supplied. Output is written
atomically after all validation and rendering succeeds. Even with `--force`,
the command refuses to overwrite an input or comparison manifest, including
hard-link aliases; output symlinks are rejected. Generated reports do not
modify the original JSON. Keep the raw files alongside any published report.

## Explicit implementation comparisons

Without `--comparisons`, the tool reports distributions only. It does not
infer a baseline, pair cases by their names, or match arbitrary metadata.

For a suite with cases named `implementation-a/size-10` and
`implementation-b/size-10`, the comparison manifest is:

```json
{
  "schema": "monad-execbench/comparisons-v1",
  "comparisons": [
    {
      "name": "Size 10, dual VM",
      "baseline": {
        "input": "dual",
        "case": "implementation-a/size-10"
      },
      "candidate": {
        "input": "dual",
        "case": "implementation-b/size-10"
      }
    },
    {
      "name": "Size 10, interpreter",
      "baseline": {
        "input": "interpreter",
        "case": "implementation-a/size-10"
      },
      "candidate": {
        "input": "interpreter",
        "case": "implementation-b/size-10"
      }
    }
  ]
}
```

Save this as `comparisons.json`, then run:

```bash
.venv/bin/monad-execbench-report \
  --input dual=results/dual-hot.json \
  --input interpreter=results/interpreter-hot.json \
  --comparisons comparisons.json \
  --output results/comparison.md
```

Case references use the original manifest case name, not the runner's
`execute/<mode>/.../repeats:N` envelope. Comparison names must be unique.
Unknown manifest fields, unknown inputs/cases, and self-comparisons are
rejected. The comparison manifest's path and SHA-256 are recorded in the report.

Every ratio is **candidate / baseline**. For example, `1.25x` wall time and a
`+25%` wall change mean that the candidate took 25% more time. `0.8x` means it
took 20% less time. Timing ratios use medians, not averages of paired sample
ratios; randomized repetitions are not paired measurements. The report also
shows CPU microseconds per million execution gas:

```text
median CPU microseconds × 1,000,000 / execution gas
```

This describes the selected workload, not a general conversion between gas
and time. Ratios with zero denominators, or values outside finite floating
point range, are `n/a` rather than zero or infinity.

### Comparison compatibility

Implementation comparisons must use the same execution mode and matching
recorded environment, block, fixture hashes, runner binary/revision/version,
Monad revision, compiler/build, and host fingerprint. Host comparison checks
the recorded hostname, CPU count, nominal frequency, caches, scaling state,
and benchmark-library version/build. Missing optional host fields remain
unknown, not proof of identical operating conditions. Cross-file comparisons
also require identified 40-character Git revisions, not `unknown` placeholders.

Cases in one fixture suite may have different implementation labels, inputs,
and other metadata. Choosing a meaningful pair is the author's responsibility:
the tool does not infer economic or functional equivalence. Different execution
statuses cannot be paired. A verified root revert is a valid result, not a
benchmark failure, and may be compared with another verified root revert.

Multiple modes, builds, hosts, or fixtures may appear as separate input
sections, but incompatible pairs cause the whole report command to fail.
Cross-mode ratios, cross-machine scaling claims, and before/after comparisons
across different runner or fixture revisions are deliberately not supported
in this first reporting version. There is no compatibility-bypass flag.

## Statistical and validation rules

- Statistics are recomputed from `run_type: iteration` rows only. Each row is
  already an average per execution over its calibrated iterations; do not
  divide it by `iterations` again. Repetitions receive equal weight.
- `ns`, `us`, `ms`, and `s` are normalized to microseconds. Wall and process CPU
  time remain separate. Times are printed with six significant figures;
  percentage changes use three decimal places. Calculations use unrounded data.
- Standard deviation uses the sample convention (`n - 1`). With one repetition,
  standard deviation and CV are `n/a`. A zero mean also makes CV unavailable.
- CV is standard deviation / mean, formatted as a percentage. Provided
  aggregate rows, including Google Benchmark's CV rows, are not timing samples
  and their derived counter values are not treated as execution gas.
- Every present case must have exactly its requested raw repetitions, unique
  indexes covering `0..N-1`, positive calibrated iteration counts, one benchmark
  thread, and consistent status, metadata, and execution counters.
- Aggregate-only output, orphan aggregate groups, failed entries, unsupported
  schemas/modes/units, duplicate JSON keys, non-finite/negative timings, malformed
  metadata, and ambiguous runner-owned numeric counters are rejected. Error
  flags on aggregate rows are checked even though their statistics are ignored.
- Built-in execution counters must be nonnegative integers no larger than
  `2^53 - 1`. Larger user metadata counters are supported through the exact
  decimal strings in the label; the approximate numeric value must agree.
- Validation errors exit nonzero without replacing an existing report. The
  reporter does not reload the fixture, verify signatures, or certify result
  authenticity. It cannot detect a case whose raw and aggregate rows were both
  removed, nor recover console-only warnings.

## Measurement quality

Warnings flag enabled or unrecorded CPU scaling, unrecognized/non-optimized
builds, unidentified revisions, fewer than 50 repetitions, zero median times,
and wall or CPU CV above 5%. The 5% threshold is a diagnostic heuristic, not a
statistical significance test. Warnings stay visible in the report but do not
prevent exploratory analysis of already-recorded data.

The current runner JSON does not establish all of CPU affinity, core isolation,
CPU model, kernel, governor/turbo settings, or competing load. The reporter
does not read the reporting machine's configuration and mistake it for the
benchmark host. Matching recorded provenance alone is insufficient to certify
a controlled experiment. Refer to the original run logs and the
[benchmarking methodology](benchmarking.md) before publishing conclusions.

These are warmed direct-VM measurements, not full-transaction latency, node
throughput, hardware counters, opcode profiling, or security assessments.
Report generation does not rerun verification; correctness was checked by the
runner when it produced the input. Diagnostic profiling and release hardening
are separate follow-up work.

## Tests

The reporting tests require no RPC, Foundry, C++ build, or Linux host:

```bash
.venv/bin/python -m unittest discover -s tests/report -v
.venv/bin/ruff check analysis tests/report
.venv/bin/ruff format --check analysis tests/report
```

The synthetic tests cover statistical calculations, unit conversion, exact
large counters, explicit pairings, context mismatches, warnings, malformed and
incomplete results, literal Markdown rendering, output protection, and CLI use.
