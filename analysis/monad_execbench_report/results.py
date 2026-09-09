from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNITS_TO_US = {"ns": 0.001, "us": 1.0, "ms": 1000.0, "s": 1_000_000.0}
HASH_FIELDS = (
    "runner_sha256",
    "fixture_bundle_sha256",
    "fixture_manifest_sha256",
    "fixture_cases_sha256",
    "fixture_state_sha256",
    "block_hash",
)
TEXT_FIELDS = (
    "monad_execbench_version",
    "monad_execbench_commit",
    "monad_commit",
    "build_type",
    "compiler",
    "fixture_schema",
    "fixture_created_at",
    "capture_tool",
    "execution_env",
    "benchmark_mode",
    "case_filter",
    "host_name",
    "library_version",
    "library_build_type",
)
# Differences in these fields must never be hidden inside an implementation ratio.
COMPARABILITY_FIELDS = HASH_FIELDS + (
    "monad_execbench_version",
    "monad_execbench_commit",
    "monad_commit",
    "build_type",
    "compiler",
    "fixture_schema",
    "fixture_created_at",
    "capture_tool",
    "execution_env",
    "benchmark_mode",
    "block_number",
    "host_name",
    "num_cpus",
    "mhz_per_cpu",
    "caches",
    "cpu_scaling_enabled",
    "library_version",
    "library_build_type",
)
METRICS = ("execution_gas", "return_data_bytes", "log_count")
COMPARISON_SCHEMA = "monad-execbench/comparisons-v1"


class ReportError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReportError(message)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ReportError(f"non-finite JSON constant: {value}")


def _float(value: str) -> float:
    result = float(value)
    require(math.isfinite(result), "non-finite JSON number")
    return result


def parse_json(data: bytes | str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_object,
            parse_constant=_constant,
            parse_float=_float,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ReportError(f"invalid JSON: {error}") from error


def integer(value: Any, field: str, minimum: int = 0) -> int:
    require(
        type(value) is int and value >= minimum,
        f"{field}: expected integer >= {minimum}",
    )
    return value


def decimal_string(value: Any, field: str) -> int:
    require(
        isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value) is not None,
        f"{field}: expected unsigned decimal string",
    )
    try:
        return int(value)
    except ValueError as error:
        raise ReportError(f"{field}: decimal string is too large") from error


