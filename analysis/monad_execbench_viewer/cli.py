from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .export import export
from .server import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export and explore saved benchmark results locally; never execute contracts"
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "export", help="validate inputs and write a compact, lazy-loaded dataset"
    )
    prepare.add_argument("--input", action="append", required=True, metavar="NAME=FILE")
    prepare.add_argument(
        "--profile",
        action="append",
        default=[],
        type=Path,
        help="diagnostics-v1 or attribution-v1 JSON; repeat for multiple fixtures",
    )
    prepare.add_argument("--comparisons", type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    serve = commands.add_parser(
        "serve", help="serve an exported dataset on loopback only"
    )
    serve.add_argument("directory", type=Path)
    serve.add_argument("--port", type=int, default=0)
    options = parser.parse_args(argv)
    try:
        if options.command == "export":
            result = export(
                options.input, options.profile, options.comparisons, options.output
            )
            print(f"exported {len(result['runs'])} run(s): {options.output.resolve()}")
        else:
            if not 0 <= options.port <= 65535:
                parser.error("port must be between 0 and 65535")
            with create_server(options.directory, options.port) as server:
                print(
                    f"Viewer: http://127.0.0.1:{server.server_port}\nRead-only local results. Ctrl-C to stop.",
                    flush=True,
                )
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
        RecursionError,
    ) as error:
        print(f"viewer: {error}", file=sys.stderr)
        return 1
