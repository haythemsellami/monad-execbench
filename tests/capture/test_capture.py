from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import zstandard
from monad_execbench_capture.capture import (
    CALLS_SCHEMA,
    EMPTY_CODE_HASH,
    EMPTY_STORAGE_ROOT,
    CaptureBundle,
    CaptureError,
    capture_suite,
    collect_logs,
    derive_execution_gas,
    load_calls_document,
    sha256,
    write_bundle,
)

ZERO_ADDRESS = "0x" + "00" * 20
SENDER = "0x" + "11" * 20
TARGET = "0x" + "22" * 20
BLOCK_HASH = "0x" + "aa" * 32
PARENT_HASH = "0x" + "bb" * 32
CODE_HASH = "0x" + "cc" * 32


class FakeRpc:
    def call(self, method: str, params: list[Any]) -> Any:
        if method == "eth_getBlockByNumber":
            return {
                "number": "0x0",
                "hash": BLOCK_HASH,
                "parentHash": PARENT_HASH,
                "timestamp": "0x123",
                "gasLimit": "0xf4240",
                "baseFeePerGas": "0x0",
                "miner": ZERO_ADDRESS,
                "mixHash": "0x" + "33" * 32,
            }
        if method == "eth_chainId":
            return "0x8f"
        if method == "debug_traceCall":
            tracer = params[2]["tracer"]
            if tracer == "callTracer":
                return {
                    "from": SENDER,
                    "to": TARGET,
                    "gas": "0xef038",
                    "gasUsed": "0x520d",
                    "output": "0x2a",
                    "type": "CALL",
                }
            if params[2].get("tracerConfig", {}).get("diffMode"):
                return {"pre": {}, "post": {SENDER: {"nonce": "0x1"}}}
            return {
                ZERO_ADDRESS: {"balance": "0x0"},
                SENDER: {"balance": "0x1"},
                TARGET: {"balance": "0x0", "code": "0x00"},
            }
        if method == "eth_getProof":
            address = params[0]
            if address == ZERO_ADDRESS:
                return self._proof(address, 0, EMPTY_CODE_HASH)
            if address == SENDER:
                return self._proof(address, 1, EMPTY_CODE_HASH)
            if address == TARGET:
                return self._proof(address, 0, CODE_HASH)
        if method == "eth_getCode":
            return "0x00" if params[0] == TARGET else "0x"
        if method == "web3_sha3":
            return CODE_HASH if params[0] == "0x00" else EMPTY_CODE_HASH
        raise AssertionError(f"unexpected RPC call: {method} {params}")

    def batch(self, method: str, params: list[list[Any]]) -> list[Any]:
        raise AssertionError(f"unexpected RPC batch: {method} {params}")

    @staticmethod
    def _proof(address: str, balance: int, code_hash: str) -> dict[str, Any]:
        return {
            "address": address,
            "balance": hex(balance),
            "nonce": "0x0",
            "codeHash": code_hash,
            "storageHash": EMPTY_STORAGE_ROOT,
            "storageProof": [],
        }


