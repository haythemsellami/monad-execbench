# monad-execbench Specification

## Status

Draft implementation specification.

## 1. Purpose

`monad-execbench` is an external, contract-agnostic benchmarking tool for measuring an arbitrary EVM call with the production Monad C++ execution engine.

The tool consumes a portable execution bundle containing a block environment, transaction message, account state, and expected result. It executes that bundle directly through the Monad VM and reports execution time, execution gas, CPU counters, opcode attribution, and call-frame attribution.

Foundry prepares contracts and calls. RPC tracing captures the state needed to replay them. The C++ runner performs the measurement. The runner must not contain hardcoded knowledge of any contract, protocol, address, ABI, function selector, or benchmark input.

## 2. Goals

The project must:

1. Execute arbitrary supplied EVM messages using the production Monad VM.
2. Default to `MONAD_TEN` execution semantics and gas accounting.
3. Build against a pinned Monad execution-client source revision that implements `MONAD_TEN`.
4. Consume self-contained, reproducible fixtures rather than querying an RPC during measurement.
5. Use Foundry artifacts and scripts to prepare newly compiled contracts and ABI-encoded calls.
6. Capture live dependency state from a pinned Monad block.
7. Benchmark production dual-mode execution and diagnostic interpreter execution.
8. Keep transaction state isolated between benchmark iterations while modeling production code-cache behavior.
9. Verify execution correctness before reporting performance.
10. Produce machine-readable raw results and human-readable comparative reports.
11. Support Linux `perf` and flamegraph collection without modifying the measured contract.
12. Detect incomplete fixtures instead of silently interpreting missing state as zero.

## 3. High-level architecture

```text
Foundry project
  |-- builds current contract source
  |-- deploys contracts on a pinned local fork
  |-- ABI-encodes benchmark calls
  `-- emits a call manifest
              |
              v
Fixture capture utility
  |-- reads the Foundry manifest and artifacts
  |-- calls the fork RPC and prestate tracer
  |-- records block context and expected results
  `-- emits a portable execution bundle
              |
              v
monad-execbench C++ runner
  |-- loads the fixture into an in-memory Monad state
  |-- verifies correctness and fixture completeness
  |-- executes through the production Monad VM
  `-- emits Google Benchmark JSON and diagnostics
              |
              v
Analysis and reporting
  |-- compares gas and CPU ratios
  |-- processes perf counters and flamegraphs
  `-- attributes work to call frames, opcodes, and source
```

## 4. Project components

### 4.1 C++ direct-VM runner

The primary executable will be `monad-execbench`. It will:

- Load one fixture or a suite of fixtures.
- Validate the fixture schema and supported execution environment.
- Construct an in-memory Monad state database.
- Construct the block header, transaction, EVMC message, and execution host.
- Execute with `monad::vm::VM` and `MonadTraits<MONAD_TEN>` by default.
- Create fresh transactional state for every benchmark iteration.
- Control compiler and decoded-code caches according to the selected benchmark mode.
- Run correctness checks before timed repetitions.
- Emit Google Benchmark-compatible JSON.

The headline execution path must call the production VM entry point with the target code hash and runtime bytecode. It must not substitute an Ethereum-only blockchain-test VM or Evmone for production Monad execution.

Nested contract calls must continue through the same VM and state engine. This includes external calls, storage operations, logs, internal reverts, and journal rollback.

### 4.2 Fixture capture utility

The capture utility will convert one or more prepared RPC calls into a portable execution bundle. It will be independent of the C++ timing process so benchmarks never perform network requests.

The initial implementation may be a small Python CLI because this layer primarily performs JSON-RPC orchestration, artifact parsing, validation, and serialization. Its public inputs and output schema are language-independent.

The capture utility will collect:

