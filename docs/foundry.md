# Foundry workflow

The Solidity helper in `foundry/src/ExecBench.sol` lets any Forge script emit a
call manifest without teaching the C++ runner about a contract ABI, address, or
workload.

## Import the helper

Add this repository as a dependency or copy the single helper source into the
consumer project, then use it from the script that prepares the fork:

```solidity
import { ExecBench } from "monad-execbench/ExecBench.sol";

using ExecBench for ExecBench.Manifest;

ExecBench.Manifest memory manifest = ExecBench.create(2);
manifest.addCall(
    "implementation-a/amount-1",
    caller,
    target,
    abi.encodeCall(ITarget.run, (input)),
    0
);
```

`create` takes the exact maximum case count. Adding beyond that capacity, using
an empty case name, or supplying invalid metadata reverts the script.

Use `Options` when a call needs an explicit gas limit, gas price, access list,
or report metadata:

```solidity
ExecBench.Options memory options;
options.labels = new ExecBench.Label[](1);
options.labels[0] = ExecBench.Label({
    key: "implementation", value: "implementation-b"
});
options.counters = new ExecBench.Counter[](1);
options.counters[0] = ExecBench.Counter({ key: "amount_in", value: input });

manifest.addCall(
    "implementation-b/amount-1",
    caller,
    target,
    abi.encodeCall(ITarget.run, (input)),
    0,
    options
);
```

Labels are arbitrary strings used for grouping and display. Counters are
unsigned integers exposed to Google Benchmark and are also retained as exact
decimal strings in the JSON label. Metadata keys must begin with an ASCII
letter or underscore and may then contain ASCII letters, digits, `_`, `.`, or
`-`. The names `execution_gas`, `return_data_bytes`, and `log_count` are
reserved for runner measurements.

Write the completed manifest after deployment and state preparation:

```solidity
manifest.write(vm.envString("EXECBENCH_CALLS_PATH"));
```

The consumer project's `foundry.toml` must grant write access to the selected
path through `fs_permissions`. Private keys, RPC URLs, and secrets are not part
of the manifest.

## Prepare, capture, and run

The normal sequence is:

1. Start a Monad-compatible local fork at a fixed block.
2. Run the consumer Forge script with `--broadcast` against that fork.
3. Pass the emitted calls file to `monad-execbench-capture`.
4. Run `monad-execbench verify` offline.
5. Run `monad-execbench run` only after verification passes.

For example:

```bash
EXECBENCH_CALLS_PATH="$PWD/fixtures/calls.json" \
  forge script script/PrepareBench.s.sol:PrepareBench \
  --rpc-url http://127.0.0.1:8545 \
  --broadcast

monad-execbench-capture \
  --rpc-url http://127.0.0.1:8545 \
  --calls fixtures/calls.json \
  --block latest \
  --execution-env MONAD_TEN \
  --output fixtures/generated/suite

monad-execbench verify fixtures/generated/suite
monad-execbench run fixtures/generated/suite \
  --mode dual-hot \
  --repetitions 50 \
  --output results/dual-hot.json
```

## Execution-environment selection

`--execution-env` records the schedule that the reference RPC is expected to
implement; it cannot change that RPC's EVM. Verification is the enforcement
boundary: captured status, output, gas, logs, and state must match the pinned
Monad C++ implementation before measurement starts.

Foundry v1.8.0 or newer provides first-class Monad execution and implements
`MonadTen`, including MIP-8 page-based storage accounting. Start a local node
with an explicit network and hardfork when preparing `MONAD_TEN` fixtures:

```bash
anvil --network monad --hardfork MonadTen
```

`MonadTen` is also the default for local Monad execution in Foundry v1.8.0,
but selecting it explicitly keeps the saved workflow independent of defaults.
The verifier rejects an RPC schedule mismatch instead of benchmarking it.

## Repository integration test

On the supported Linux build host, with Monad-enabled `forge` and `anvil` on
`PATH`, run:

```bash
PYTHONPATH=capture python3 tests/capture/anvil_roundtrip.py \
  --verifier ./build/monad-execbench
```

`--forge` and `--anvil` accept explicit binary paths. The test requires Foundry
v1.8.0 or newer, launches Anvil with `MonadTen`, deploys fresh probe contracts,
and covers ABI-generated calldata, a nested reverted read, direct storage reads
and writes, a root revert, logs, access-list warming, metadata, capture,
two-mode verification, and a short `dual-hot` run.