def number(value: Any, field: str) -> float:
    require(type(value) in (int, float), f"{field}: expected finite nonnegative number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ReportError(f"{field}: number is too large") from error
    require(
        math.isfinite(result) and result >= 0,
        f"{field}: expected finite nonnegative number",
    )
    return result


def counter(value: Any, field: str) -> int:
    result = number(value, field)
    require(
        result.is_integer() and result <= 2**53 - 1,
        f"{field}: expected an exactly representable unsigned counter",
    )
    return int(result)


@dataclass(frozen=True)
class Distribution:
    median: float
    mean: float
    minimum: float
    maximum: float
    stddev: float | None
    cv: float | None

    @classmethod
    def from_samples(cls, samples: list[float]) -> Distribution:
        try:
            mean = statistics.mean(samples)
            stddev = statistics.stdev(samples) if len(samples) > 1 else None
            cv = stddev / mean if stddev is not None and mean > 0 else None
            values = [mean, statistics.median(samples), min(samples), max(samples)]
            require(
                all(math.isfinite(x) for x in values + [stddev or 0, cv or 0]),
                "timing statistics overflow",
            )
            return cls(values[1], mean, values[2], values[3], stddev, cv)
        except (OverflowError, statistics.StatisticsError) as error:
            raise ReportError(f"cannot calculate timing statistics: {error}") from error


@dataclass(frozen=True)
class Case:
    name: str
    wall: Distribution
    cpu: Distribution
    repetitions: int
    iterations: int
    gas: int
    output_bytes: int
    logs: int
    status: str
    labels: dict[str, str]
    counters: dict[str, str]


@dataclass(frozen=True)
class Run:
    alias: str
    path: Path
    sha256: str
    context: dict[str, Any]
    cases: dict[str, Case]
    warnings: list[str]


@dataclass(frozen=True)
class Comparison:
    name: str
    baseline_run: Run
    baseline: Case
    candidate_run: Run
    candidate: Case


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    require(
        isinstance(row.get("label"), str), "raw repetition is missing its JSON label"
    )
    label = parse_json(row["label"])
    require(isinstance(label, dict), "label must be an object")
    require(label.get("status") in ("success", "revert"), "invalid label status")
    for field in ("labels", "counters"):
        values = label.get(field, {})
        require(isinstance(values, dict), f"label.{field}: expected object")
        for key, value in values.items():
            require(isinstance(value, str), f"label.{field}.{key}: expected string")
            if field == "counters":
                exact = decimal_string(value, f"label.counters.{key}")
                # Metadata may exceed double precision: display the exact label,
                # but still check that the emitted numeric approximation agrees.
                approximate = number(row.get(key), key)
                try:
                    require(
                        approximate == float(exact),
                        f"{key}: numeric and exact counter disagree",
                    )
                except OverflowError as error:
                    raise ReportError(f"{key}: counter is too large") from error
    return label


def _case(name: str, rows: list[dict[str, Any]], repetitions: int) -> Case:
    require(
        len(rows) == repetitions,
        f"{name}: expected {repetitions} raw repetitions, got {len(rows)}",
    )
    indexes: set[int] = set()
    wall: list[float] = []
    cpu: list[float] = []
    iterations = 0
    first_metadata = _metadata(rows[0])
    metrics = tuple(counter(rows[0].get(key), key) for key in METRICS)
    for row in rows:
        index = integer(row.get("repetition_index"), "repetition_index")
        require(
            index < repetitions and index not in indexes,
            f"{name}: duplicate or out-of-range repetition_index",
        )
        indexes.add(index)
        require(
            integer(row.get("repetitions"), "repetitions", 1) == repetitions,
            f"{name}: inconsistent repetition count",
        )
        require(
            integer(row.get("threads"), "threads", 1) == 1,
            f"{name}: only single-threaded samples are supported",
        )
        iterations += integer(row.get("iterations"), "iterations", 1)
        unit = row.get("time_unit")
        require(
            isinstance(unit, str) and unit in UNITS_TO_US,
            f"{name}: unsupported time_unit",
        )
        for key, values in (("real_time", wall), ("cpu_time", cpu)):
            value = number(row.get(key), key) * UNITS_TO_US[unit]
            require(math.isfinite(value), f"{name}: converted timing overflows")
            values.append(value)
        require(
            _metadata(row) == first_metadata,
            f"{name}: metadata changed between repetitions",
        )
        require(
            tuple(counter(row.get(key), key) for key in METRICS) == metrics,
            f"{name}: execution counters changed between repetitions",
        )
    return Case(
        name,
        Distribution.from_samples(wall),
        Distribution.from_samples(cpu),
        repetitions,
        iterations,
        *metrics,
        first_metadata["status"],
        first_metadata.get("labels", {}),
        first_metadata.get("counters", {}),
    )


def load_run(alias: str, path: Path) -> Run:
    data = path.read_bytes()
    document = parse_json(data)
    require(isinstance(document, dict), "result must be an object")
    context = document.get("context")
    require(isinstance(context, dict), "result.context must be an object")
    require(
        type(context.get("json_schema_version")) is int
        and context["json_schema_version"] == 1,
        "unsupported Google Benchmark JSON schema version",
    )
    for field in TEXT_FIELDS:
        require(
            isinstance(context.get(field), str) and bool(context[field].strip()),
            f"context.{field}: expected nonempty string",
        )
    for field in HASH_FIELDS:
        value = context.get(field)
        require(
            isinstance(value, str)
            and re.fullmatch(r"0x[0-9a-f]{64}", value) is not None,
            f"context.{field}: expected lowercase SHA-256/block hash",
        )
    require(
        context["fixture_schema"] == "monad-execbench/v1", "unsupported fixture schema"
    )
    require(
        context["benchmark_mode"] in ("dual-hot", "interpreter-hot"),
        "unsupported benchmark mode",
    )
    decimal_string(context.get("block_number"), "context.block_number")
    repetitions = decimal_string(
        context.get("requested_repetitions"), "context.requested_repetitions"
    )
    require(repetitions > 0, "requested_repetitions must be positive")
    integer(context.get("num_cpus"), "context.num_cpus", 1)
    if "cpu_scaling_enabled" in context:
        require(
            type(context["cpu_scaling_enabled"]) is bool,
            "cpu_scaling_enabled must be boolean",
        )
    rows = document.get("benchmarks")
    require(
        isinstance(rows, list) and bool(rows), "benchmarks must be a nonempty array"
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    aggregate_names: set[str] = set()
    for row in rows:
        require(isinstance(row, dict), "benchmark entry must be an object")
        require(
            type(row.get("error_occurred", False)) is bool,
            "error_occurred must be boolean",
        )
        require(
            not row.get("error_occurred") and not row.get("error_message"),
            f"benchmark failure: {row.get('name', '?')}: {row.get('error_message', 'unknown error')}",
        )
        run_name = row.get("run_name")
        require(isinstance(run_name, str), "benchmark entry is missing run_name")
        match = re.fullmatch(
            r"execute/(dual-hot|interpreter-hot)/(.+)/repeats:([0-9]+)",
            run_name,
            re.DOTALL,
        )
        require(match is not None, f"unsupported benchmark run_name: {run_name}")
        assert match is not None
        require(
            match[1] == context["benchmark_mode"]
            and decimal_string(match[3], "run_name repetitions") == repetitions,
            f"{run_name}: mode or repetition count disagrees with context",
        )
        name = match[2]
        kind = row.get("run_type")
        require(kind in ("iteration", "aggregate"), "unsupported benchmark run_type")
        if kind == "aggregate":
            aggregate_names.add(name)
            continue
        require(
            row.get("name") == run_name, f"{name}: raw name disagrees with run_name"
        )
        grouped.setdefault(name, []).append(row)
    require(
        bool(grouped),
        "raw repetitions are required; aggregate-only results cannot be reported",
    )
    require(
        aggregate_names <= grouped.keys(),
        "aggregate entry has no corresponding raw repetitions",
    )
    cases = {
        name: _case(name, rows, repetitions) for name, rows in sorted(grouped.items())
    }
    warnings: list[str] = []
    if context.get("cpu_scaling_enabled") is True:
        warnings.append(
            "CPU scaling is enabled; frequency changes can affect comparisons. Treat these timings as provisional."
        )
    elif "cpu_scaling_enabled" not in context:
        warnings.append("CPU-scaling state was not recorded.")
    if context["build_type"].lower() not in ("release", "relwithdebinfo", "minsizerel"):
        warnings.append(
            f"Runner build is not a recognized optimized build: {context['build_type']}."
        )
    if context["library_build_type"].lower() != "release":
        warnings.append("Google Benchmark was not built in release mode.")
    for field in ("monad_commit", "monad_execbench_commit"):
        if re.fullmatch(r"[0-9a-f]{40}", context[field]) is None:
            warnings.append(
                f"{field} is not an identified Git revision; cross-file ratios are unavailable."
            )
    for name, case in cases.items():
        if case.repetitions < 50:
            warnings.append(
                f"{name}: only {case.repetitions} repetitions; the standard protocol uses at least 50."
            )
        if any(x.cv is not None and x.cv > 0.05 for x in (case.wall, case.cpu)):
            warnings.append(
                f"{name}: timing CV exceeds 5%; investigate variability before drawing conclusions."
            )
        if case.wall.median == 0 or case.cpu.median == 0:
            warnings.append(
                f"{name}: a median timing is zero; timing ratios with that denominator are unavailable."
            )
    return Run(
        alias,
        path.resolve(),
        "0x" + hashlib.sha256(data).hexdigest(),
        context,
        cases,
        warnings,
    )


def load_comparisons(path: Path, runs: dict[str, Run]) -> tuple[list[Comparison], str]:
    data = path.read_bytes()
    document = parse_json(data)
    require(
        isinstance(document, dict) and set(document) == {"schema", "comparisons"},
        "comparison manifest requires only schema and comparisons",
    )
    require(document["schema"] == COMPARISON_SCHEMA, "unsupported comparison schema")
    entries = document["comparisons"]
    require(
        isinstance(entries, list) and bool(entries),
        "comparisons must be a nonempty array",
    )
    result: list[Comparison] = []
    names: set[str] = set()
    for entry in entries:
        require(
            isinstance(entry, dict) and set(entry) == {"name", "baseline", "candidate"},
            "each comparison requires only name, baseline, and candidate",
        )
        name = entry["name"]
        require(
            isinstance(name, str) and bool(name.strip()) and name not in names,
            "comparison names must be nonempty and unique",
        )
        names.add(name)
        selected = []
        for side in ("baseline", "candidate"):
            ref = entry[side]
            require(
                isinstance(ref, dict) and set(ref) == {"input", "case"},
                f"{name}.{side}: requires input and case",
            )
            alias, case_name = ref["input"], ref["case"]
            require(
                isinstance(alias, str) and alias in runs,
                f"{name}.{side}: unknown input",
            )
            run = runs[alias]
            require(
                isinstance(case_name, str) and case_name in run.cases,
                f"{name}.{side}: unknown case",
            )
            selected.append((run, run.cases[case_name]))
        (base_run, base), (candidate_run, candidate) = selected
        require(
            (base_run.path, base.name) != (candidate_run.path, candidate.name),
            f"{name}: cannot compare a case with itself",
        )
        different = [
            key
            for key in COMPARABILITY_FIELDS
            if base_run.context.get(key) != candidate_run.context.get(key)
        ]
        require(
            not different,
            f"{name}: incompatible comparison context: {', '.join(different)}",
        )
        if base_run.path != candidate_run.path:
            for key in ("monad_commit", "monad_execbench_commit"):
                require(
                    re.fullmatch(r"[0-9a-f]{40}", base_run.context[key]) is not None,
                    f"{name}: cross-file comparison requires an identified {key}",
                )
        require(
            base.status == candidate.status,
            f"{name}: cannot compare different execution statuses",
        )
        result.append(Comparison(name, base_run, base, candidate_run, candidate))
    return result, "0x" + hashlib.sha256(data).hexdigest()