- Chain ID and selected Monad execution environment.
- Block number and block hash.
- Complete block execution context.
- Sender, recipient, calldata, value, gas, and access list.
- Runtime bytecode for every accessed contract.
- Balances and nonces for every accessed account.
- Every accessed storage slot and its value.
- Expected status, return data, execution gas, and selected balance changes.
- Optional call-trace data for later attribution.
- Foundry artifact labels, ABIs, source maps, and build metadata when available.

### 4.3 Foundry integration helper

The repository will provide a small Solidity helper that consumer projects can import from their benchmark deployment scripts.

It will allow a project to register a benchmark case using normal Solidity types and `abi.encodeCall`:

```solidity
ExecBench.addCall(
    "example/case-a",
    caller,
    target,
    callData,
    value
);
```

The helper will serialize a call manifest that the capture utility consumes. It will not attempt to serialize all EVM state itself.

Consumer-specific deployment and state preparation remain in the consumer repository.

### 4.4 Analysis tooling

Analysis scripts will consume raw benchmark output and generate:

- Per-case median, minimum, maximum, mean, and dispersion.
- Ratios between implementations.
- Gas-to-CPU comparisons.
- Linux `perf stat` summaries.
- Flamegraphs from `perf record` data.
- Call-frame and opcode summaries.
- Optional Solidity source attribution using Foundry source maps.

Raw data must remain available so generated conclusions can be independently checked.

## 5. Foundry integration

### 5.1 Foundry artifacts

The capture utility may consume Foundry artifacts from `out/` to obtain:

- Contract and source names.
- ABI and function selectors.
- Creation bytecode and deployed-bytecode templates.
- Immutable and library references.
- Solidity compiler settings and metadata.
- Deployed source maps.

Artifacts alone are not sufficient to construct a replay fixture. They do not contain current pool reserves, token balances, allowances, proxy storage, dependent contract state, or fully materialized runtime bytecode after constructor immutables are resolved.

The capture process must obtain actual runtime bytecode from the prepared fork after deployment.

### 5.2 Foundry broadcast output

When available, `forge script` broadcast output may be used to associate:

- Deployment addresses with artifacts.
- Constructor arguments with deployed contracts.
- Deployment order with human-readable labels.
- Prepared transaction inputs with cases.

The capture utility must not depend on a fixed deployment address. Addresses are data in the generated manifest and fixture.

### 5.3 Pinned local fork

The canonical capture workflow will use a local Monad-compatible Foundry fork pinned to a specific block.

The workflow is:

1. Start a local fork at the requested block.
2. Compile the consumer project.
3. Deploy freshly compiled benchmark contracts and dependencies to the fork.
4. Prepare caller balances and approvals.
5. Emit the call manifest.
6. Capture every call without committing its state changes.
7. Stop the fork after fixture generation.

No mainnet deployment or mainnet write is involved.

## 6. Execution bundle

### 6.1 Design principles

An execution bundle must be:

- Self-contained.
- Deterministic.
- Contract-agnostic.
- Explicit about the execution environment and block context.
- Validatable against a reference RPC result.
- Safe to run without network access.
- Compact enough to store or publish as a benchmark artifact.

Although `MONAD_TEN` is the execution-environment default, every normalized bundle must record its selected environment explicitly. A saved result must never depend on an implicit default.

### 6.2 Proposed directory format

```text
fixture-suite/
|-- manifest.json
|-- cases.json
|-- state.json.zst
|-- provenance.json
`-- artifacts/
    |-- build-info/
    `-- contracts/
```

The artifact directory is optional. Execution must only require the manifest, cases, state, and provenance. Artifacts enrich attribution and reporting.

### 6.3 Manifest example

```json
{
  "schema": "monad-execbench/v1",
  "chain": {
    "chainId": 143,
    "executionEnv": "MONAD_TEN"
  },
  "block": {
    "number": "97663468",
    "hash": "0x...",
    "parentHash": "0x...",
    "timestamp": "0x...",
    "gasLimit": "0x...",
    "baseFee": "0x...",
    "beneficiary": "0x...",
    "prevRandao": "0x..."
  },
  "state": "state.json.zst",
  "cases": "cases.json"
}
```

