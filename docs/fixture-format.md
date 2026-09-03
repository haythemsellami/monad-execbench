# Portable fixture format

`monad-execbench verify` consumes a directory containing four files:

```text
fixture-suite/
|-- manifest.json
|-- cases.json
|-- state.json.zst
`-- provenance.json
```

`state.json` is also accepted for small, reviewable fixtures. A compressed
state file must be a Zstandard frame with its decompressed size recorded in
the frame header. Every encoded fixture file and every decompressed Zstandard
payload is limited to 512 MiB.

## Manifest

The first schema version is `monad-execbench/v1`:

```json
{
  "schema": "monad-execbench/v1",
  "chain": {
    "chainId": "143",
    "executionEnv": "MONAD_TEN"
  },
  "block": {
    "number": "97663468",
    "hash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "timestamp": "0x0",
    "gasLimit": "0xbebc200",
    "baseFee": "0x0",
    "beneficiary": "0x0000000000000000000000000000000000000000",
    "prevRandao": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "blockHashes": {}
  },
  "state": "state.json.zst",
  "cases": "cases.json"
}
```

Unsigned quantities may be JSON integers, decimal strings, or `0x`-prefixed
strings. Addresses and 32-byte values must have their full fixed width.
`blockHashes` is optional;
`parentHash` automatically supplies the hash for `number - 1`. Older block
hashes used by the `BLOCKHASH` opcode must be included in `blockHashes`.

The only execution environment currently supported is `MONAD_TEN`. The
`--execution-env` flag may select an environment explicitly, but it must match
the value recorded by the fixture.

## State

State is an explicit map of present accounts plus an explicit list of accounts
known to be absent:

```json
{
  "accounts": {
    "0x1111111111111111111111111111111111111111": {
      "balance": "0",
      "nonce": "1",
      "code": "0x60015460005260206000f3",
      "codeHash": "0x98ad3660b57cc327f74bd024b5b409dc9a1ccd0eadbc69f6e703a5b3db7bbf9d",
      "storage": {
        "0x0000000000000000000000000000000000000000000000000000000000000001": "0x0000000000000000000000000000000000000000000000000000000000000000"
      }
    }
  },
  "absentAccounts": [
    "0x2222222222222222222222222222222222222222"
  ]
}
```

Every present account requires `balance`, `nonce`, `code`, `codeHash`, and
`storage`. The loader recomputes and checks `codeHash`. A zero-valued storage
slot must still appear in `storage`; omission means that the slot was not
captured. This distinction lets verification reject incomplete state instead
of substituting zero.

Any account that execution probes and finds nonexistent must appear in
`absentAccounts`. This includes the block beneficiary when it is absent.

## Cases

`cases.json` is a non-empty array:

```json
[
  {
    "name": "example/case-a",
    "message": {
      "from": "0x3333333333333333333333333333333333333333",
      "to": "0x1111111111111111111111111111111111111111",
      "input": "0x",
      "value": "0",
      "gas": "1000000",
      "gasPrice": "0",
      "accessList": []
    },
    "expected": {
      "status": "success",
      "output": "0x0000000000000000000000000000000000000000000000000000000000000000",
      "gasUsed": "8115",
      "logs": [],
      "state": {
        "0x1111111111111111111111111111111111111111": {
          "nonce": "1",
          "storage": {
            "0x0000000000000000000000000000000000000000000000000000000000000001": "0x0000000000000000000000000000000000000000000000000000000000000000"
          }
        }
      }
    }
  }
]
```

`status` is `success` or `revert`. `gasUsed` is execution gas for the supplied
root message, excluding transaction intrinsic gas. `logs` and `state` are
optional; when present, they are exact assertions. A state assertion may
contain any combination of `balance`, `nonce`, `code`, and `storage`.

Each case starts from the same state file. State changes made by one case are
not visible to another case or to the second VM mode.

## Provenance

`provenance.json` must be a JSON object. The verifier currently preserves the
file as a required bundle boundary but does not interpret its fields. Capture
tooling will populate the provenance fields and content hashes defined in the
project specification.

## Verification behavior

The verifier runs each case in `InterpreterOnly` and `Dual` modes using
`MonadTraits<MONAD_TEN>`, the production EVM host, and Monad's page-encoded
in-memory state engine. Nested calls, storage, logs, and frame rollback use the
same execution code as the client.

Verification fails on:

- Invalid schema or malformed fixed-width values.
- Runtime bytecode that does not match its declared code hash.
- Status, output, execution-gas, log, or selected post-state mismatch.
- A difference between interpreter and dual-mode results.
- Any uncaptured account, runtime code, storage slot, or requested block hash.
