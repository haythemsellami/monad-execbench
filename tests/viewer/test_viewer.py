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
from types import SimpleNamespace
from unittest.mock import Mock, patch

from monad_execbench_attribution.report import attribute
from monad_execbench_attribution.sources import load_build_info
from monad_execbench_viewer.cli import main
from monad_execbench_viewer.export import SCHEMA, export, write_json
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

    def test_publication_moves_one_complete_directory(self):
        path = self.write("profile.json", self.diagnostic())
        rename = Path.rename

        def publish(staged, target):
            self.assertTrue(staged.is_dir())
            self.assertEqual(target, self.output)
            self.assertEqual(list(target.iterdir()), [])
            self.assertTrue((staged / "summary.json").is_file())
            self.assertTrue((staged / "p0-c0.json").is_file())
            self.assertTrue((staged / "p0-c0/frame-0.json").is_file())
            return rename(staged, target)

        with patch.object(Path, "rename", autospec=True, side_effect=publish) as move:
            self.prepare(profiles=[path])
        self.assertEqual(move.call_count, 1)
        self.assertEqual(list(self.root.glob(".viewer-*")), [])
        self.assertTrue((self.output / "p0-c0/frame-0.json").is_file())

    def test_publication_failure_cleans_reservation_and_allows_retry(self):
        path = self.write("profile.json", self.diagnostic())
        for exception in (OSError("publication failed"), KeyboardInterrupt()):
            with self.subTest(exception=type(exception).__name__):
                with (
                    patch.object(Path, "rename", side_effect=exception),
                    self.assertRaises(type(exception)),
                ):
                    self.prepare(profiles=[path])
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.root.glob(".viewer-*")), [])
        self.prepare(profiles=[path])
        self.assertTrue((self.output / "summary.json").is_file())

    def test_staging_failure_never_reserves_output(self):
        with (
            patch(
                "monad_execbench_viewer.export.write_json", side_effect=OSError("write")
            ),
            self.assertRaises(OSError),
        ):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".viewer-*")), [])

    def test_publication_preserves_destination_created_during_staging(self):
        for kind in ("empty-directory", "directory", "file", "symlink"):
            with self.subTest(kind=kind):
                output = self.root / kind
                identity = []

                def write_and_collide(
                    path, value, kind=kind, output=output, identity=identity
                ):
                    write_json(path, value)
                    if kind in ("empty-directory", "directory"):
                        output.mkdir()
                        if kind == "directory":
                            (output / "unrelated").write_text("keep")
                    elif kind == "file":
                        output.write_text("keep")
                    else:
                        output.symlink_to(self.root / "absent")
                    identity.append(output.lstat().st_ino)

                with (
                    patch(
                        "monad_execbench_viewer.export.write_json",
                        side_effect=write_and_collide,
                    ),
                    self.assertRaises(FileExistsError),
                ):
                    export([f"run={self.input}"], [], None, output)
                self.assertEqual(output.lstat().st_ino, identity[0])
                if kind == "directory":
                    self.assertEqual((output / "unrelated").read_text(), "keep")
                elif kind == "file":
                    self.assertEqual(output.read_text(), "keep")
                self.assertEqual(list(self.root.glob(".viewer-*")), [])

    def test_publication_failure_does_not_remove_another_writers_files(self):
        def fail_after_other_write(*args):
            (self.output / "unrelated").write_text("keep")
            raise OSError("publication failed")

        with (
            patch.object(Path, "rename", side_effect=fail_after_other_write),
            self.assertRaisesRegex(OSError, "publication failed"),
        ):
            self.prepare()
        self.assertEqual((self.output / "unrelated").read_text(), "keep")
        self.assertEqual(list(self.root.glob(".viewer-*")), [])

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

    def test_profile_provenance_is_projected_without_losing_build_identity(self):
        data = self.attribution()
        expected = copy.deepcopy(data["build_info"])
        data["build_info"][0]["input"] = {"sources": "not browser provenance"}
        data["build_info"][0]["output"] = {"bytecode": "not browser provenance"}
        data["unexpected"] = {"payload": "not browser provenance"}
        data["version"] = "0.1.0"
        result = self.prepare(profiles=[self.write("attribution.json", data)])
        provenance = result["profiles"][0]
        self.assertEqual(provenance["build_info"], expected)
        self.assertEqual(provenance["version"], "0.1.0")
        self.assertNotIn("unexpected", provenance)
        self.assertNotIn("not browser provenance", json.dumps(provenance))
        for field in ("runner_sha256", "runner_commit", "compiler", "build_type"):
            self.assertEqual(provenance[field], data[field])

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

    def assert_profile_cli_error(self, data):
        path = self.write("malformed-profile.json", data)
        before = path.read_bytes()
        stderr = io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            result = main(
                [
                    "export",
                    "--input",
                    f"run={self.input}",
                    "--profile",
                    str(path),
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(result, 1)
        self.assertTrue(stderr.getvalue().startswith("viewer: "))
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse(self.output.exists())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".viewer-*")), [])

    def test_malformed_profile_shapes_return_clean_cli_errors(self):
        mutations = (
            lambda d: d.update(cases=None),
            lambda d: d.update(cases={}),
            lambda d: d.update(cases=[None]),
            lambda d: d.update(cases=["bad"]),
            lambda d: d["cases"][0].update(codes=None),
            lambda d: d["cases"][0].update(frames=None),
            lambda d: d["cases"][0].update(frames=[None]),
            lambda d: d["cases"][0]["frames"][0].update(pcs=None),
            lambda d: d["cases"][0]["frames"][0].update(pcs=[None]),
            lambda d: d["cases"][0].update(coverage={"solidity": None}),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = self.attribution()
                mutate(data)
                self.assert_profile_cli_error(data)

    def test_invalid_build_provenance_returns_clean_cli_errors(self):
        invalid = (
            None,
            {},
            [None],
            [{}],
            [{"file": "build.json", "compiler": "solc", "sha256": "bad"}],
            [{"file": None, "compiler": "solc", "sha256": "a" * 64}],
            [{"file": "build.json", "compiler": {}, "sha256": "a" * 64}],
        )
        for value in invalid:
            with self.subTest(value=value):
                data = self.attribution()
                data["build_info"] = value
                self.assert_profile_cli_error(data)

    def test_default_port_headers_without_binding_privileged_port(self):
        self.prepare()
        with patch("monad_execbench_viewer.server.ThreadingHTTPServer") as factory:
            create_server(self.output, 80)
        handler = factory.call_args.args[1]
        checks = (
            (80, "127.0.0.1", None, 200),
            (80, "127.0.0.1:80", None, 200),
            (80, "127.0.0.1", "http://127.0.0.1", 200),
            (80, "127.0.0.1", "http://127.0.0.1:80", 200),
            (80, "127.0.0.1:80", "http://127.0.0.1", 200),
            (80, "127.0.0.1:80", "http://127.0.0.1:80", 200),
            (80, "127.0.0.1:81", None, 403),
            (80, "localhost", None, 403),
            (80, "attacker.example", None, 403),
            (80, "127.0.0.1", "https://127.0.0.1", 403),
            (80, "127.0.0.1", "http://127.0.0.1:81", 403),
            (80, "127.0.0.1", "https://attacker.example", 403),
            (8765, "127.0.0.1:8765", "http://127.0.0.1:8765", 200),
            (8765, "127.0.0.1", None, 403),
            (8765, "127.0.0.1:80", None, 403),
            (8765, "127.0.0.1:8765", "http://127.0.0.1", 403),
        )
        for port, host, origin, expected in checks:
            with self.subTest(port=port, host=host, origin=origin):
                request = SimpleNamespace(
                    server=SimpleNamespace(server_port=port),
                    headers={"Host": host, "Origin": origin},
                    path="/summary.json",
                    send_error=Mock(),
                    send_response=Mock(),
                    send_header=Mock(),
                    end_headers=Mock(),
                    wfile=io.BytesIO(),
                )
                handler.do_GET(request)
                if expected == 200:
                    request.send_response.assert_called_once_with(200)
                    request.send_error.assert_not_called()
                    self.assertEqual(
                        json.loads(request.wfile.getvalue())["schema"], SCHEMA
                    )
                else:
                    request.send_error.assert_called_once_with(403)
                    request.send_response.assert_not_called()

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
