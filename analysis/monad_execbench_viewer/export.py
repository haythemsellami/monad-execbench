from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from monad_execbench_report.results import load_comparisons, load_run, require

SCHEMA = "monad-execbench/viewer-v1"
MAX_INPUT = 512 * 1024 * 1024


def bounded_file(path: Path) -> Path:
    path = path.resolve(strict=True)
    require(
        path.is_file() and path.stat().st_size <= MAX_INPUT,
        "input must be a file <= 512 MiB",
    )
    return path


def safe_numbers(value):
    """Keep large integers exact when results reach JavaScript."""
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: safe_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_numbers(item) for item in value]
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            safe_numbers(value),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def ratio(candidate, baseline):
    if not baseline:
        return None
    value = candidate / baseline
    return value if math.isfinite(value) else None


def export(
    inputs: list[str], profiles: list[Path], comparisons: Path | None, output: Path
) -> dict:
    require(
        not output.exists() and not output.is_symlink(),
        "output already exists; choose a new directory",
    )
    runs = {}
    for value in inputs:
        alias, separator, filename = value.partition("=")
        require(
            bool(separator)
            and bool(filename)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", alias),
            "input must be NAME=FILE",
        )
        require(alias not in runs, "duplicate input name")
        path = bounded_file(Path(filename))
        require(
            all(not path.samefile(run.path) for run in runs.values()),
            "duplicate input file",
        )
        runs[alias] = load_run(alias, path)
    require(bool(runs), "at least one timing input is required")
    pairs, comparison_hash = (
        load_comparisons(bounded_file(comparisons), runs) if comparisons else ([], None)
    )
    summary = {
        "schema": SCHEMA,
        "runs": [],
        "comparisons": [],
        "profiles": [],
        "comparison_sha256": comparison_hash,
    }
    lookup = {}
    for index, run in enumerate(runs.values()):
        cases = []
        for case_index, case in enumerate(run.cases.values()):
            entry = {"id": f"r{index}-c{case_index}", **asdict(case), "profile": None}
            cases.append(entry)
            lookup[(run.alias, case.name)] = entry
        summary["runs"].append(
            {
                "id": f"r{index}",
                "name": run.alias,
                "file": run.path.name,
                "sha256": run.sha256,
                "context": run.context,
                "warnings": run.warnings,
                "cases": cases,
            }
        )
    for pair in pairs:
        summary["comparisons"].append(
            {
                "name": pair.name,
                "baseline": lookup[(pair.baseline_run.alias, pair.baseline.name)]["id"],
                "candidate": lookup[(pair.candidate_run.alias, pair.candidate.name)][
                    "id"
                ],
                "mode": pair.baseline_run.context["benchmark_mode"],
                "gas_ratio": ratio(pair.candidate.gas, pair.baseline.gas),
                "cpu_ratio": ratio(pair.candidate.cpu.median, pair.baseline.cpu.median),
                "wall_ratio": ratio(
                    pair.candidate.wall.median, pair.baseline.wall.median
                ),
            }
        )
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".viewer-", dir=output.parent) as staging:
        temporary = Path(staging)
        if profiles:
            from .profiles import add_profiles

            add_profiles(summary, profiles, temporary)
        write_json(temporary / "summary.json", summary)
        # Reserve the name exclusively, then replace only our empty reservation
        # with the complete dataset in one same-filesystem directory rename.
        output.mkdir()
        try:
            temporary.rename(output)
        except BaseException:
            try:
                output.rmdir()
            except OSError:
                # Never recursively remove an output modified by another writer.
                pass
            raise
    return summary