### 6.4 State representation

State will use a normalized address-to-account map containing:

- Balance.
- Nonce.
- Runtime code.
- Code hash.
- Accessed storage keys and values.

Multiple cases may share a union of their captured prestate. Adding an unused account or storage slot does not change execution and avoids duplicating dependency state across cases.

The capture utility must preserve sufficient information to distinguish:

- A captured slot whose value is zero.
- A slot that was not captured.

This distinction is required for incomplete-fixture detection.

### 6.5 Provenance

`provenance.json` must record:

- Fixture creation timestamp.
- Source RPC chain ID.
- Block number and hash.
- Monad execution-client commit expected by the runner.
- Foundry and Solidity compiler versions.
- Consumer repository commit and dirty-state indicator.
- Foundry artifact/build identifiers.
- Capture-tool version.
- Hashes of the normalized manifest, cases, and state.

RPC URLs, authorization headers, private keys, and environment secrets must never be written to provenance or fixtures.

## 7. State capture and completeness

### 7.1 Prestate capture

The capture utility will use `debug_traceCall` with a prestate tracer against the prepared local fork. It must verify that the tracer includes state accessed by nested calls that later revert.

If the selected RPC cannot provide a usable prestate tracer, capture must fail clearly. A raw opcode `structLogs` trace is not required for fixture generation.

### 7.2 Expected result

For each case, the capture stage must save a reference result from the same fork state:

- Success or revert status.
- Return or revert data.
- Execution gas.
- Selected account and token balance changes.
- Optional logs and call-frame tree.

Because capture calls are non-committing, every case starts from the same prepared fork state.

### 7.3 Missing-state detection

The C++ runner must use a validating state adapter during its untimed correctness pass. Every account and storage read will be checked against the fixture's captured-presence metadata.

If execution reads an uncaptured account or slot, verification must fail with the address, code hash when available, and storage key. Missing data must not be silently returned as an empty account or zero-valued slot.

Timed repetitions may use a lower-overhead state adapter only after the fixture passes completeness verification.

## 8. Execution-environment selection

`MONAD_TEN` is the default execution environment. Capture, verification, and benchmark commands must also accept an explicit `--execution-env <ENVIRONMENT>` CLI flag.

Rules:

1. When `--execution-env` is omitted during capture, the CLI selects `MONAD_TEN`.
2. The normalized bundle always records the selected execution environment explicitly.
3. During verification and execution, the CLI uses the bundle's recorded environment unless `--execution-env` is supplied.
4. An explicit CLI environment must match the bundle's recorded environment. A mismatch is rejected because the saved expected result belongs to the recorded environment.
5. The runner refuses unknown or unsupported environments.
6. The runner must not silently downgrade `MONAD_TEN` to `MONAD_NINE` or Ethereum Cancun behavior.
7. The Monad Git submodule must be pinned to a commit containing the production `MONAD_TEN` traits and schedule.
8. Additional environments may be supported through explicit trait dispatch.

## 9. Benchmark modes

### 9.1 `dual-hot`

This is the headline result.

- Use production `VM::Mode::Dual`.
- Decode and compile all fixture bytecode before timed execution.
- Preserve the VM/compiler code cache across iterations.
- Recreate transaction state for every iteration.

This models steady-state execution where code has already been observed and cached.

### 9.2 `interpreter-hot`

This is the primary diagnostic mode.

- Use production `VM::Mode::InterpreterOnly`.
- Cache decoded/intermediate code before timing.
- Collect opcode counts and other interpreter diagnostics when enabled.
- Preserve identical transaction-state reset semantics.

This mode supports detailed attribution and provides a compiler-independent correctness comparison.

### 9.3 `dual-cold`

This is an optional secondary result.

- Use production dual mode.
- Start with a fresh relevant code/compiler cache for each measured sample.
- Include first-seen compilation behavior in the timed region.

Cold and hot measurements must never be combined in the same headline statistic.

## 10. Timing boundaries

