from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from monad_execbench_report.cli import main
from monad_execbench_report.markdown import render_report, text
from monad_execbench_report.results import (
    COMPARABILITY_FIELDS,
    COMPARISON_SCHEMA,
    HASH_FIELDS,
    ReportError,
    load_comparisons,
    load_run,
    parse_json,
)


def document(mode: str = "dual-hot", count: int = 3) -> dict:
    context = {
        "json_schema_version": 1,
        "monad_execbench_version": "0.1.0",
        "monad_execbench_commit": "a" * 40,
        "monad_commit": "b" * 40,
        "compiler": "GNU 15.2.0",
        "build_type": "RelWithDebInfo",
        "fixture_schema": "monad-execbench/v1",
        "fixture_created_at": "2026-01-01T00:00:00Z",
        "capture_tool": "monad-execbench-capture 0.1.0",
        "execution_env": "MONAD_TEN",
        "benchmark_mode": mode,
        "case_filter": "*",
        "host_name": "benchmark-host",
        "num_cpus": 8,
        "mhz_per_cpu": 3200,
        "cpu_scaling_enabled": False,
        "caches": [{"type": "Data", "level": 1, "size": 32768, "num_sharing": 1}],
        "library_version": "v1.9.1",
        "library_build_type": "release",
        "block_number": "123456",
        "requested_repetitions": str(count),
    }
    context.update({key: "0x" + "c" * 64 for key in HASH_FIELDS})
    rows = []
    for implementation, multiplier in (("a", 1), ("b", 2)):
        name = f"execute/{mode}/implementation-{implementation}/size-10/repeats:{count}"
        for index in range(count):
            rows.append(
                {
                    "name": name,
                    "run_name": name,
                    "run_type": "iteration",
                    "repetitions": count,
                    "repetition_index": index,
                    "threads": 1,
                    "iterations": 10 * (index + 1),
                    "time_unit": "ns",
                    "real_time": (index + 1) * 1000 * multiplier,
                    "cpu_time": (index + 1) * 500 * multiplier,
                    "execution_gas": 100 * multiplier,
                    "log_count": 1,
                    "return_data_bytes": 32,
                    "size": 10.0,
                    "label": json.dumps(
                        {
                            "status": "success",
                            "labels": {"implementation": implementation},
                            "counters": {"size": "10"},
                        }
                    ),
                }
            )
        rows.append(
            {
                **rows[-1],
                "name": name + "_cv",
                "run_type": "aggregate",
                "aggregate_name": "cv",
                "aggregate_unit": "percentage",
                "real_time": 999999,
                "cpu_time": 999999,
                "execution_gas": 0.01,
            }
        )
    return {"context": context, "benchmarks": rows}


