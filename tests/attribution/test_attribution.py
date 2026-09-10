from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from Crypto.Hash import keccak
from monad_execbench_attribution.cli import main, write_new
from monad_execbench_attribution.report import attribute, markdown
from monad_execbench_attribution.sources import (
    Artifact,
    instructions,
    load_build_info,
    match_artifact,
    runtime_template,
    source_map,
)


def build_info(code="602a5000", mapping="0:6:0;-1:-1:-1;7:3:0"):
    return {
        "solcVersion": "0.8.26",
        "input": {"sources": {"Example.sol": {"content": "// café\nabc"}}},
        "output": {
            "sources": {
                "Example.sol": {
                    "id": 0,
                    "ast": {
                        "nodeType": "FunctionDefinition",
                        "name": "run",
                        "src": "0:12:0",
                    },
                }
            },
            "contracts": {
                "Example.sol": {
                    "Example": {
                        "evm": {
                            "deployedBytecode": {
                                "object": code,
                                "sourceMap": mapping,
                            }
                        }
                    }
                }
            },
        },
    }


def diagnostic(code="602a5000"):
    code_hash = "0x" + keccak.new(digest_bits=256, data=bytes.fromhex(code)).hexdigest()
    return {
        "schema": "monad-execbench/diagnostics-v1",
        "mode": "diagnostic-interpreter",
        "execution_env": "MONAD_TEN",
        "block_number": 1,
        "block_hash": "0x" + "a" * 64,
        "bundle_sha256": "0x" + "b" * 64,
        "monad_commit": "c" * 40,
        "runner_commit": "d" * 40,
        "runner_sha256": "0x" + "e" * 64,
        "cases": [
            {
                "name": "example",
                "status": "success",
                "gas_used": 5,
                "steps": 3,
                "outside_vm_gas": 0,
                "codes": {code_hash: "0x" + code},
                "frames": [
                    {
                        "id": 0,
                        "parent": None,
                        "depth": 0,
                        "code_hash": code_hash,
                        "code_kind": "runtime",
                        "recipient": "0x" + "1" * 40,
                        "sender": "0x" + "2" * 40,
                        "selector": "0x",
                        "gas_supplied": 100,
                        "gas_used": 5,
                        "self_gas": 5,
                        "status": "success",
                        "pcs": [
                            {"pc": 0, "opcode": 96, "gas": 3, "count": 1},
                            {"pc": 2, "opcode": 80, "gas": 2, "count": 1},
                            {"pc": 3, "opcode": 0, "gas": 0, "count": 1},
                        ],
                    }
                ],
            }
        ],
    }


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def load(self, build=None):
        path = self.root / "build.json"
        path.write_text(json.dumps(build if build is not None else build_info()))
        return load_build_info([path])

    def test_pc_boundaries_skip_push_data_and_allow_truncation(self):
        self.assertEqual(
            instructions(bytes.fromhex("606061ffff00")), {0: 96, 2: 97, 5: 0}
        )
        self.assertEqual(instructions(bytes.fromhex("7fff")), {0: 127})

    def test_source_map_inheritance(self):
        self.assertEqual(
            source_map("1:2:3:i:1;;:4::o;9:::-:0"),
            [
                (1, 2, 3, "i", 1),
                (1, 2, 3, "i", 1),
                (1, 4, 3, "o", 1),
                (9, 4, 3, "-", 0),
            ],
        )
        self.assertEqual(source_map(""), [])
        for invalid in ("0:1:2:x", "-2:1:2", "0:1:2:-:-1", "1:2:3:i:0:6"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                source_map(invalid)

    def test_utf8_offsets_and_function_span(self):
        artifacts, _ = self.load(build_info(mapping="9:3:0"))
        source, reason = artifacts[0].location(0)
        self.assertEqual(reason, "mapped")
        self.assertEqual(
            (source["line"], source["column_bytes"], source["snippet"]), (2, 1, "abc")
        )
        self.assertEqual(source["function"]["name"], "run")
        self.assertEqual(artifacts[0].location(2), (None, "no-source-map-entry"))

    def test_generated_source_is_not_solidity(self):
        build = build_info(mapping="0:3:1")
        build["output"]["contracts"]["Example.sol"]["Example"]["evm"][
            "deployedBytecode"
        ]["generatedSources"] = [{"id": 1, "name": "#utility.yul", "contents": "abc"}]
        artifacts, _ = self.load(build)
        self.assertEqual(artifacts[0].location(0)[0]["kind"], "generated")

    def test_creation_code_never_matches_runtime_sources(self):
        artifacts, builds = self.load()
        value = diagnostic()
        value["cases"][0]["frames"][0]["code_kind"] = "creation"
        report = attribute(json.dumps(value).encode(), artifacts, builds)
        frame = report["cases"][0]["frames"][0]
        self.assertEqual(frame["artifact_match"]["status"], "creation-code")
        self.assertTrue(all(entry["source"] is None for entry in frame["pcs"]))

    def test_duplicate_json_and_invalid_provenance_are_rejected(self):
        artifacts, builds = self.load()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            attribute(b'{"schema":"one","schema":"two"}', artifacts, builds)
        value = diagnostic()
        value["runner_sha256"] = "unknown"
        with self.assertRaisesRegex(ValueError, "runner_sha256"):
            attribute(json.dumps(value).encode(), artifacts, builds)

    def test_markdown_renders_labels_as_text(self):
        artifacts, builds = self.load()
        value = diagnostic()
        value["cases"][0]["name"] = "[link](https://example.com) | <script>\n# heading"
        rendered = markdown(attribute(json.dumps(value).encode(), artifacts, builds))
        self.assertNotIn("[link](https://example.com)", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("\\|", rendered)

    def test_exact_matching_never_ignores_metadata(self):
        artifacts, _ = self.load()
        self.assertEqual(
            match_artifact(bytes.fromhex("602a5000"), artifacts)[1], "exact"
        )
        self.assertEqual(
            match_artifact(bytes.fromhex("602a5001"), artifacts)[1], "unmatched"
        )
        self.assertEqual(
            match_artifact(bytes.fromhex("602a5000"), artifacts * 2)[1], "ambiguous"
        )

    def test_immutable_and_link_substitutions_only_mask_immediate_bytes(self):
        runtime = {
            "object": "7f" + "00" * 32 + "73" + "00" * 20,
            "immutableReferences": {"1": [{"start": 1, "length": 32}]},
            "linkReferences": {"L.sol": {"L": [{"start": 34, "length": 20}]}},
        }
        code, mask = runtime_template(runtime)
        candidate = Artifact("a", "b", "c", code, mask, {}, {})
        self.assertTrue(
            candidate.matches(bytes.fromhex("7f" + "ff" * 32 + "73" + "ee" * 20))
        )
        self.assertFalse(
            candidate.matches(bytes.fromhex("7e" + "ff" * 32 + "73" + "ee" * 20))
        )
        runtime["object"] = "7f" + "00" * 32 + "73" + "__$" + "a" * 34 + "$__"
        self.assertEqual(runtime_template(runtime), (code, mask))
        for start, length in ((0, 1), (54, 1), (1, 54)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                runtime_template(
                    {
                        "object": "6000",
                        "immutableReferences": {
                            "x": [{"start": start, "length": length}]
                        },
                    }
                )

    def test_missing_source_and_invalid_span_fail(self):
        build = build_info()
        build["input"]["sources"]["Example.sol"] = {
            "urls": ["https://example.invalid/"]
        }
        with self.assertRaisesRegex(TypeError, "embed"):
            self.load(build)
        artifacts, _ = self.load(build_info(mapping="999:3:0"))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            artifacts[0].location(0)

    def test_build_files_deduplicated_and_artifacts_rejected(self):
        self.load()
        self.assertEqual(
            len(load_build_info([self.root, self.root / "build.json"])[0]), 1
        )
        with self.assertRaisesRegex(ValueError, "complete Foundry"):
            self.load({"bytecode": "0x1234"})

    def test_attribution_conserves_gas_and_instructions(self):
        artifacts, builds = self.load()
        report = attribute(json.dumps(diagnostic()).encode(), artifacts, builds)
        self.assertEqual(
            report["cases"][0]["coverage"],
            {
                "solidity": {"gas": 3, "steps": 2},
                "generated": {"gas": 0, "steps": 0},
                "unmapped": {"gas": 2, "steps": 1},
            },
        )
        rendered = markdown(report)
        self.assertIn("not CPU time", rendered)
        self.assertIn("Example.sol", rendered)
        self.assertIn("Verified gas: 5", rendered)

    def test_unknown_and_ambiguous_are_explicit(self):
        artifacts, builds = self.load()
        for candidates, status in (([], "unmatched"), (artifacts * 2, "ambiguous")):
            report = attribute(json.dumps(diagnostic()).encode(), candidates, builds)
            frame = report["cases"][0]["frames"][0]
            self.assertEqual(frame["artifact_match"]["status"], status)
            self.assertTrue(all(entry["source"] is None for entry in frame["pcs"]))

    def test_reverted_child_gas_is_not_double_counted(self):
        value = diagnostic()
        case = value["cases"][0]
        child = copy.deepcopy(case["frames"][0])
        child.update(id=1, parent=0, depth=1, status="revert")
        case["frames"].append(child)
        case["frames"][0]["gas_used"] = 10
        case.update(gas_used=10, steps=6)
        artifacts, builds = self.load()
        report = attribute(json.dumps(value).encode(), artifacts, builds)
        self.assertEqual(
            sum(item["gas"] for item in report["cases"][0]["coverage"].values()), 10
        )
        self.assertEqual(report["cases"][0]["frames"][1]["status"], "revert")

    def test_invalid_pc_hash_and_accounting_fail(self):
        artifacts, builds = self.load()
        for field, value in (("pc", 1), ("opcode", 255), ("count", True), ("gas", 4)):
            report = diagnostic()
            report["cases"][0]["frames"][0]["pcs"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                attribute(json.dumps(report).encode(), artifacts, builds)
        report = diagnostic()
        report["cases"][0]["codes"]["0x" + "f" * 64] = "0x1234"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            attribute(json.dumps(report).encode(), artifacts, builds)

    def test_implicit_stop_is_not_mapped(self):
        value = diagnostic("602a50")
        report = attribute(json.dumps(value).encode(), [], [])
        self.assertEqual(
            report["cases"][0]["frames"][0]["pcs"][-1]["mapping"], "implicit-stop"
        )

    def test_cli_writes_both_reports_and_does_not_overwrite(self):
        self.load()
        diagnostics = self.root / "diagnostics.json"
        diagnostics.write_text(json.dumps(diagnostic()))
        output = self.root / "report.md"
        arguments = [
            "--build-info",
            str(self.root / "build.json"),
            "--diagnostics",
            str(diagnostics),
            "--output",
            str(output),
            "--json-output",
            str(self.root / "report.json"),
        ]
        self.assertEqual(main(arguments), 0)
        original = output.read_bytes()
        self.assertEqual(main(arguments), 1)
        self.assertEqual(output.read_bytes(), original)

    def test_cli_rejects_invalid_input_without_publishing(self):
        self.load()
        diagnostics = self.root / "bad.json"
        diagnostics.write_text('{"schema": "wrong"}')
        output = self.root / "report.md"
        self.assertEqual(
            main(
                [
                    "--build-info",
                    str(self.root / "build.json"),
                    "--diagnostics",
                    str(diagnostics),
                    "--output",
                    str(output),
                ]
            ),
            1,
        )
        self.assertFalse(output.exists())

    def test_publication_does_not_follow_dangling_symlinks(self):
        target = self.root / "target"
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(FileExistsError):
            write_new(link, "no")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
