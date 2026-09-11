from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from monad_execbench_attribution.report import attribute
from monad_execbench_report.results import integer, parse_json, require

from .export import bounded_file, write_json

IDENTITY = {
    "bundle_sha256": "fixture_bundle_sha256",
    "block_hash": "block_hash",
    "block_number": "block_number",
    "execution_env": "execution_env",
    "monad_commit": "monad_commit",
    "runner_commit": "monad_execbench_commit",
    "compiler": "compiler",
    "build_type": "build_type",
}
PROVENANCE_FIELDS = (*IDENTITY, "version", "mode", "runner_sha256")
FRAME_FIELDS = (
    "id",
    "parent",
    "depth",
    "code_hash",
    "code_kind",
    "recipient",
    "sender",
    "selector",
    "gas_supplied",
    "gas_used",
    "self_gas",
    "status",
)


def source_location(source) -> dict | None:
    if source is None:
        return None
    require(isinstance(source, dict), "source must be an object or null")
    require(source.get("kind") in ("solidity", "generated"), "unknown source kind")
    for field in ("file", "source_sha256", "snippet"):
        require(isinstance(source.get(field), str), f"invalid source {field}")
    require(
        re.fullmatch(r"[0-9a-f]{64}", source["source_sha256"]), "invalid source digest"
    )
    for field in ("start", "length", "line", "column_bytes"):
        integer(
            source.get(field),
            f"source {field}",
            1 if field in ("line", "column_bytes") else 0,
        )
    function = source.get("function")
    if function is not None:
        require(
            isinstance(function, dict) and isinstance(function.get("name"), str),
            "invalid function label",
        )
        integer(function.get("start"), "function start")
        integer(function.get("length"), "function length")
        function = {field: function[field] for field in ("name", "start", "length")}
    return {
        **{
            field: source[field]
            for field in (
                "file",
                "source_sha256",
                "kind",
                "start",
                "length",
                "line",
                "column_bytes",
                "snippet",
            )
        },
        "function": function,
    }


