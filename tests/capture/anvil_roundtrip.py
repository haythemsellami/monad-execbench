from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from monad_execbench_capture import __version__
from monad_execbench_capture.capture import (
    capture_suite,
    load_calls_document,
    write_bundle,
)
from monad_execbench_capture.rpc import RpcClient, RpcError

ANVIL_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
REPOSITORY = Path(__file__).resolve().parents[2]
FOUNDRY_ROOT = REPOSITORY / "foundry"


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


def pinned_monad_commit() -> str:
    return subprocess.run(
        ["git", "-C", REPOSITORY / "third_party" / "monad", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def monad_network_arguments(anvil: str) -> list[str]:
    help_text = subprocess.run(
        [anvil, "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "--network <NETWORK>" in help_text and "monad" in help_text:
        return ["--network", "monad", "--hardfork", "MonadTen"]
    raise RuntimeError(
        f"{anvil} does not expose first-class Monad support; use Foundry v1.8.0 or newer"
    )


def prepare_calls(forge: str, endpoint: str, output: Path) -> bytes:
    environment = os.environ.copy()
    environment["EXECBENCH_PRIVATE_KEY"] = ANVIL_PRIVATE_KEY
    environment["EXECBENCH_CALLS_PATH"] = str(output)
    result = subprocess.run(
        [
            forge,
            "script",
            "script/PrepareIntegration.s.sol:PrepareIntegration",
            "--rpc-url",
            endpoint,
            "--broadcast",
        ],
        cwd=FOUNDRY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Foundry preparation failed\n" + result.stdout + result.stderr
        )
    return output.read_bytes()


def run_benchmark(verifier: Path, fixture: Path, output: Path) -> None:
    result = subprocess.run(
        [
            verifier,
            "run",
            fixture,
            "--mode",
            "dual-hot",
            "--repetitions",
            "2",
            "--output",
            output,
            "--",
            "--benchmark_min_time=0.001s",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
        raise RuntimeError("benchmark command failed")

    report = json.loads(output.read_text())
    if report["context"]["execution_env"] != "MONAD_TEN":
        raise RuntimeError(
            "benchmark report did not preserve the execution environment"
        )
    iterations = [
        entry for entry in report["benchmarks"] if entry["run_type"] == "iteration"
    ]
    if len(iterations) != 12:
        raise RuntimeError("benchmark report did not contain two runs for six cases")
    metadata_runs = [
        entry for entry in iterations if "probe/storage-read" in entry["name"]
    ]
    if len(metadata_runs) != 2:
        raise RuntimeError("benchmark report omitted the metadata case")
    for entry in metadata_runs:
        label = json.loads(entry["label"])
        if (
            entry["input_value"] != 1
            or label["labels"]["operation"] != "storage-read"
            or label["counters"]["input_value"] != "1"
        ):
            raise RuntimeError("benchmark report did not preserve case metadata")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anvil", default="anvil")
    parser.add_argument("--forge", default="forge")
    parser.add_argument("--verifier", required=True, type=Path)
    arguments = parser.parse_args()

    port = available_port()
    endpoint = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile() as anvil_stderr:
        process = subprocess.Popen(
            [
                arguments.anvil,
                *monad_network_arguments(arguments.anvil),
                "--port",
                str(port),
                "--silent",
            ],
            stdout=subprocess.DEVNULL,
            stderr=anvil_stderr,
        )
        failed = False
        try:
            rpc = RpcClient(endpoint)
            wait_for_rpc(rpc, process)
            FOUNDRY_ROOT.joinpath("out").mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".execbench-integration-", dir=FOUNDRY_ROOT / "out"
            ) as directory:
                calls_path = Path(directory) / "calls.json"
                calls_bytes = prepare_calls(arguments.forge, endpoint, calls_path)
                calls = load_calls_document(calls_bytes)
                bundle = capture_suite(rpc, calls)
                fixture = Path(directory) / "fixture"
                write_bundle(
                    fixture,
                    bundle,
                    calls_bytes=calls_bytes,
                    monad_commit=pinned_monad_commit(),
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
                if "cases=6\nverification=passed\n" not in result.stdout:
                    raise RuntimeError("verifier did not report the expected summary")
                run_benchmark(
                    arguments.verifier,
                    fixture,
                    Path(directory) / "benchmark.json",
                )
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
