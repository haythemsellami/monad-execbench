from __future__ import annotations

import copy
import hashlib
import http.client
import io
import json
import runpy
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.resources import files
from pathlib import Path

from monad_execbench_attribution.report import attribute
from monad_execbench_attribution.sources import load_build_info
from monad_execbench_viewer.cli import main
from monad_execbench_viewer.export import SCHEMA, export
from monad_execbench_viewer.profiles import IDENTITY, checked_profile
from monad_execbench_viewer.server import create_server

ROOT = Path(__file__).resolve().parents[2]
TIMING = runpy.run_path(str(ROOT / "tests/report/test_report.py"))["document"]
helpers = runpy.run_path(str(ROOT / "tests/attribution/test_attribution.py"))


class ViewerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.timing = TIMING()
        self.input = self.write("timing.json", self.timing)
        self.output = self.root / "viewer"

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def prepare(self, **kwargs):
        return export(
            [f"run={self.input}"],
            kwargs.get("profiles", []),
            kwargs.get("comparisons"),
            self.output,
        )

    def diagnostic(self):
        data = helpers["diagnostic"]()
        for left, right in IDENTITY.items():
            data[left] = self.timing["context"][right]
        data["block_number"] = int(data["block_number"])
        case = data["cases"][0]
        case["name"] = "implementation-a/size-10"
        case["gas_used"] = 100
        frame = case["frames"][0]
        frame["gas_used"] = frame["self_gas"] = 100
        frame["pcs"][0]["gas"] = 98
        return data

    def attribution(self):
        build = self.write("build.json", helpers["build_info"]())
        artifacts, builds = load_build_info([build])
        return attribute(json.dumps(self.diagnostic()).encode(), artifacts, builds)

    def test_export_reuses_statistics_and_exact_metadata(self):
        huge = 2**200
        for row in self.timing["benchmarks"]:
            row["size"] = float(huge)
            label = json.loads(row["label"])
            label["counters"]["size"] = str(huge)
            row["label"] = json.dumps(label)
        self.write("timing.json", self.timing)
        result = self.prepare()
        case = result["runs"][0]["cases"][0]
        self.assertEqual(case["cpu"]["median"], 1)
        self.assertEqual(case["wall"]["median"], 2)
        self.assertEqual(case["iterations"], 60)
        self.assertEqual(case["counters"]["size"], str(huge))
        self.assertEqual(
            json.loads((self.output / "summary.json").read_text())["schema"], SCHEMA
        )
        self.assertTrue(result["runs"][0]["warnings"])
        self.assertIsNone(case["profile"])

    def test_input_and_existing_output_are_never_replaced(self):
        before = self.input.read_bytes()
        self.prepare()
        with self.assertRaisesRegex(ValueError, "output already exists"):
            self.prepare()
        self.assertEqual(self.input.read_bytes(), before)
        with self.assertRaises(ValueError):
            export([f"run={self.input}"], [], None, self.input)

    def test_duplicate_alias_files_invalid_and_missing_repetitions(self):
        for inputs in (
            [f"run={self.input}", f"run={self.input}"],
            [f"a={self.input}", f"b={self.input}"],
            [f"../x={self.input}"],
        ):
            with self.assertRaises(ValueError):
                export(inputs, [], None, self.output)
        self.timing["benchmarks"].pop(0)
        self.write("timing.json", self.timing)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_explicit_comparison_and_cross_mode_rejection(self):
        manifest = {
            "schema": "monad-execbench/comparisons-v1",
            "comparisons": [
                {
                    "name": "two designs",
                    "baseline": {"input": "run", "case": "implementation-a/size-10"},
                    "candidate": {"input": "run", "case": "implementation-b/size-10"},
                }
            ],
        }
        path = self.write("comparisons.json", manifest)
        result = self.prepare(comparisons=path)
        self.assertEqual(result["comparisons"][0]["cpu_ratio"], 2)
        other = self.write("other.json", TIMING("interpreter-hot"))
        manifest["comparisons"][0]["candidate"]["input"] = "other"
        self.write("comparisons.json", manifest)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            export(
                [f"run={self.input}", f"other={other}"], [], path, self.root / "invalid"
            )

    def test_diagnostics_without_sources_are_supported(self):
        path = self.write("diagnostics.json", self.diagnostic())
        result = self.prepare(profiles=[path])
        self.assertEqual(result["runs"][0]["cases"][0]["profile"], "p0-c0")
        case = json.loads((self.output / "p0-c0.json").read_text())
        self.assertEqual(case["coverage"]["unmapped"]["gas"], 100)
        self.assertEqual(case["sources"], [])
        self.assertNotIn("pcs", case["frames"][0])
        detail = json.loads((self.output / case["frames"][0]["file"]).read_text())
        self.assertEqual(sum(pc["gas"] for pc in detail["pcs"]), 100)

    def test_attribution_sources_are_deduplicated_and_lazy(self):
        data = self.attribution()
        path = self.write("attribution.json", data)
        result = self.prepare(profiles=[path])
        case = json.loads((self.output / "p0-c0.json").read_text())
        self.assertEqual(case["coverage"]["solidity"]["gas"], 98)
        self.assertEqual(len(case["sources"]), 2)
        self.assertNotIn("codes", case)
        self.assertNotIn("frames", result["profiles"][0])
        self.assertEqual(
            result["profiles"][0]["input_sha256"],
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def test_profile_identity_and_result_mismatch_rejected(self):
        for mutate in (
            lambda d: d.update(bundle_sha256="0x" + "f" * 64),
            lambda d: d["cases"][0].update(status="revert"),
        ):
            data = self.diagnostic()
            mutate(data)
            path = self.write("profile.json", data)
            with self.assertRaises(ValueError):
                self.prepare(profiles=[path])
            self.assertFalse(self.output.exists())

    def test_duplicate_profile_rejected(self):
        path = self.write("profile.json", self.diagnostic())
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.prepare(profiles=[path, path])
        self.assertFalse(self.output.exists())

    def test_profile_gas_opcode_hash_and_coverage_validation(self):
        changes = [
            lambda d: d["cases"][0].update(steps=99),
            lambda d: d["cases"][0]["frames"][0]["pcs"][0].update(pc=1),
            lambda d: d["cases"][0]["frames"][0].update(self_gas=99),
            lambda d: d["cases"][0]["coverage"]["solidity"].update(gas=99),
            lambda d: d["cases"][0]["frames"][0]["pcs"][0]["source"].update(
                kind="unknown"
            ),
        ]
        for mutate in changes:
            data = self.attribution()
            mutate(data)
            with self.assertRaises(ValueError):
                checked_profile(self.write("invalid.json", data))

    def test_empty_frame_root_precompile_accounting(self):
        data = self.diagnostic()
        data["cases"][0].update(frames=[], codes={}, outside_vm_gas=100, steps=0)
        self.prepare(profiles=[self.write("empty.json", data)])
        result = json.loads((self.output / "p0-c0.json").read_text())
        self.assertEqual(result["outside_vm_gas"], 100)
        self.assertEqual(result["frames"], [])

    def test_multiple_roots_rejected(self):
        data = self.diagnostic()
        second = copy.deepcopy(data["cases"][0]["frames"][0])
        second["id"] = 1
        data["cases"][0]["frames"].append(second)
        with self.assertRaisesRegex(ValueError, "multiple root"):
            checked_profile(self.write("roots.json", data))

    def test_cli_errors_do_not_publish_output(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["export", "--input", "not-a-file", "--output", str(self.output)]),
                1,
            )
        self.assertFalse(self.output.exists())

    def test_static_resources_are_packaged_without_remote_dependencies(self):
        assets = files("monad_execbench_viewer").joinpath("static")
        html = assets.joinpath("index.html").read_text()
        script = assets.joinpath("app.js").read_text()
        self.assertIn('lang="en"', html)
        self.assertIn('src="/app.js"', html)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("https://", script)
        self.assertTrue(assets.joinpath("style.css").read_text())

    def test_server_is_loopback_read_only_and_confines_files(self):
        self.prepare()
        outside = self.write("private.json", {"private": True})
        (self.output / "p0-c0.json").symlink_to(outside)
        with create_server(self.output) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")

                def request(path, headers=None, method="GET"):
                    client = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=5
                    )
                    client.request(method, path, headers=headers or {})
                    response = client.getresponse()
                    payload = response.read()
                    result = response.status, dict(response.headers), payload
                    client.close()
                    return result

                for path in ("/", "/app.js", "/style.css", "/summary.json"):
                    status, headers, _ = request(path)
                    self.assertEqual(status, 200)
                    self.assertIn(
                        "frame-ancestors 'none'", headers["Content-Security-Policy"]
                    )
                    self.assertNotIn("Access-Control-Allow-Origin", headers)
                for path in (
                    "/../private.json",
                    "/%2e%2e/private.json",
                    "/p0-c0.json",
                    "/unknown",
                ):
                    self.assertEqual(request(path)[0], 404)
                self.assertEqual(
                    request("/summary.json", {"Host": "attacker.example"})[0], 403
                )
                self.assertEqual(
                    request("/summary.json", {"Origin": "https://attacker.example"})[0],
                    403,
                )
                self.assertEqual(request("/summary.json", method="POST")[0], 501)
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
