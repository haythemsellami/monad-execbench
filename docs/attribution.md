# Solidity execution attribution

Attribution answers **which bytecode and Solidity source spans consumed gas and
executed instructions** during a verified fixture replay. It does not measure
CPU time per opcode, Solidity function latency, JIT native-code samples, or
full-transaction/node throughput.

There are two separate tools:

- `monad-execbench-diagnostics`: Linux C++ diagnostic interpreter replay.
- `monad-execbench-attribute`: offline Python mapping and Markdown/JSON reports.

Neither needs an RPC endpoint after capture. Neither enables instrumentation in
the normal timing executable. Use the same saved fixture for timing and
attribution; compare its bundle hash in both outputs.

## Build the diagnostic executable

Use the recursive checkout, dependency setup, GCC 15, and Linux x86-64-v3
baseline from [the release guide](releases.md). Keep the normal timing build
in `build/` and create a **different** diagnostic build directory:

```bash
CC=gcc-15 CXX=g++-15 cmake -S . -B build-diagnostics -G Ninja \
  -DMONAD_EXECBENCH_DIAGNOSTICS=ON \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/monad/category/core/toolchains/gcc-avx2.cmake"
cmake --build build-diagnostics --target monad-execbench --parallel
cmake --install build-diagnostics --prefix /path/to/installation --component execbench
```

The CMake target keeps its existing name, but this configuration produces only
`monad-execbench-diagnostics`, with no timing commands. CMake rejects changing
an existing build directory between timing and diagnostic configurations.
Installations can contain both executables; their names do not collide.

The diagnostic compatibility layer is deliberately tied to the pinned Monad
revision. It replaces the interpreter dispatch translation unit in the build
graph, **not in the submodule**, and wraps the `MONAD_TEN` result-finalization
symbol with GNU ld. The dispatch wrappers call the upstream instruction
implementations. The upstream runtime, host, state engine, trampoline, memory
rules, and gas schedule remain responsible for execution semantics.

The finalization hook observes the actual EVMC result after deferred return
memory costs and exceptional-halt handling. It does not approximate or duplicate
that accounting. A dependency upgrade must review the dispatch/ABI shim and
rerun the native regression suite. LTO is not supported for this diagnostic
link configuration.

## Produce the compiler inputs

In the contract project, retain the build-info from the **same compilation**
that produced the captured deployed bytecode:

```bash
forge build --build-info --extra-output evm.deployedBytecode.generatedSources
```

Use `--force` if existing cached artifacts were built without build-info. Do
not rebuild an already-deployed contract with different compiler settings and
expect an address-based match. Compiler version, optimizer settings, source
paths, library links, and metadata can change the bytecode.

Pass the resulting `out/build-info/` directory or individual JSON files. Repeat
`--build-info` for separately compiled dependencies. Plain contract artifacts
and broadcast JSON are not enough: this command needs compiler input source
contents, compilation-scoped source IDs, deployed bytecode, source maps, and
reference ranges. No source paths are opened on disk or fetched from URLs;
source text comes only from the supplied build-info.

Generated Yul is reported separately when the compiler emitted its sources.
Missing generated-source data remains `source-unavailable`, not invented
Solidity attribution. Function labels are taken from enclosing AST function
or modifier spans when available, and include their source offsets to
distinguish overloads. They are not inferred from ABI selectors.

## Run

Install the Python utilities with `python -m pip install .`, then:

```bash
./build-diagnostics/monad-execbench-diagnostics /path/to/fixture \
  > /path/to/results/diagnostics.json

monad-execbench-attribute \
  --diagnostics /path/to/results/diagnostics.json \
  --build-info /path/to/contracts/out/build-info \
  --output /path/to/results/attribution.md \
  --json-output /path/to/results/attribution.json
```

Create the results directory first. Check the native command's exit status
before running attribution. Diagnostics are emitted to stdout only after all
cases pass; verification/progress/errors go to stderr. Shell redirection may
leave an empty file when execution fails. The Python command rejects invalid
diagnostics and never replaces existing output files or symlinks. Each report
file is published atomically; the optional JSON and Markdown pair is not a
multi-file transaction, so an I/O failure publishing the second file can leave
the first complete report in place.

`--top N` controls the number of source spans/unmapped PCs shown per case
(default 20). JSON retains every frame and PC. Keep the diagnostic JSON and
original build-info alongside reports for reproduction.

## What the reports contain

