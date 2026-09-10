from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .report import attribute, markdown
from .sources import load_build_info


def write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hard-link publication is atomic and cannot overwrite an existing file,
    # including a dangling symlink. No partial report is published on failure.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.link(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Map verified interpreter diagnostics to Foundry Solidity source maps (not CPU time)"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument(
        "--build-info",
        type=Path,
        action="append",
        required=True,
        help="Complete build-info JSON or directory; repeat for dependencies",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New Markdown report path (never overwritten)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional new machine-readable attribution report",
    )
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.top < 1:
            raise ValueError("--top must be positive")
        outputs = [args.output] + ([args.json_output] if args.json_output else [])
        if len({path.resolve() for path in outputs}) != len(outputs):
            raise ValueError("output paths must differ")
        if any(os.path.lexists(path) for path in outputs):
            raise ValueError("output already exists; choose new output paths")
        artifacts, builds = load_build_info(args.build_info)
        report = attribute(args.diagnostics.read_bytes(), artifacts, builds)
        rendered = markdown(report, args.top)
        if args.json_output:
            write_new(args.json_output, json.dumps(report, indent=2) + "\n")
        write_new(args.output, rendered)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RecursionError,
    ) as error:
        print(f"attribution failed: {error}", file=sys.stderr)
        return 1
    print(f"Attribution report: {args.output}")
    return 0