The timed region must include the root VM call and all nested contract execution. It must exclude fixture parsing, base-state construction, benchmark registration, result validation, and reporting.

For a hot benchmark iteration:

1. Pause timing.
2. Create a fresh `BlockState` and transactional `State` from the immutable base state.
3. Construct the transaction, message, block context, host, and tracers.
4. Apply transaction-level warm-account and access-list semantics.
5. Ensure the selected code caches are already primed.
6. Resume timing.
7. Call the production Monad VM.
8. Pause timing.
9. Verify the result against the prevalidated expectation.
10. Destroy the mutated transaction state.

The initial account-warming logic must model the transaction prelude accurately because a direct root VM call bypasses that part of normal transaction processing.

## 11. Correctness requirements

No timed benchmark result is valid until the case passes an untimed verification execution.

Verification must check:

- Execution status.
- Return or revert data.
- Execution gas.
- Selected native and token balance changes.
- Expected logs when supplied.
- Complete account and storage access coverage.
- Interpreter and compiler output agreement.
- Interpreter and compiler gas agreement.

Consumer workloads may include additional semantic checks in case metadata or an external report generator.

Any mismatch must fail the case rather than emit a performance number with a warning.

## 12. Command-line interface

The intended workflow is:

```bash
monad-execbench capture \
  --rpc-url http://127.0.0.1:8545 \
  --calls benchmark-calls.json \
  --artifacts out \
  --execution-env MONAD_TEN \
  --output fixtures/example-suite
```

```bash
monad-execbench verify fixtures/example-suite \
  --execution-env MONAD_TEN
```

```bash
monad-execbench run fixtures/example-suite \
  --execution-env MONAD_TEN \
  --mode dual-hot \
  --repetitions 50 \
  --output results/dual-hot.json
```

Case filtering:

```bash
monad-execbench run fixtures/example-suite \
  --filter 'implementation-b/*' \
  --mode interpreter-hot
```

The runner should pass through relevant Google Benchmark flags where doing so does not compromise fixture validation or result metadata.

## 13. Benchmark methodology

The standard comparison run will:

- Use at least 50 repetitions per case.
- Randomly interleave cases to reduce time-order bias.
- Pin the benchmark process to a selected physical CPU core.
- Record CPU model, kernel, compiler, build type, and relevant frequency settings.
- Use an optimized release build with debug symbols retained for profiling.
- Avoid network and disk access inside timed regions.
- Report distributions rather than only a single average.

The runner should expose Google Benchmark counters for:

- Execution gas.
- Amount or other numeric case metadata when provided.
- Return-data bytes.
- Log count.
- Optional executed-opcode count.

The benchmark executable must return a nonzero exit code when fixture verification fails.

## 14. Linux performance profiling

The C++ runner must be compatible with external profiling such as:

```bash
perf stat -r 20 -e \
  cycles,instructions,branches,branch-misses,cache-references,cache-misses \
  monad-execbench run fixtures/example-suite --filter 'example/case-a' --mode dual-hot
```

`perf record` will be used to generate flamegraphs for cases with meaningful CPU differences.

Primary hardware metrics are:

- CPU cycles.
- Instructions retired.
- Instructions per cycle.
- Branches and branch misses.
- Cache references and cache misses.
- Wall-clock and process CPU time.

Profiling invocations, raw perf data, and generated summaries must record the same fixture and executable hashes as the main benchmark output.

## 15. Opcode, call-frame, and source attribution

Interpreter diagnostics may record:

```text
address -> code hash -> program counter -> opcode -> count/cost
```

Call-frame attribution may record:

- Caller and callee.
- Call type.
- Input selector.
- Gas supplied and gas consumed.
- Success or revert status.
- Inclusive and exclusive execution measurements where available.

When a matching Foundry artifact is present, the deployed source map may translate program counters into Solidity source locations. Attribution must be keyed by runtime code hash rather than address alone so results remain correct with fresh deployments and duplicate bytecode.