- Provenance: fixture bundle hash, pinned block, Monad and runner revisions,
  diagnostic executable hash, build/compiler details, and build-info hashes.
- Per-case verified gross execution gas, instruction count, and gas consumed
  outside VM interpreter frames.
- Interpreter frames: parent ID, EVMC depth, storage-context recipient, EVMC
  sender, input selector, runtime code hash, status, supplied gas, inclusive
  gas, and self gas.
- Per-frame/PC opcode byte, execution count, and gas excluding child bytecode
  work. JSON retains the actual observed bytecode keyed by Keccak-256 hash.
- Solidity/generated/unmapped coverage by both gas and instruction count.
- Ranked source spans with file, UTF-8 byte-based location, enclosing
  function/modifier where available, and source snippets in JSON.

Frame `recipient` is the storage context. With `DELEGATECALL`, it is not the
address supplying code; matching always uses **the actually executed code**.
`sender` follows EVMC semantics and is not necessarily the parent frame's
recipient. This is an interpreter-frame tree, not a complete RPC call-tracer
tree: precompiles do not enter the interpreter, and there is no inferred call
type or code address. An empty runtime can enter the interpreter and execute
an implicit padded `STOP`; that instruction is explicitly unmapped.
Frames entered by `CREATE`/`CREATE2` are marked `creation` and retain their
opcode/gas data without runtime source matching, even if their initcode happens
to equal an artifact's deployed bytecode. Creation source maps are not yet mapped.

Gas is gross consumption before refunds, not receipt gas or transaction cost.
For every case the following identities are checked:

```text
sum(PC gas in a frame) = frame self gas
frame self gas + direct child interpreter gas = frame inclusive gas
sum(all frame self gas) + outside-VM gas = verified case execution gas
```

Precompile execution, empty-account charges, code-deposit costs, and other
host-side work beneath a call remain charged to the invoking opcode unless
they occur outside all interpreter frames. The metric is an observed gas
delta, not just the opcode's fixed/base price.

Nested reverted/failed work is retained. A frame status describes that VM
invocation; a successful child may still have its state rolled back by a later
ancestor revert. Source gas does not imply persistent state changes. Counted
instructions include attempted faulting opcodes, not only completed ones.

## Matching and source-map limitations

Runtime matching checks the full bytecode, including metadata. Only compiler
declared immutable/library reference ranges may differ, and those ranges must
be inside `PUSH` immediate data. The report distinguishes `exact` and `masked`
matches. There is no metadata stripping, address-only lookup, or fuzzy match.

Multiple matching artifacts/compilations are `ambiguous`; none is selected
arbitrarily. Supply only the relevant build-info files to resolve stale or
duplicate compilations. Unknown code still contributes all gas/counts to its
frame, code hash, PC, and opcode, but has no invented Solidity source.

Solidity source maps index instructions, not bytes. The mapper skips `PUSH`
immediates, expands omitted map fields, respects compilation-scoped source IDs,
and uses UTF-8 byte offsets. `-1` source entries, implicit padding, and missing
map entries remain explicit unmapped work. The compiler's optimized/inlined
ranges can cover expressions, declarations, or entire functions; these are
source-map hints rather than precise causal ownership or function invocation
counts. See the [Solidity source-map specification](https://docs.soliditylang.org/en/latest/internals/source_mappings.html).

Diagnostics collect at most 10,000,000 instruction visits and 100,000
interpreter frames **per case**. Exceeding a limit or failing gas reconciliation
rejects the whole diagnostic report, never publishes partial coverage. Limits
stop collection, not EVM execution; fixture gas limits still bound replay.

Hardware counters, execution-scoped flamegraphs, and C++/JIT CPU attribution
remain separate work. Do not allocate measured wall time to Solidity by its
share of gas or opcode counts.

## Validation

```bash
python -m unittest discover -s tests/attribution -v
python tests/attribution/native_checks.py \
  --diagnostics ./build-diagnostics/monad-execbench-diagnostics
python tests/capture/anvil_roundtrip.py \
  --verifier "$PWD/build/monad-execbench" \
  --diagnostics "$PWD/build-diagnostics/monad-execbench-diagnostics" \
  --output results/attribution-roundtrip
```

Release CI runs these alongside the unchanged timing-runner CTests, package
installation tests, and the synthetic Foundry/capture/report workflow. No
consumer workload or public-chain benchmark is run by these tests.
