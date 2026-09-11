"""Frontend checks that need no browser: packaged assets, untrusted-text
sinks, offline operation, the exact-value formatting rules and export
accounting identities against a real export."""

from __future__ import annotations

import copy
import http.client
import json
import re
import runpy
import shutil
import subprocess
import tempfile
import threading
import unittest
from importlib.resources import files
from pathlib import Path

from monad_execbench_viewer.export import export
from monad_execbench_viewer.profiles import IDENTITY
from monad_execbench_viewer.server import ASSET_SUFFIXES, create_server

ROOT = Path(__file__).resolve().parents[2]
TIMING = runpy.run_path(str(ROOT / "tests/report/test_report.py"))["document"]
helpers = runpy.run_path(str(ROOT / "tests/attribution/test_attribution.py"))
STATIC = files("monad_execbench_viewer").joinpath("static")
MODULES = ("app.js", "dom.js", "format.js", "state.js") + tuple(
    f"views/{name}.js"
    for name in ("overview", "scaling", "comparisons", "explorer", "provenance")
)
FONTS = (
    "barlow-400.woff2",
    "barlow-500.woff2",
    "barlow-600.woff2",
    "barlow-condensed-500.woff2",
    "barlow-condensed-600.woff2",
)
FORBIDDEN_SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    'setAttribute("style"',
    "srcdoc",
    "javascript:",
)
NODE = shutil.which("node")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SCRIPT_NAME = "<script>alert(1)</script>"
LONG_NAME = "very-long/" + "segment-" * 60 + "end"


def timing_with_names(names):
    document = TIMING("dual-hot", 3)
    rows = []
    for row in document["benchmarks"]:
        if "implementation-a" not in row["run_name"]:
            continue
        for name in names:
            copy_row = copy.deepcopy(row)
            copy_row["name"] = copy_row["run_name"] = (
                f"execute/dual-hot/{name}/repeats:3"
            )
            rows.append(copy_row)
    document["benchmarks"] = rows
    return document


def multi_frame_diagnostic(context):
    """A profile with nested frames, a reverting child and outside-VM gas."""
    data = helpers["diagnostic"]()
    for left, right in IDENTITY.items():
        data[left] = context[right]
    data["block_number"] = int(data["block_number"])
    case = data["cases"][0]
    template = case["frames"][0]

    def frame(identifier, parent, depth, gas_used, self_gas, status, gas):
        result = copy.deepcopy(template)
        result.update(
            id=identifier,
            parent=parent,
            depth=depth,
            gas_supplied=gas_used + 10,
            gas_used=gas_used,
            self_gas=self_gas,
            status=status,
            pcs=[
                {"pc": 0, "opcode": 96, "gas": gas[0], "count": 2},
                {"pc": 2, "opcode": 80, "gas": gas[1], "count": 2},
                {"pc": 3, "opcode": 0, "gas": gas[2], "count": 1},
            ],
        )
        return result

    frames = [
        frame(0, None, 0, 90, 30, "success", (20, 8, 2)),
        frame(1, 0, 1, 40, 25, "success", (20, 3, 2)),
        frame(2, 1, 2, 15, 15, "revert", (10, 4, 1)),
        frame(3, 0, 1, 20, 20, "success", (18, 1, 1)),
    ]
    case.update(
        name="implementation-a/size-10",
        gas_used=100,
        outside_vm_gas=10,
        frames=frames,
        steps=sum(pc["count"] for item in frames for pc in item["pcs"]),
    )
    return data