class CaptureTest(unittest.TestCase):
    def test_load_calls_document_rejects_unknown_schema(self) -> None:
        with self.assertRaisesRegex(CaptureError, "calls.schema"):
            load_calls_document(b'{"schema":"wrong","cases":[]}')

    def test_capture_rejects_unknown_case_fields(self) -> None:
        calls = {
            "schema": CALLS_SCHEMA,
            "cases": [
                {
                    "name": "example/typo",
                    "from": SENDER,
                    "to": TARGET,
                    "data": "0x",
                }
            ],
        }
        with self.assertRaisesRegex(CaptureError, "unknown field 'data'"):
            capture_suite(FakeRpc(), calls)

    def test_capture_normalizes_case_metadata(self) -> None:
        calls = {
            "schema": CALLS_SCHEMA,
            "cases": [
                {
                    "name": "example/metadata",
                    "from": SENDER,
                    "to": TARGET,
                    "metadata": {
                        "labels": {
                            "implementation": "example-a",
                            "candidate_set": "all",
                        },
                        "counters": {"amount_in": "0xde0b6b3a7640000"},
                    },
                }
            ],
        }
        bundle = capture_suite(FakeRpc(), calls)
        self.assertEqual(
            bundle.cases[0]["metadata"],
            {
                "labels": {
                    "candidate_set": "all",
                    "implementation": "example-a",
                },
                "counters": {"amount_in": "1000000000000000000"},
            },
        )

    def test_capture_rejects_invalid_metadata(self) -> None:
        base = {
            "name": "example/metadata",
            "from": SENDER,
            "to": TARGET,
        }
        invalid_metadata = [
            ({}, "expected at least one label or counter"),
            ({"labels": {"bad key": "x"}}, "invalid metadata key"),
            ({"labels": {"valid": 1}}, "expected a string"),
            (
                {"counters": {"execution_gas": 1}},
                "counter name is reserved",
            ),
            ({"counters": {"amount": -1}}, "expected an unsigned quantity"),
        ]
        for metadata, expected in invalid_metadata:
            with self.subTest(metadata=metadata):
                calls = {
                    "schema": CALLS_SCHEMA,
                    "cases": [{**base, "metadata": metadata}],
                }
                with self.assertRaisesRegex(CaptureError, expected):
                    capture_suite(FakeRpc(), calls)

    def test_derive_execution_gas_removes_intrinsic_gas(self) -> None:
        self.assertEqual(
            derive_execution_gas(
                1_000_000, {"gas": "0xef038", "gasUsed": "0xb8f4"}, "trace"
            ),
            (979_000, 26_348),
        )

    def test_derive_execution_gas_rejects_evmc_overflow(self) -> None:
        with self.assertRaisesRegex(CaptureError, "EVMC signed range"):
            derive_execution_gas(
                1 << 63, {"gas": hex(1 << 63), "gasUsed": "0x0"}, "trace"
            )

    def test_collect_logs_ignores_reverted_frames_and_orders_positions(self) -> None:
        topic = "0x" + "44" * 32
        logs = collect_logs(
            {
                "logs": [
                    {
                        "address": TARGET,
                        "data": "0x02",
                        "topics": [topic],
                        "position": "0x2",
                    }
                ],
                "calls": [
                    {
                        "logs": [
                            {
                                "address": SENDER,
                                "data": "0x01",
                                "topics": [],
                                "position": "0x1",
                            }
                        ]
                    },
                    {
                        "error": "execution reverted",
                        "logs": [
                            {
                                "address": ZERO_ADDRESS,
                                "data": "0xff",
                                "topics": [],
                                "position": "0x0",
                            }
                        ],
                    },
                ],
            }
        )
        self.assertEqual([entry["data"] for entry in logs], ["0x01", "0x02"])

    def test_capture_suite_normalizes_a_successful_call(self) -> None:
        calls = {
            "schema": CALLS_SCHEMA,
            "cases": [
                {
                    "name": "example/success",
                    "from": SENDER,
                    "to": TARGET,
                    "gas": "0xf4240",
                }
            ],
        }
        bundle = capture_suite(FakeRpc(), calls)
        self.assertEqual(bundle.manifest["chain"]["chainId"], "143")
        self.assertEqual(bundle.cases[0]["message"]["gas"], "979000")
        self.assertEqual(bundle.cases[0]["expected"]["gasUsed"], "5")
        self.assertNotIn("state", bundle.cases[0]["expected"])
        self.assertEqual(bundle.state["absentAccounts"], [ZERO_ADDRESS])
        self.assertEqual(set(bundle.state["accounts"]), {SENDER, TARGET})

    def test_write_bundle_is_complete_and_compressed(self) -> None:
        bundle = CaptureBundle(
            manifest={
                "schema": "monad-execbench/v1",
                "chain": {"chainId": "143", "executionEnv": "MONAD_TEN"},
                "state": "state.json.zst",
                "cases": "cases.json",
            },
            cases=[],
            state={"accounts": {}, "absentAccounts": []},
            chain_id=143,
            block_number=1,
            block_hash=BLOCK_HASH,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture"
            write_bundle(
                output,
                bundle,
                calls_bytes=b"{}\n",
                monad_commit="1" * 40,
                capture_version="test",
                created_at="2026-01-01T00:00:00Z",
            )
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"manifest.json", "cases.json", "state.json.zst", "provenance.json"},
            )
            state = json.loads(
                zstandard.ZstdDecompressor().decompress(
                    (output / "state.json.zst").read_bytes()
                )
            )
            self.assertEqual(state, bundle.state)
            provenance = json.loads((output / "provenance.json").read_text())
            self.assertNotIn("rpc", json.dumps(provenance).lower())
            for name in ("manifest.json", "cases.json", "state.json.zst"):
                self.assertEqual(
                    provenance["files"][name], sha256((output / name).read_bytes())
                )
            self.assertEqual(
                provenance["normalized"]["stateSha256"],
                sha256(
                    (json.dumps(bundle.state, indent=2, sort_keys=True) + "\n").encode()
                ),
            )


if __name__ == "__main__":
    unittest.main()