def build_provenance(value) -> list[dict]:
    require(isinstance(value, list), "build_info must be an array")
    result = []
    for build in value:
        require(isinstance(build, dict), "build_info entry must be an object")
        for field in ("file", "compiler"):
            require(
                isinstance(build.get(field), str) and bool(build[field].strip()),
                f"invalid build_info {field}",
            )
        require(
            isinstance(build.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", build["sha256"]),
            "invalid build_info sha256",
        )
        result.append({field: build[field] for field in ("file", "sha256", "compiler")})
    return result


def checked_profile(path: Path) -> dict:
    raw = bounded_file(path).read_bytes()
    original = parse_json(raw)
    require(isinstance(original, dict), "profile must be an object")
    mapped = original.get("schema") == "monad-execbench/attribution-v1"
    require(
        mapped or original.get("schema") == "monad-execbench/diagnostics-v1",
        "unsupported profile schema",
    )
    builds = build_provenance(original.get("build_info", []))
    require(isinstance(original.get("cases"), list), "cases must be an array")
    native = {key: original[key] for key in PROVENANCE_FIELDS if key in original}
    for field in ("version", "compiler", "build_type"):
        if field in native:
            require(
                isinstance(native[field], str) and bool(native[field].strip()),
                f"invalid profile {field}",
            )
    native["schema"] = "monad-execbench/diagnostics-v1"
    native["cases"] = []
    for case in original["cases"]:
        require(isinstance(case, dict), "case must be an object")
        require(case.get("status") in ("success", "revert"), "invalid root status")
        require(isinstance(case.get("codes"), dict), "codes must be an object")
        frames = case["frames"]
        require(isinstance(frames, list), "frames must be an array")
        require(all(isinstance(f, dict) for f in frames), "frame must be an object")
        require(
            not frames or (frames[0]["parent"] is None and frames[0]["depth"] == 0),
            "invalid root frame",
        )
        require(
            all(f["parent"] is not None for f in frames[1:]), "multiple root frames"
        )
        native_frames = []
        for frame in frames:
            require(isinstance(frame.get("pcs"), list), "pcs must be an array")
            require(
                all(isinstance(pc, dict) for pc in frame["pcs"]),
                "PC entry must be an object",
            )
            for field in ("sender", "recipient"):
                require(
                    isinstance(frame.get(field), str)
                    and re.fullmatch(r"0x[0-9a-f]{40}", frame[field]),
                    f"invalid frame {field}",
                )
            require(
                isinstance(frame.get("selector"), str)
                and re.fullmatch(r"0x(?:[0-9a-f]{2}){0,4}", frame["selector"]),
                "invalid frame selector",
            )
            native_frames.append(
                {
                    **{field: frame[field] for field in FRAME_FIELDS},
                    "pcs": [
                        {key: pc[key] for key in ("pc", "opcode", "count", "gas")}
                        for pc in frame["pcs"]
                    ],
                }
            )
        native["cases"].append(
            {
                **{
                    key: case[key]
                    for key in (
                        "name",
                        "status",
                        "gas_used",
                        "steps",
                        "outside_vm_gas",
                        "codes",
                    )
                },
                "frames": native_frames,
            }
        )
    # Reuse the diagnostic validator for code hashes, PC boundaries and gas/count
    # conservation. Saved source labels remain imported annotations, not a fresh
    # compilation or source-map authenticity check.
    checked = attribute(json.dumps(native).encode(), [], [])
    del native
    if mapped:
        for case, validated in zip(original["cases"], checked["cases"], strict=True):
            coverage = {
                kind: {"gas": 0, "steps": 0}
                for kind in ("solidity", "generated", "unmapped")
            }
            for frame, native_frame in zip(
                case["frames"], validated["frames"], strict=True
            ):
                match = frame["artifact_match"]
                require(
                    isinstance(match, dict)
                    and match.get("status")
                    in ("exact", "masked", "ambiguous", "unmatched", "creation-code"),
                    "invalid artifact match",
                )
                require(
                    isinstance(match.get("candidates"), list)
                    and all(isinstance(x, str) for x in match["candidates"]),
                    "invalid artifact candidates",
                )
                is_match = match["status"] in ("exact", "masked")
                require(
                    not is_match or len(match["candidates"]) == 1,
                    "matched frame needs one artifact",
                )
                require(
                    frame["code_kind"] != "creation"
                    or match["status"] == "creation-code",
                    "creation source match is unsupported",
                )
                native_frame["artifact_match"] = {
                    "status": match["status"],
                    "candidates": match["candidates"],
                }
                for pc, native_pc in zip(
                    frame["pcs"], native_frame["pcs"], strict=True
                ):
                    source = source_location(pc.get("source"))
                    require(
                        (source is not None) == (pc.get("mapping") == "mapped"),
                        "source and mapping reason disagree",
                    )
                    require(
                        source is None or (is_match and pc.get("mapping") == "mapped"),
                        "unmatched PC cannot have source",
                    )
                    require(
                        isinstance(pc.get("mapping"), str), "invalid PC mapping reason"
                    )
                    require(
                        native_pc["mapping"] != "implicit-stop" or source is None,
                        "implicit STOP cannot have source",
                    )
                    native_pc["source"], native_pc["mapping"] = source, pc["mapping"]
                    bucket = coverage[source["kind"] if source else "unmapped"]
                    bucket["gas"] += pc["gas"]
                    bucket["steps"] += pc["count"]
                native_frame["steps"] = sum(pc["count"] for pc in frame["pcs"])
            require(isinstance(case.get("coverage"), dict), "missing source coverage")
            for counters in case["coverage"].values():
                require(isinstance(counters, dict), "coverage entry must be an object")
                for value in counters.values():
                    integer(value, "coverage counter")
            require(
                coverage == case.get("coverage"), "source coverage does not reconcile"
            )
            validated["coverage"] = coverage
    checked["input_sha256"] = hashlib.sha256(raw).hexdigest()
    checked["input_schema"] = original["schema"]
    checked["build_info"] = builds
    return checked


def add_profiles(summary: dict, paths: list[Path], directory: Path) -> None:
    for index, path in enumerate(paths):
        profile = checked_profile(path)
        provenance = {key: value for key, value in profile.items() if key != "cases"}
        provenance["id"] = f"p{index}"
        provenance["file"] = path.name
        summary["profiles"].append(provenance)
        for case_index, case in enumerate(profile["cases"]):
            identifier = f"p{index}-c{case_index}"
            targets = []
            for run in summary["runs"]:
                if all(
                    str(profile.get(left)) == str(run["context"].get(right))
                    for left, right in IDENTITY.items()
                ):
                    targets.extend(
                        item for item in run["cases"] if item["name"] == case["name"]
                    )
            require(
                bool(targets),
                f"profile case has no compatible timing input: {case['name']}",
            )
            for item in targets:
                require(
                    item["profile"] is None,
                    "duplicate or ambiguous profile for timing case",
                )
                require(
                    item["gas"] == case["gas_used"]
                    and item["status"] == case["status"],
                    "profile execution result disagrees with timing",
                )
                item["profile"] = identifier
            sources = []
            source_ids = {}
            source_totals = defaultdict(lambda: {"gas": 0, "steps": 0})
            opcodes = defaultdict(lambda: {"gas": 0, "steps": 0})
            frames = []
            for frame in case["frames"]:
                pcs = []
                for pc in frame["pcs"]:
                    source = source_location(pc["source"])
                    source_id = None
                    if source:
                        key = json.dumps(source, sort_keys=True)
                        if key not in source_ids:
                            source_ids[key] = len(sources)
                            sources.append(source)
                        source_id = source_ids[key]
                        source_totals[source_id]["gas"] += pc["gas"]
                        source_totals[source_id]["steps"] += pc["count"]
                    opcodes[pc["opcode"]]["gas"] += pc["gas"]
                    opcodes[pc["opcode"]]["steps"] += pc["count"]
                    pcs.append(
                        {
                            **{
                                key: pc[key]
                                for key in ("pc", "opcode", "gas", "count", "mapping")
                            },
                            "source": source_id,
                        }
                    )
                detail = {
                    **{field: frame[field] for field in FRAME_FIELDS},
                    "artifact_match": frame["artifact_match"],
                    "steps": sum(pc["count"] for pc in frame["pcs"]),
                    "file": f"{identifier}/frame-{frame['id']}.json",
                }
                frames.append(detail)
                write_json(
                    directory / detail["file"], {"frame": frame["id"], "pcs": pcs}
                )
            write_json(
                directory / f"{identifier}.json",
                {
                    "id": identifier,
                    "name": case["name"],
                    "gas": case["gas_used"],
                    "steps": case["steps"],
                    "outside_vm_gas": case["outside_vm_gas"],
                    "coverage": case["coverage"],
                    "frames": frames,
                    "sources": sources,
                    "source_totals": [
                        {"source": key, **value}
                        for key, value in sorted(
                            source_totals.items(), key=lambda pair: -pair[1]["gas"]
                        )
                    ],
                    "opcodes": [
                        {"opcode": key, **value}
                        for key, value in sorted(
                            opcodes.items(), key=lambda pair: -pair[1]["gas"]
                        )
                    ],
                },
            )
