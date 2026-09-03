# Fixture capture

`monad-execbench-capture` converts contract-agnostic call descriptions into a
self-contained fixture suite that the C++ verifier can replay without network
access.

## Installation

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

The capture utility requires Python 3.11 or newer. Its only runtime dependency
is `zstandard`, used to write `state.json.zst` with a declared content size.

## Call manifest

The input is a JSON document using `monad-execbench/calls-v1`:

```json
{
  "schema": "monad-execbench/calls-v1",
  "cases": [
    {
      "name": "example/case-a",
      "from": "0x1111111111111111111111111111111111111111",
      "to": "0x2222222222222222222222222222222222222222",
      "input": "0x12345678",
      "value": "0",
      "gas": "1000000",
      "gasPrice": "0",
      "accessList": []
    }
  ]
}
```

`input`, `value`, `gasPrice`, and `accessList` are optional. They default to
`0x`, zero, the selected block base fee, and an empty array. An explicit
`gasPrice` must be at least the block base fee. `gas` defaults to the selected
block gas limit. Case names must be unique. Contract creation is not supported
by this schema; every case requires a `to` address.

## Capturing a fixture

Use a Monad-compatible local fork and pin it to a stable block:

```bash
.venv/bin/monad-execbench-capture \
  --rpc-url http://127.0.0.1:8545 \
  --calls benchmark-calls.json \
  --block latest \
  --execution-env MONAD_TEN \
  --output fixtures/generated/example-suite
```

`latest` is resolved once to an exact block number and hash. Capture fails if
the hash changes before the bundle is complete. Existing output is preserved
unless `--force` is explicitly supplied.

The RPC must support:

- `debug_traceCall` with `prestateTracer`, including `diffMode`;
- `debug_traceCall` with `callTracer` and `withLog`;
- `eth_getProof`, `eth_getCode`, and `web3_sha3`;
- historical `eth_getBlockByNumber` queries.

Capture records the union of all accounts and storage slots accessed by every
case, including state read by nested calls that revert. Account and storage
proof responses distinguish captured zero values from missing state. The prior
256 block hashes are included so valid `BLOCKHASH` reads remain offline.

The call tracer supplies the root execution gas after transaction intrinsic
gas. The normalized fixture therefore contains the direct-VM gas limit and gas
used values expected by the C++ runner.

Expected output currently includes success or revert status, output data,
execution gas, logs, and storage/code/contract-nonce changes reported by the
prestate diff tracer. Sender nonce and balance changes are excluded because
they belong to the transaction envelope rather than the direct root VM call.
Balance assertions can be added when transaction-envelope normalization is
implemented.

## Verifying offline

After capture, stop the RPC process or move the fixture to another machine:

```bash
./build/monad-execbench verify fixtures/generated/example-suite
```

Both interpreter and production dual-mode execution must pass before the
fixture is suitable for benchmarking.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests/capture -v
.venv/bin/ruff check capture tests/capture
.venv/bin/ruff format --check capture tests/capture
```

When a Monad-enabled Anvil and the C++ runner are available on the same Linux
host, run the live capture-to-replay integration test:

```bash
.venv/bin/python tests/capture/anvil_roundtrip.py \
  --verifier ./build/monad-execbench
```

The integration test covers a successful nested call, state read inside a
reverted child frame, a storage write, a root revert with data, and an emitted
log. The generated fixture is then verified in both VM modes.