def comparison(candidate_input: str = "dual") -> dict:
    return {
        "schema": COMPARISON_SCHEMA,
        "comparisons": [
            {
                "name": "size 10",
                "baseline": {"input": "dual", "case": "implementation-a/size-10"},
                "candidate": {
                    "input": candidate_input,
                    "case": "implementation-b/size-10",
                },
            }
        ],
    }


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "dual.json"
        self.pairs = self.root / "pairs.json"
        self.output = self.root / "report.md"
        self.write(self.path, document())
        self.write(self.pairs, comparison())

    @staticmethod
    def write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def load(self, value: dict):
        self.write(self.path, value)
        return load_run("dual", self.path)

    def cli(self, *extra: str) -> tuple[int, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                ["--input", f"dual={self.path}", "--output", str(self.output), *extra]
            )
        return status, stdout.getvalue() + stderr.getvalue()

    def test_statistics_use_only_raw_repetition_averages(self):
        run = load_run("dual", self.path)
        case = run.cases["implementation-a/size-10"]
        self.assertEqual(case.wall.median, 2)
        self.assertEqual(case.wall.mean, 2)
        self.assertEqual(case.wall.minimum, 1)
        self.assertEqual(case.wall.maximum, 3)
        self.assertEqual(case.wall.stddev, 1)
        self.assertEqual(case.wall.cv, 0.5)
        self.assertEqual(case.cpu.median, 1)
        self.assertEqual(case.iterations, 60)
        self.assertEqual(case.repetitions, 3)
        self.assertEqual(case.gas, 100)
        self.assertEqual(
            run.sha256, "0x" + hashlib.sha256(self.path.read_bytes()).hexdigest()
        )

    def test_time_units_are_normalized(self):
        for unit, scale in (
            ("ns", 1),
            ("us", 1000),
            ("ms", 1_000_000),
            ("s", 1_000_000_000),
        ):
            with self.subTest(unit=unit):
                value = document()
                for row in value["benchmarks"]:
                    row["time_unit"] = unit
                    row["real_time"] /= scale
                    row["cpu_time"] /= scale
                self.assertEqual(
                    self.load(value).cases["implementation-a/size-10"].wall.median, 2
                )

    def test_metadata_uses_exact_large_counter(self):
        value = document()
        exact = str(2**200 + 1)
        for row in value["benchmarks"]:
            label = json.loads(row["label"])
            label["counters"]["size"] = exact
            row["label"] = json.dumps(label)
            row["size"] = float(exact)
        run = self.load(value)
        self.assertEqual(run.cases["implementation-a/size-10"].counters["size"], exact)
        self.assertIn(exact, render_report({"dual": run}, []))

    def test_report_and_explicit_ratios(self):
        status, output = self.cli("--comparisons", str(self.pairs))
        self.assertEqual(status, 0, output)
        report = self.output.read_text()
        self.assertIn("2x | 2x | +100", report)
        self.assertIn("CPU µs / million gas", report)
        self.assertIn("raw repetition", report)
        self.assertIn("not node throughput", report)
        self.assertIn("SHA-256", report)
        self.assertIn("timing CV exceeds 5%", report)
        self.assertIn("only 3 repetitions", report)

    def test_no_inferred_comparisons_and_deterministic_output(self):
        status, output = self.cli()
        self.assertEqual(status, 0, output)
        first = self.output.read_bytes()
        self.assertIn(b"No implementation pairings or ratios were inferred", first)
        self.assertEqual(self.cli("--force")[0], 0)
        self.assertEqual(first, self.output.read_bytes())

    def test_single_sample_and_zero_denominators_are_unavailable(self):
        value = document(count=1)
        for row in value["benchmarks"]:
            row["real_time"] = row["cpu_time"] = row["execution_gas"] = 0
        run = self.load(value)
        case = run.cases["implementation-a/size-10"]
        self.assertIsNone(case.wall.stddev)
        self.assertIsNone(case.wall.cv)
        pairs, digest = load_comparisons(self.pairs, {"dual": run})
        report = render_report({"dual": run}, pairs, comparison_sha256=digest)
        self.assertIn("size 10 | n/a | n/a | n/a | n/a | n/a", report)
        self.assertNotRegex(report, r"\b(?:nan|inf)\b")

    def test_scaled_debug_and_missing_scaling_warnings(self):
        value = document()
        value["context"].update(
            cpu_scaling_enabled=True, build_type="Debug", library_build_type="debug"
        )
        warnings = " ".join(self.load(value).warnings)
        self.assertIn("CPU scaling is enabled", warnings)
        self.assertIn("not a recognized optimized build", warnings)
        self.assertIn("not built in release mode", warnings)
        del value["context"]["cpu_scaling_enabled"]
        self.assertIn(
            "CPU-scaling state was not recorded", " ".join(self.load(value).warnings)
        )

    def test_successful_root_revert_is_not_a_benchmark_error(self):
        value = document()
        for row in value["benchmarks"]:
            label = json.loads(row["label"])
            label["status"] = "revert"
            row["label"] = json.dumps(label)
        self.assertEqual(
            self.load(value).cases["implementation-a/size-10"].status, "revert"
        )

    def test_rejects_failed_raw_or_aggregate_rows(self):
        for index in (0, 3):
            value = document()
            value["benchmarks"][index].update(
                error_occurred=True, error_message="verification failed"
            )
            with self.assertRaisesRegex(ReportError, "benchmark failure"):
                self.load(value)

    def test_rejects_aggregate_only_and_partial_samples(self):
        value = document()
        value["benchmarks"] = [
            row for row in value["benchmarks"] if row["run_type"] == "aggregate"
        ]
        with self.assertRaisesRegex(ReportError, "aggregate-only"):
            self.load(value)
        value = document()
        del value["benchmarks"][0]
        with self.assertRaisesRegex(ReportError, "expected 3 raw repetitions"):
            self.load(value)

    def test_invalid_sample_fields(self):
        mutations = [
            ("real_time", float("nan")),
            ("real_time", float("inf")),
            ("real_time", -1),
            ("real_time", True),
            ("cpu_time", None),
            ("iterations", 0),
            ("iterations", 1.5),
            ("threads", 2),
            ("execution_gas", 2**53),
            ("execution_gas", 0.5),
            ("time_unit", "minutes"),
            ("repetitions", 4),
            ("repetition_index", 1),
            ("repetition_index", 3),
            ("label", "null"),
            ("label", "{}"),
            ("size", 11),
            ("run_type", "custom"),
            ("run_name", "malformed"),
        ]
        for key, invalid in mutations:
            with self.subTest(key=key, invalid=invalid):
                value = document()
                value["benchmarks"][0][key] = invalid
                with self.assertRaises(ReportError):
                    self.load(value)

    def test_rejects_inconsistent_metadata_and_counters(self):
        for key, invalid in (
            ("execution_gas", 99),
            ("log_count", 9),
            ("return_data_bytes", 0),
        ):
            value = document()
            value["benchmarks"][1][key] = invalid
            with self.assertRaisesRegex(ReportError, "execution counters changed"):
                self.load(value)
        value = document()
        label = json.loads(value["benchmarks"][1]["label"])
        label["labels"]["implementation"] = "different"
        value["benchmarks"][1]["label"] = json.dumps(label)
        with self.assertRaisesRegex(ReportError, "metadata changed"):
            self.load(value)

    def test_invalid_context_and_duplicate_json_keys(self):
        for key, invalid in (
            ("runner_sha256", None),
            ("benchmark_mode", "dual-cold"),
            ("requested_repetitions", "0"),
            ("json_schema_version", 2),
            ("num_cpus", True),
            ("cpu_scaling_enabled", "false"),
        ):
            with self.subTest(key=key):
                value = document()
                value["context"][key] = invalid
                with self.assertRaises(ReportError):
                    self.load(value)
        with self.assertRaisesRegex(ReportError, "duplicate JSON key"):
            parse_json('{"benchmarks": [], "benchmarks": []}')

    def test_same_context_cross_file_comparison(self):
        other = self.root / "other.json"
        self.write(other, document())
        self.write(self.pairs, comparison("other"))
        runs = {"dual": load_run("dual", self.path), "other": load_run("other", other)}
        self.assertEqual(len(load_comparisons(self.pairs, runs)[0]), 1)

    def test_comparison_rejects_every_context_mismatch(self):
        original = load_run("dual", self.path)
        other_path = self.root / "other.json"
        self.write(other_path, document())
        self.write(self.pairs, comparison("other"))
        for field in COMPARABILITY_FIELDS:
            with self.subTest(field=field):
                other = load_run("other", other_path)
                other.context[field] = "different"
                with self.assertRaisesRegex(
                    ReportError, "incompatible comparison context"
                ):
                    load_comparisons(self.pairs, {"dual": original, "other": other})

    def test_multiple_modes_are_separate_and_cross_mode_ratio_rejected(self):
        other = self.root / "interpreter.json"
        self.write(other, document("interpreter-hot"))
        status, output = self.cli("--input", f"interpreter={other}")
        self.assertEqual(status, 0, output)
        self.assertIn("Input: interpreter", self.output.read_text())
        self.write(self.pairs, comparison("interpreter"))
        status, output = self.cli(
            "--input",
            f"interpreter={other}",
            "--comparisons",
            str(self.pairs),
            "--force",
        )
        self.assertEqual(status, 1)
        self.assertIn("incompatible comparison context", output)

    def test_unknown_revisions_prevent_cross_file_ratios(self):
        value = document()
        value["context"]["monad_commit"] = "unknown"
        base = self.load(value)
        other = self.root / "other.json"
        self.write(other, value)
        self.write(self.pairs, comparison("other"))
        with self.assertRaisesRegex(ReportError, "identified monad_commit"):
            load_comparisons(
                self.pairs, {"dual": base, "other": load_run("other", other)}
            )

    def test_manifest_errors(self):
        run = load_run("dual", self.path)
        invalid = []
        value = comparison()
        value["comparisons"][0]["candidate"]["case"] = "unknown"
        invalid.append(value)
        value = comparison()
        value["comparisons"][0]["candidate"] = copy.deepcopy(
            value["comparisons"][0]["baseline"]
        )
        invalid.append(value)
        value = comparison()
        value["comparisons"][0]["typo"] = True
        invalid.append(value)
        value = comparison()
        value["comparisons"].append(value["comparisons"][0])
        invalid.append(value)
        for value in invalid:
            self.write(self.pairs, value)
            with self.assertRaises(ReportError):
                load_comparisons(self.pairs, {"dual": run})

    def test_comparison_rejects_status_mismatch(self):
        value = document()
        for row in value["benchmarks"]:
            if "implementation-b" in row["run_name"]:
                label = json.loads(row["label"])
                label["status"] = "revert"
                row["label"] = json.dumps(label)
        with self.assertRaisesRegex(ReportError, "different execution statuses"):
            load_comparisons(self.pairs, {"dual": self.load(value)})

    def test_markdown_escapes_untrusted_text(self):
        self.assertEqual(text("a|b\n<script>*x*`"), "a\\|b<br>&lt;script&gt;\\*x\\*\\`")
        status, output = self.cli(
            "--title", "[click](https://example.test)\n# injected"
        )
        self.assertEqual(status, 0, output)
        self.assertTrue(self.output.read_text().startswith("# \\[click\\]\\("))
        self.assertNotIn("\n# injected", self.output.read_text())

    def test_existing_output_and_inputs_are_preserved(self):
        self.output.write_text("previous report")
        self.assertEqual(self.cli()[0], 1)
        self.assertEqual(self.output.read_text(), "previous report")
        original = self.path.read_bytes()
        status, output = self.cli("--output", str(self.path), "--force")
        self.assertEqual(status, 1)
        self.assertIn("must not overwrite an input", output)
        self.assertEqual(original, self.path.read_bytes())
        self.output.unlink()
        self.output.hardlink_to(self.path)
        self.assertEqual(self.cli("--force")[0], 1)
        self.assertEqual(original, self.path.read_bytes())

    def test_failed_validation_never_replaces_report(self):
        self.output.write_text("previous report")
        value = document()
        value["benchmarks"][0]["error_occurred"] = True
        self.write(self.path, value)
        self.assertEqual(self.cli("--force")[0], 1)
        self.assertEqual(self.output.read_text(), "previous report")

    def test_failed_publish_cleans_temporary_file(self):
        self.output.write_text("previous report")
        before = set(self.root.iterdir())
        with patch(
            "monad_execbench_report.cli.os.replace", side_effect=OSError("disk error")
        ):
            self.assertEqual(self.cli("--force")[0], 1)
        self.assertEqual(self.output.read_text(), "previous report")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_duplicate_inputs_missing_files_and_bad_names(self):
        for extra in (
            ("--input", f"dual={self.path}"),
            ("--input", f"alias={self.path}"),
            ("--input", f"bad name={self.path}"),
            ("--input", "missing=/does/not/exist"),
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.cli(*extra)[0], 1)

    def test_nonfinite_numeric_exponents_are_rejected(self):
        with self.assertRaisesRegex(ReportError, "non-finite JSON number"):
            parse_json('{"context": {"mhz_per_cpu": 1e400}}')
        value = document()
        value["benchmarks"][0]["real_time"] = 1e300
        value["benchmarks"][0]["time_unit"] = "s"
        # A large finite input can be represented, while unit conversion must
        # fail cleanly once it overflows instead of printing Infinity.
        self.assertTrue(
            math.isfinite(self.load(value).cases["implementation-a/size-10"].wall.mean)
        )
        value["benchmarks"][0]["real_time"] = 1e308
        with self.assertRaisesRegex(ReportError, "overflows"):
            self.load(value)


if __name__ == "__main__":
    unittest.main()