class FrontendAssetsTest(unittest.TestCase):
    def test_modules_fonts_and_stylesheet_are_packaged_offline(self):
        html = STATIC.joinpath("index.html").read_text()
        css = STATIC.joinpath("style.css").read_text()
        self.assertIn('src="/app.js"', html)
        self.assertIn('href="/style.css"', html)
        self.assertNotIn("@import", css)
        self.assertNotRegex(css, r"url\(\s*['\"]?(?:https?:|//)")
        for font in FONTS:
            self.assertIn(f"fonts/{font}", css)
            self.assertEqual(STATIC.joinpath("fonts", font).read_bytes()[:4], b"wOF2")
        self.assertIn(
            "SIL Open Font License", STATIC.joinpath("fonts/OFL.txt").read_text()
        )
        for name in MODULES:
            script = STATIC.joinpath(name).read_text().replace(SVG_NAMESPACE, "")
            self.assertFalse(re.search(r"https?://", script), f"{name} has a URL")
            self.assertNotIn("import(", script)
            for sink in FORBIDDEN_SINKS:
                self.assertNotIn(sink, script, f"{name} uses {sink}")
        self.assertNotIn("<script>", html.replace('<script type="module"', ""))
        self.assertNotRegex(html, r"\son[a-z]+=")

    def test_stylesheet_uses_tokens_and_square_geometry(self):
        css = STATIC.joinpath("style.css").read_text()
        root = css[css.index(":root {") : css.index("}", css.index(":root {"))]
        body = css.replace(root, "")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", body), [])
        self.assertEqual(set(re.findall(r"border-radius:\s*([^;]+);", css)), {"0"})
        self.assertNotIn("gradient(", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("tabular-nums", css)

    def test_forbidden_claims_are_absent_from_copy(self):
        text = "\n".join(STATIC.joinpath(name).read_text() for name in MODULES)
        for phrase in (
            "faster",
            "slower",
            "mainnet",
            "testnet",
            "cold cache",
            "verified ✓",
        ):
            self.assertNotIn(phrase, text.lower(), phrase)
        self.assertIn("no edge carries a CALL or DELEGATECALL label", text)
        self.assertIn("no scaling law is fitted or implied", text)
        self.assertIn("never reads the browser's hardware", text)

    @unittest.skipUnless(NODE, "node is optional; it is never needed to serve")
    def test_modules_parse_and_formatting_rules_hold_in_node(self):
        for name in MODULES:
            with self.subTest(module=name):
                subprocess.run(
                    [NODE, "--check", str(STATIC.joinpath(name))], check=True
                )
        script = """
import { formatInt, formatUs, formatPct, compareBig, formatDecimal, share } from FORMAT_MODULE;
const assert = (condition, message) => { if (!condition) throw new Error(message); };
assert(formatInt("18446744073709551617") === "18,446,744,073,709,551,617", "exact huge counter");
assert(formatInt(9007199254740993n) === "9,007,199,254,740,993", "bigint kept exact");
assert(compareBig("18446744073709551617", "18446744073709551616") === 1, "bigint order");
assert(compareBig("9007199254740993", 9007199254740991) === 1, "string beyond 2^53 compares exactly");
assert(compareBig("9007199254740992", "9007199254740993") === -1, "adjacent huge strings stay distinct");
assert(formatUs(0.0031) === "0.0031 µs", "tiny nonzero never rounds to zero: " + formatUs(0.0031));
assert(formatUs(1.234) === "1.23 µs", "2dp under 10");
assert(formatUs(42.26) === "42.3 µs", "1dp under 100");
assert(formatUs(12345.6) === "12,346 µs", "grouped integer");
assert(formatUs(null) === null, "null is unavailable, not zero");
assert(formatPct(0.014) === "1.40%", "cv as percent 2dp");
assert(formatPct(0.000004) === "0.00040%", "tiny cv not zero");
assert(formatDecimal(0, 2) === "0.00", "true zero stays zero");
assert(share("21000", "21000") === 100, "share percent");
console.log("formatting rules verified");
""".replace("FORMAT_MODULE", json.dumps(str(STATIC.joinpath("format.js"))))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "check.mjs"
            path.write_text(script)
            result = subprocess.run(
                [NODE, str(path)], check=True, capture_output=True, text=True
            )
        self.assertIn("formatting rules verified", result.stdout)


class ExportedDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "viewer"

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def test_untrusted_names_round_trip_as_text(self):
        document = timing_with_names([SCRIPT_NAME, LONG_NAME])
        for row in document["benchmarks"]:
            label = json.loads(row["label"])
            label["labels"]["implementation"] = '<img src=x onerror="alert(2)">'
            label["counters"]["size"] = "18446744073709551617"
            row["size"] = float(18446744073709551617)
            row["label"] = json.dumps(label)
        result = export(
            [f"run={self.write('t.json', document)}"], [], None, self.output
        )
        names = [case["name"] for case in result["runs"][0]["cases"]]
        self.assertEqual(sorted(names), sorted([SCRIPT_NAME, LONG_NAME]))
        summary = (self.output / "summary.json").read_text()
        self.assertIn(json.dumps(SCRIPT_NAME), summary)
        case = result["runs"][0]["cases"][0]
        self.assertEqual(case["counters"]["size"], "18446744073709551617")
        self.assertIsInstance(case["counters"]["size"], str)

    def test_accounting_identities_hold_in_real_export(self):
        timing = TIMING()
        profile = self.write("profile.json", multi_frame_diagnostic(timing["context"]))
        export([f"run={self.write('t.json', timing)}"], [profile], None, self.output)
        case = json.loads((self.output / "p0-c0.json").read_text())
        frames = {frame["id"]: frame for frame in case["frames"]}
        children = {}
        for frame in case["frames"]:
            if frame["parent"] is not None:
                children.setdefault(frame["parent"], []).append(frame)
        for frame in case["frames"]:
            detail = json.loads((self.output / frame["file"]).read_text())
            self.assertEqual(
                sum(pc["gas"] for pc in detail["pcs"]),
                frame["self_gas"],
                "per-PC gas = frame self gas",
            )
            self.assertEqual(
                frame["self_gas"]
                + sum(child["gas_used"] for child in children.get(frame["id"], [])),
                frame["gas_used"],
                "self gas + direct children inclusive gas = inclusive gas",
            )
        self.assertEqual(
            sum(frame["self_gas"] for frame in frames.values())
            + case["outside_vm_gas"],
            case["gas"],
            "Σ self gas + outside-VM gas = whole-call gas",
        )
        coverage = case["coverage"]
        self.assertEqual(
            sum(bucket["gas"] for bucket in coverage.values()) + case["outside_vm_gas"],
            case["gas"],
            "coverage buckets + outside-VM remainder = whole-call gas",
        )
        self.assertEqual(
            sum(bucket["steps"] for bucket in coverage.values()), case["steps"]
        )
        self.assertEqual(
            sum(entry["gas"] for entry in case["opcodes"]),
            sum(frame["self_gas"] for frame in frames.values()),
        )
        self.assertEqual(frames[2]["status"], "revert")
        self.assertEqual(frames[2]["depth"], frames[1]["depth"] + 1)

    def test_representative_large_dataset_exports_and_serves(self):
        document = timing_with_names(
            [f"suite/case-{index:04d}" for index in range(300)]
        )
        timing = self.write("large.json", document)
        data = multi_frame_diagnostic(document["context"])
        case = data["cases"][0]
        case["name"] = "suite/case-0000"
        template = case["frames"][0]
        frames = []
        for index in range(1500):
            frame = copy.deepcopy(template)
            # Only the root carries gas so the whole-call gas still matches the
            # timing case; every other frame is a zero-gas visit.
            self_gas = 90 if index == 0 else 0
            frame.update(
                id=index,
                parent=None if index == 0 else (index - 1) // 2,
                depth=0 if index == 0 else frames[(index - 1) // 2]["depth"] + 1,
                pcs=[
                    {"pc": 0, "opcode": 96, "gas": self_gas, "count": 3},
                    {"pc": 2, "opcode": 80, "gas": 0, "count": 1},
                    {"pc": 3, "opcode": 0, "gas": 0, "count": 1},
                ],
                self_gas=self_gas,
                gas_used=0,
                gas_supplied=100000,
            )
            frames.append(frame)
        for frame in reversed(frames):
            frame["gas_used"] = frame["self_gas"] + sum(
                child["gas_used"] for child in frames if child["parent"] == frame["id"]
            )
        case.update(
            frames=frames,
            outside_vm_gas=100 - frames[0]["gas_used"],
            steps=sum(pc["count"] for frame in frames for pc in frame["pcs"]),
        )
        profile = self.write("large-profile.json", data)
        export([f"run={timing}"], [profile], None, self.output)
        self.assertEqual(len(list(self.output.glob("p0-c0/frame-*.json"))), 1500)
        with create_server(self.output) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=10
                )
                client.request("GET", "/summary.json")
                summary = json.loads(client.getresponse().read())
                self.assertEqual(len(summary["runs"][0]["cases"]), 300)
                client.request("GET", "/p0-c0/frame-1499.json")
                self.assertEqual(client.getresponse().status, 200)
                client.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)


class AssetRoutesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        timing = root / "t.json"
        timing.write_text(json.dumps(TIMING()))
        self.output = root / "viewer"
        export([f"run={timing}"], [], None, self.output)
        self.server = create_server(self.output)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)

    def request(self, path):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        client.request("GET", path)
        response = client.getresponse()
        payload = response.read()
        headers = dict(response.headers)
        client.close()
        return response.status, headers, payload

    def test_every_referenced_asset_resolves_from_the_package(self):
        html = self.request("/")[2].decode()
        css = self.request("/style.css")[2].decode()
        referenced = set(re.findall(r'(?:src|href)="(/[^"]+)"', html))
        referenced |= {
            "/" + match for match in re.findall(r"url\(\"([^\")]+)\"\)", css)
        }
        for name in MODULES:
            script = self.request(f"/{name}")[2].decode()
            self.assertIn("charset=utf-8", self.request(f"/{name}")[1]["Content-Type"])
            for imported in re.findall(r'from "\.{1,2}/([^"]+)"', script):
                referenced.add(
                    "/" + imported
                    if not name.startswith("views/")
                    else "/" + imported.replace("../", "")
                )
        for path in sorted(referenced):
            with self.subTest(path=path):
                status, headers, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(
                    "frame-ancestors 'none'", headers["Content-Security-Policy"]
                )
                self.assertIn("font-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(
            self.request("/fonts/barlow-400.woff2")[1]["Content-Type"], "font/woff2"
        )

    def test_only_allowlisted_package_files_are_served(self):
        for path in (
            "/fonts/OFL.txt",
            "/fonts/../app.js",
            "/views/../style.css",
            "/views/",
            "/fonts",
            "/static/app.js",
            "/__init__.py",
            "/server.py",
            "/../server.py",
            "/views/%2e%2e/app.js",
            "/app.js/",
            "/APP.JS",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(set(ASSET_SUFFIXES), {".js", ".css", ".woff2", ".html"})


if __name__ == "__main__":
    unittest.main()
