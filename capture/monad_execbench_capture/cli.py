from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import __version__
from .capture import (
    DEFAULT_EXECUTION_ENV,
    CaptureError,
    capture_suite,
    load_calls_document,
    write_bundle,
)
from .rpc import RpcClient, RpcError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="monad-execbench-capture",
        description="Capture a portable monad-execbench fixture suite",
    )
    result.add_argument("--rpc-url", required=True)
    result.add_argument("--calls", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--block", default="latest")
    result.add_argument("--execution-env", default=DEFAULT_EXECUTION_ENV)
    result.add_argument("--monad-commit")
    result.add_argument("--timeout", type=float, default=30.0)
    result.add_argument("--force", action="store_true")
    result.add_argument("--version", action="version", version=__version__)
    return result


def detect_monad_commit() -> str:
    repository = Path(__file__).resolve().parents[2]
    monad = repository / "third_party" / "monad"
    try:
        return subprocess.run(
            ["git", "-C", str(monad), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise CaptureError(
            "cannot determine the pinned Monad commit; pass --monad-commit"
        ) from error


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        calls_bytes = arguments.calls.read_bytes()
        calls_document = load_calls_document(calls_bytes)
        rpc = RpcClient(arguments.rpc_url, arguments.timeout)
        bundle = capture_suite(
            rpc,
            calls_document,
            block_selector=arguments.block,
            execution_env=arguments.execution_env,
        )
        write_bundle(
            arguments.output,
            bundle,
            calls_bytes=calls_bytes,
            monad_commit=arguments.monad_commit or detect_monad_commit(),
            capture_version=__version__,
            force=arguments.force,
        )
        print(f"captured {len(bundle.cases)} case(s) at block {bundle.block_number}")
        print(f"fixture={arguments.output.resolve()}")
        return 0
    except (CaptureError, RpcError, OSError) as error:
        print(f"capture failed: {error}", file=sys.stderr)
        return 1
