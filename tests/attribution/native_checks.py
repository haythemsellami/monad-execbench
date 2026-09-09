"""Regression checks for the pinned native diagnostic hooks; no RPC required."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from Crypto.Hash import keccak
from monad_execbench_attribution.report import attribute

ROOT = Path(__file__).resolve().parents[2]
PARENT = "0x2000000000000000000000000000000000000001"
CHILD = "0x2000000000000000000000000000000000000004"


def digest(raw: bytes) -> str:
    return "0x" + hashlib.sha256(raw).hexdigest()


def fixture(
    directory: Path, code: str, gas: int, output="0x", *, child="00", status="success"
) -> None:
    base = ROOT / "tests/fixtures/synthetic"
    manifest = (base / "manifest.json").read_bytes()
    case = json.loads((base / "cases.json").read_bytes())[0]
    case["expected"] = {
        "status": status,
        "output": output,
        "gasUsed": str(gas),
        "logs": [],
    }
    state = json.loads((base / "state.json").read_bytes())
    identity = copy.deepcopy(state["accounts"][case["message"]["from"]])
    identity["balance"] = "0"
    state["accounts"]["0x" + "0" * 39 + "4"] = identity
    # CREATE address for the parent account's initial nonce of one.
    created = keccak.new(
        digest_bits=256, data=bytes.fromhex("d694" + PARENT[2:] + "01")
    ).digest()[-20:]
    state["absentAccounts"].append("0x" + created.hex())
    for address, bytecode in ((PARENT, code), (CHILD, child)):
        state["accounts"][address]["code"] = "0x" + bytecode
        state["accounts"][address]["codeHash"] = (
            "0x" + keccak.new(digest_bits=256, data=bytes.fromhex(bytecode)).hexdigest()
        )
    cases = json.dumps([case]).encode()
    state_raw = json.dumps(state).encode()
    provenance = json.loads((base / "provenance.json").read_bytes())
    hashes = [digest(value) for value in (manifest, cases, state_raw)]
    provenance["files"] = dict(
        zip(("manifest.json", "cases.json", "state.json"), hashes)
    )
    provenance["normalized"] = dict(
        zip(("manifestSha256", "casesSha256", "stateSha256"), hashes)
    )
    provenance["normalized"]["bundleSha256"] = digest("".join(hashes).encode())
    for name, raw in (
        ("manifest.json", manifest),
        ("cases.json", cases),
        ("state.json", state_raw),
        ("provenance.json", json.dumps(provenance).encode()),
    ):
        (directory / name).write_bytes(raw)


def run(runner: Path, path: Path) -> dict:
    result = subprocess.run([runner, path], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    report = attribute(result.stdout, [], [])
    return report["cases"][0]


def check(runner: Path) -> None:
    raw = subprocess.run(
        [runner, ROOT / "tests/fixtures/synthetic"], capture_output=True, check=True
    ).stdout
    report = attribute(raw, [], [])
    assert len(report["cases"]) == 5
    assert report["cases"][0]["steps"] == 6
    nested = report["cases"][3]
    assert [frame["status"] for frame in nested["frames"]] == ["success", "revert"]
    assert nested["frames"][0]["self_gas"] == 10131
    assert nested["frames"][1]["self_gas"] == 28697
    with tempfile.TemporaryDirectory(
        prefix="execbench-native-attribution-"
    ) as temporary:
        path = Path(temporary)
        # Two 32-byte words cost one gas in MONAD_TEN; this is charged by
        # Context::copy_to_evmc_result, after the interpreter trampoline returns.
        for opcode, status in (("f3", "success"), ("fd", "revert")):
            fixture(path, "60405f" + opcode, 6, "0x" + "00" * 64, status=status)
            case = run(runner, path)
            assert case["outside_vm_gas"] == 0
            assert case["frames"][0]["pcs"][-1]["gas"] == 1
        fixture(path, "60", 3)
        case = run(runner, path)
        assert case["steps"] == 2
        assert case["frames"][0]["pcs"][-1]["mapping"] == "implicit-stop"
        fixture(path, "", 0)
        case = run(runner, path)
        assert case["gas_used"] == 0
        assert case["frames"][0]["pcs"][0]["mapping"] == "implicit-stop"
        fixture(path, "5f5f5ff05000", 32008)
        case = run(runner, path)
        assert case["frames"][1]["code_kind"] == "creation"
        assert case["frames"][1]["artifact_match"]["status"] == "creation-code"
        parent = "5f5f5f5f5f73" + CHILD[2:] + "6064f15000"
        for child in ("fe", "7f" + "ff" * 32 + "5ff3"):
            fixture(path, parent, 10218, child=child)
            case = run(runner, path)
            assert case["outside_vm_gas"] == 0
            assert case["frames"][1]["status"] == "error"
            assert case["frames"][1]["gas_used"] == 100
        parent = "60205f5f5f73" + CHILD[2:] + "6064f45060205ff3"
        fixture(
            path, parent, 10134, "0x" + "00" * 12 + PARENT[2:], child="305f5260205ff3"
        )
        case = run(runner, path)
        assert case["frames"][1]["recipient"] == PARENT
        assert case["frames"][1]["code_hash"] != case["frames"][0]["code_hash"]
        fixture(path, "5f5f5f5f60045afa5000", 130)
        case = run(runner, path)
        assert len(case["frames"]) == 1
        assert (
            next(item for item in case["frames"][0]["pcs"] if item["opcode"] == 0xFA)[
                "gas"
            ]
            == 115
        )
        # Missing-state detection must still fail before publishing diagnostics.
        failure = subprocess.run(
            [runner, ROOT / "tests/fixtures/incomplete"],
            capture_output=True,
            check=False,
        )
        assert failure.returncode and not failure.stdout
        assert b"uncaptured storage" in failure.stderr
        bad = copy.deepcopy(json.loads(raw))
        bad["cases"][0]["frames"][0]["self_gas"] += 1
        try:
            attribute(json.dumps(bad).encode(), [], [])
        except ValueError:
            pass
        else:
            raise AssertionError("non-reconciling diagnostics accepted")
    print(
        "native attribution: nested calls/reverts, return memory, errors, delegatecall, precompile, implicit STOP, empty code, and incomplete state passed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics", required=True, type=Path)
    check(parser.parse_args().diagnostics.resolve())
