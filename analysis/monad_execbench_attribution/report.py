from __future__ import annotations

import copy
import hashlib
import html
import re

from Crypto.Hash import keccak

from .sources import Artifact, instructions, integer, json_document, match_artifact


def bytecode(value: object) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError("code must be a 0x-prefixed hex string")
    return bytes.fromhex(value[2:])


def attribute(raw: bytes, artifacts: list[Artifact], builds: list[dict]) -> dict:
    report = json_document(raw)
    if report.get("schema") != "monad-execbench/diagnostics-v1":
        raise ValueError("expected monad-execbench/diagnostics-v1")
    if (
        report.get("mode") != "diagnostic-interpreter"
        or report.get("execution_env") != "MONAD_TEN"
    ):
        raise ValueError("unsupported diagnostic mode or execution environment")
    if not isinstance(report.get("cases"), list) or not report["cases"]:
        raise ValueError("diagnostics must contain cases")
    integer(report["block_number"], "block number")
    for field in ("block_hash", "bundle_sha256", "runner_sha256"):
        if re.fullmatch(r"0x[0-9a-f]{64}", report.get(field, "")) is None:
            raise ValueError(f"invalid {field}")
    for field in ("monad_commit", "runner_commit"):
        if re.fullmatch(r"[0-9a-f]{40}(?:-dirty)?", report.get(field, "")) is None:
            raise ValueError(f"invalid {field}")
    report = copy.deepcopy(report)
    report["schema"] = "monad-execbench/attribution-v1"
    report["diagnostics_sha256"] = hashlib.sha256(raw).hexdigest()
    report["build_info"] = builds
    names = set()
    for case in report["cases"]:
        if not isinstance(case["name"], str) or case["name"] in names:
            raise ValueError("invalid or duplicate case name")
        names.add(case["name"])
        gas_used = integer(case["gas_used"], "case gas")
        outside = integer(case["outside_vm_gas"], "outside VM gas")
        expected_steps = integer(case["steps"], "steps")
        codes = {}
        matches = {}
        pc_maps = {}
        for code_hash, text in case["codes"].items():
            code = bytecode(text)
            if code_hash != "0x" + keccak.new(digest_bits=256, data=code).hexdigest():
                raise ValueError("diagnostic code hash mismatch")
            codes[code_hash] = code
            matches[code_hash] = match_artifact(code, artifacts)
            pc_maps[code_hash] = instructions(code)
        totals = {
            kind: {"gas": 0, "steps": 0}
            for kind in ("solidity", "generated", "unmapped")
        }
        steps = 0
        vm_gas = 0
        children = {}
        for index, frame in enumerate(case["frames"]):
            if integer(frame["id"], "frame ID") != index:
                raise ValueError("frame IDs must be consecutive")
            parent = frame["parent"]
            if parent is not None and integer(parent, "parent ID") >= index:
                raise ValueError("frame parent must precede child")
            depth = integer(frame["depth"], "frame depth")
            if parent is not None and depth != case["frames"][parent]["depth"] + 1:
                raise ValueError("frame depth does not match parent")
            if frame["status"] not in ("success", "revert", "error"):
                raise ValueError("invalid frame status")
            inclusive = integer(frame["gas_used"], "frame gas")
            if inclusive > integer(frame["gas_supplied"], "frame supplied gas"):
                raise ValueError("frame consumed more than supplied gas")
            children[parent] = children.get(parent, 0) + inclusive
            code_hash = frame["code_hash"]
            artifact, match, candidates = matches[code_hash]
            if frame["code_kind"] == "creation":
                artifact, match, candidates = None, "creation-code", []
            elif frame["code_kind"] != "runtime":
                raise ValueError("invalid frame code kind")
            frame["artifact_match"] = {"status": match, "candidates": candidates}
            if artifact:
                frame["artifact_match"].update(
                    {
                        "build_sha256": artifact.build_sha256,
                        "compiler": artifact.compiler,
                    }
                )
            seen = set()
            self_gas = 0
            for entry in frame["pcs"]:
                pc = integer(entry["pc"], "PC")
                opcode = integer(entry["opcode"], "opcode")
                count = integer(entry["count"], "opcode count", 1)
                gas = integer(entry["gas"], "opcode gas")
                if pc in seen:
                    raise ValueError("duplicate PC in frame")
                seen.add(pc)
                expected_opcode = pc_maps[code_hash].get(pc)
                # The interpreter pads bytecode with STOPs; a trailing PUSH can
                # advance past the code length to exactly one implicit STOP.
                code = codes[code_hash]
                boundaries = pc_maps[code_hash]
                last_pc = next(reversed(boundaries), None)
                terminal_pc = (
                    0
                    if last_pc is None
                    else last_pc
                    + 1
                    + (code[last_pc] - 0x5F if 0x60 <= code[last_pc] <= 0x7F else 0)
                )
                implicit = pc == terminal_pc and opcode == 0
                if not implicit and expected_opcode != opcode:
                    raise ValueError(
                        "diagnostic PC/opcode does not match code boundary"
                    )
                source, reason = (
                    (None, "implicit-stop")
                    if implicit
                    else (artifact.location(pc) if artifact else (None, match))
                )
                entry["source"] = source
                entry["mapping"] = reason
                kind = source["kind"] if source else "unmapped"
                totals[kind]["gas"] += gas
                totals[kind]["steps"] += count
                self_gas += gas
                steps += count
            if self_gas != integer(frame["self_gas"], "frame self gas"):
                raise ValueError("PC gas does not reconcile with frame self gas")
            vm_gas += self_gas
        for frame in case["frames"]:
            if frame["gas_used"] != frame["self_gas"] + children.get(frame["id"], 0):
                raise ValueError("frame gas does not reconcile with children")
        if steps != expected_steps or vm_gas + outside != gas_used:
            raise ValueError("case gas or steps do not reconcile")
        case["coverage"] = totals
    return report


