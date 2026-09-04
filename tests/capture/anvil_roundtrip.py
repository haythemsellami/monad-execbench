from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from monad_execbench_capture import __version__
from monad_execbench_capture.capture import CALLS_SCHEMA, capture_suite, write_bundle
from monad_execbench_capture.rpc import RpcClient, RpcError

SENDER = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
ROOT = "0x1000000000000000000000000000000000000001"
CHILD = "0x1000000000000000000000000000000000000002"
STORAGE_WRITER = "0x1000000000000000000000000000000000000003"
REVERTER = "0x1000000000000000000000000000000000000004"
LOGGER = "0x1000000000000000000000000000000000000005"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_rpc(rpc: RpcClient, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Anvil exited with status {process.returncode}")
        try:
            rpc.call("web3_clientVersion", [])
            return
        except RpcError:
            time.sleep(0.05)
    raise RuntimeError("Anvil did not start within 10 seconds")


def install_probe_contracts(rpc: RpcClient) -> None:
    contracts = {
        CHILD: "0x60015460005260206000fd",
        ROOT: (
            "0x5f5f5f5f5f73"
            "1000000000000000000000000000000000000002"
            "61fffff15060025460005260206000f3"
        ),
        STORAGE_WRITER: "0x602a60015500",
        REVERTER: "0x63deadbeef6000526004601cfd",
        LOGGER: "0x60aa600053602a60016000a100",
    }
    for address, code in contracts.items():
        rpc.call("anvil_setCode", [address, code])


def calls_document() -> dict[str, object]:
    return {
        "schema": CALLS_SCHEMA,
        "cases": [
            {"name": "probe/nested-revert-read", "from": SENDER, "to": ROOT},
            {"name": "probe/storage-write", "from": SENDER, "to": STORAGE_WRITER},
            {"name": "probe/root-revert", "from": SENDER, "to": REVERTER},
            {"name": "probe/log", "from": SENDER, "to": LOGGER},
            {
                "name": "probe/access-list",
                "from": SENDER,
                "to": ROOT,
                "accessList": [
                    {"address": ROOT, "storageKeys": ["0x2"]},
                    {"address": CHILD, "storageKeys": ["0x1"]},
                ],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anvil", default="anvil")
    parser.add_argument("--verifier", required=True, type=Path)
    arguments = parser.parse_args()

    port = available_port()
    endpoint = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile() as anvil_stderr:
        process = subprocess.Popen(
            [arguments.anvil, "--monad", "--port", str(port), "--silent"],
            stdout=subprocess.DEVNULL,
            stderr=anvil_stderr,
        )
        failed = False
        try:
            rpc = RpcClient(endpoint)
            wait_for_rpc(rpc, process)
            install_probe_contracts(rpc)
            calls = calls_document()
            calls_bytes = (json.dumps(calls, indent=2) + "\n").encode()
            bundle = capture_suite(rpc, calls)
            with tempfile.TemporaryDirectory() as directory:
                fixture = Path(directory) / "fixture"
                write_bundle(
                    fixture,
                    bundle,
                    calls_bytes=calls_bytes,
                    monad_commit="integration-test",
                    capture_version=__version__,
                    created_at="2026-01-01T00:00:00Z",
                )
                result = subprocess.run(
                    [arguments.verifier, "verify", fixture],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                print(result.stdout, end="")
                if result.returncode != 0:
                    failed = True
                    print(result.stderr, end="", file=sys.stderr)
                    return result.returncode
                if "cases=5\nverification=passed\n" not in result.stdout:
                    raise RuntimeError("verifier did not report the expected summary")
            return 0
        except BaseException:
            failed = True
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if failed:
                anvil_stderr.seek(0)
                log = anvil_stderr.read().decode(errors="replace")
                if log:
                    print("Anvil stderr:", file=sys.stderr)
                    print(log, end="", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