External dependency contracts without matching artifacts will still be attributed by address, code hash, call frame, and opcode.

Diagnostic tracing is not enabled in headline `dual-hot` runs because its overhead changes the quantity being measured.

## 16. Repository layout

The external project is expected to evolve toward:

```text
monad-execbench/
|-- CMakeLists.txt
|-- cmake/
|   `-- MonadExecution.cmake
|-- src/
|   |-- main.cpp
|   |-- fixture_loader.cpp
|   |-- state_loader.cpp
|   |-- vm_runner.cpp
|   `-- benchmark_runner.cpp
|-- include/monad-execbench/
|-- capture/
|   |-- monad_execbench_capture/
|   `-- schema/
|-- foundry/
|   `-- src/ExecBench.sol
|-- analysis/
|-- docs/
|   `-- spec.md
|-- tests/
|-- examples/
`-- third_party/
    `-- monad/
```

The Monad execution repository will be pinned as a Git submodule. The benchmark and Monad libraries should be compiled in the same CMake build to avoid relying on an unstable binary ABI between independently built C++ components.

The first version should not require source modifications inside the Monad submodule. Any compatibility shim belongs in `monad-execbench` and must be explicitly tied to the pinned Monad commit.

## 17. Delivery phases

### Phase 1: Portable correctness replay

- Define and validate the bundle schema.
- Implement RPC prestate capture.
- Implement the Foundry call-manifest helper.
- Load captured state into Monad's in-memory state engine.
- Execute one arbitrary call with `MonadTraits<MONAD_TEN>`.
- Match the RPC status, output, and gas.
- Detect missing state.

### Phase 2: Reliable direct-VM benchmarking

- Integrate Google Benchmark.
- Implement `dual-hot` and `interpreter-hot`.
- Reset transaction state between repetitions.
- Prime and preserve the correct code caches.
- Emit reproducible raw JSON results.
- Add unit and integration tests for bundle loading and execution.

### Phase 3: Consumer benchmark suite

- Add a consumer-project Foundry preparation script.
- Generate representative fixtures from fresh deployments.
- Verify outputs, gas, and configured state changes.
- Run at least 50 randomized repetitions.
- Generate the direct-VM comparison report.

### Phase 4: Profiling and attribution

- Add `perf stat` automation.
- Capture flamegraphs for representative cases.
- Add interpreter opcode aggregation.
- Add call-frame attribution.
- Map locally built bytecode to Solidity through Foundry source maps.

### Phase 5: Extended measurements

- Add `dual-cold` compilation measurements.
- Add explicit support for other Monad forks if required.
- Add full-transaction and block-path benchmarks as a separate benchmark family.
- Add continuous performance-regression checks when results are stable enough for CI.

## 18. Initial acceptance criteria

The first usable release is complete when:

1. The C++ runner contains no contract-specific code or fixture constants.
2. A Foundry project can emit arbitrary call cases using the helper.
3. The capture utility creates a self-contained bundle from a pinned local fork.
4. The runner executes that bundle offline with production Monad `MONAD_TEN` semantics.
5. RPC and C++ execution agree on status, output, gas, and configured balance changes.
6. Compiler and interpreter modes agree on execution results and gas.
7. Missing account or storage data causes a hard verification failure.
8. Hot benchmark iterations start from identical transaction state while retaining the intended code cache.
9. Raw benchmark output records enough provenance to reproduce the run.
10. A consumer suite produces verified measurements for multiple arbitrary contract calls.

## 19. Deferred decisions

The following choices can be finalized during implementation without changing the architecture:

- The exact JSON library used by the C++ runner.
- Whether fixture state is stored as one compressed JSON file or chunked by account.
- The public packaging mechanism for the Foundry helper.
- Whether capture and analysis utilities share one Python package.
- The exact perf/flamegraph wrapper interface.
- Whether optional cryptographic account/storage proofs are added to fixture provenance.

None of these decisions may introduce contract-specific behavior into the C++ runner.