def escape(value: object) -> str:
    value = html.escape(str(value), quote=True)
    return (
        re.sub(r"([\\`*_{}\[\]()|~])", r"\\\1", value)
        .replace("\r", " ")
        .replace("\n", " ")
    )


def markdown(report: dict, top: int = 20) -> str:
    lines = [
        "# Solidity execution attribution",
        "",
        (
            "Diagnostic MONAD_TEN interpreter replay. Gas and executed opcode counts are **not CPU time**, "
            "JIT samples, or internal Solidity function-call counts. Timing results must come from the separate uninstrumented runner."
        ),
        "",
        f"Block: {report['block_number']} ({escape(report['block_hash'])}).",
        f"Fixture bundle: `{escape(report['bundle_sha256'])}`.",
        f"Monad: `{escape(report['monad_commit'])}`. Runner: `{escape(report['runner_commit'])}`.",
        f"Diagnostics SHA-256: `{report['diagnostics_sha256']}`.",
        f"Diagnostic executable SHA-256: `{report['runner_sha256']}`.",
        "",
        (
            "Gas is gross consumption before refunds. PC costs exclude child bytecode frames; precompile, "
            "empty-account and host-side call costs stay on the calling opcode. Reverted work is retained. "
            "Work outside any bytecode frame is reported separately. Source ranges are compiler attribution, "
            "not exact ownership after optimization/inlining."
        ),
        "",
        "## Compiler inputs",
        "",
        "| Build-info | Compiler | SHA-256 |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {escape(build['file'])} | {escape(build['compiler'])} | {build['sha256']} |"
        for build in report["build_info"]
    )
    for case in report["cases"]:
        lines.extend(
            [
                "",
                f"## {escape(case['name'])}",
                "",
                (
                    f"Verified gas: {case['gas_used']:,}. Executed instructions: {case['steps']:,}. "
                    f"Outside bytecode frames: {case['outside_vm_gas']:,} gas."
                ),
                "",
                "| Coverage | Gas | Instructions |",
                "| --- | ---: | ---: |",
            ]
        )
        for kind, counters in case["coverage"].items():
            lines.append(f"| {kind} | {counters['gas']:,} | {counters['steps']:,} |")
        lines.extend(
            [
                "",
                "### Bytecode frames",
                "",
                (
                    "Recipient is the storage context, not necessarily the code address (for example, DELEGATECALL). "
                    "Interpreter invocations appear here, including implicit STOP for empty code; code hashes drive artifact matching."
                ),
                "",
                "| ID / parent | Recipient | Contract / match | Status | Inclusive gas | Self gas |",
                "| --- | --- | --- | --- | ---: | ---: |",
            ]
        )
        rows = {}
        for frame in case["frames"]:
            match = frame["artifact_match"]
            label = ", ".join(match["candidates"]) or frame["code_hash"]
            lines.append(
                f"| {frame['id']} / {frame['parent']} | {escape(frame['recipient'])} | "
                f"{escape(label)} ({match['status']}) | {escape(frame['status'])} | "
                f"{frame['gas_used']:,} | {frame['self_gas']:,} |"
            )
            for entry in frame["pcs"]:
                source = entry["source"]
                if source:
                    function = source["function"]
                    label = (
                        f"{source['file']}:{source['line']}:{source['column_bytes']}"
                    )
                    label += f" — {function['name']}" if function else ""
                    key = (
                        frame["code_hash"],
                        source["source_id"],
                        source["start"],
                        source["length"],
                    )
                else:
                    label = (
                        f"{frame['code_hash']} PC {entry['pc']} ({entry['mapping']})"
                    )
                    key = (frame["code_hash"], entry["pc"], entry["mapping"])
                row = rows.setdefault(key, {"location": label, "gas": 0, "steps": 0})
                row["gas"] += entry["gas"]
                row["steps"] += entry["count"]
        ranked = sorted(
            rows.values(), key=lambda row: (-row["gas"], -row["steps"], row["location"])
        )
        lines.extend(
            [
                "",
                f"### Top {top} source spans / unmapped PCs",
                "",
                "| Location | Self gas | Instructions |",
                "| --- | ---: | ---: |",
            ]
        )
        for row in ranked[:top]:
            lines.append(
                f"| {escape(row['location'])} | {row['gas']:,} | {row['steps']:,} |"
            )
        lines.append(
            f"\nShowing {min(top, len(ranked))} of {len(ranked)} locations. Full per-frame/PC details are in the JSON report."
        )
    return "\n".join(lines) + "\n"
