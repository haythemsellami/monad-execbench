from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

from . import __version__
from .markdown import render_report
from .results import ReportError, load_comparisons, load_run, require


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="monad-execbench-report",
        description="Generate a Markdown report from saved monad-execbench JSON; never execute benchmarks",
    )
    result.add_argument(
        "--input",
        required=True,
        action="append",
        metavar="NAME=RESULTS.json",
        help="named input; repeat for multiple runs or modes",
    )
    result.add_argument(
        "--comparisons",
        type=Path,
        help="explicit baseline/candidate comparison manifest",
    )
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--title", default="Direct-VM benchmark report")
    result.add_argument(
        "--force",
        action="store_true",
        help="replace an existing report, never an input file",
    )
    result.add_argument("--version", action="version", version=__version__)
    return result


def write_report(output: Path, content: str, *, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # Write completely before publishing. A failed validation/write cannot leave
    # a partial report or truncate a previous one.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if force:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        paths: dict[str, Path] = {}
        for value in arguments.input:
            name, separator, filename = value.partition("=")
            require(
                bool(separator)
                and bool(filename)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is not None,
                "--input must be NAME=PATH with an alphanumeric, dot, dash, or underscore name",
            )
            require(name not in paths, f"duplicate input name: {name}")
            path = Path(filename).resolve()
            require(
                not any(path.samefile(other) for other in paths.values()),
                "duplicate input file",
            )
            paths[name] = path
        sources = [*paths.values()]
        if arguments.comparisons:
            sources.append(arguments.comparisons.resolve())
        output = arguments.output.absolute()
        require(not output.is_symlink(), "output must not be a symbolic link")
        require(
            not any(
                output.resolve() == source
                or (output.exists() and output.samefile(source))
                for source in sources
            ),
            "output must not overwrite an input or comparison manifest",
        )
        require(
            arguments.force or not output.exists(),
            "output already exists; use --force to replace it",
        )
        runs = {}
        for name, path in paths.items():
            try:
                runs[name] = load_run(name, path)
            except ReportError as error:
                raise ReportError(f"input {name}: {error}") from error
        comparisons, digest = (
            load_comparisons(arguments.comparisons, runs)
            if arguments.comparisons
            else ([], None)
        )
        report = render_report(
            runs,
            comparisons,
            title=arguments.title,
            comparison_source=str(arguments.comparisons.resolve())
            if arguments.comparisons
            else None,
            comparison_sha256=digest,
        )
        write_report(output, report, force=arguments.force)
        print(
            f"reported {sum(len(run.cases) for run in runs.values())} case(s), {len(comparisons)} comparison(s)"
        )
        print(f"report={output}")
        return 0
    except (ReportError, OSError) as error:
        print(f"report failed: {error}", file=sys.stderr)
        return 1
