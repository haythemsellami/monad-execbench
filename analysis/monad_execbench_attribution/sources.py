from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def json_document(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise TypeError("expected a JSON object")
    return result


def integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def instructions(code: bytes) -> dict[int, int]:
    result = {}
    pc = 0
    while pc < len(code):
        opcode = code[pc]
        result[pc] = opcode
        pc += 1 + (opcode - 0x5F if 0x60 <= opcode <= 0x7F else 0)
    return result


def source_map(text: str) -> list[tuple[int, int, int, str, int]]:
    if not isinstance(text, str):
        raise TypeError("sourceMap must be a string")
    if not text:
        return []
    previous = [-1, -1, -1, "-", 0]
    entries = []
    for entry in text.split(";"):
        fields = entry.split(":")
        if len(fields) > 5:
            raise ValueError("sourceMap entry has more than five fields")
        for index, value in enumerate(fields):
            if value:
                previous[index] = value if index == 3 else int(value)
        if any(previous[i] < -1 for i in (0, 1, 2)):
            raise ValueError("invalid negative sourceMap offset, length, or ID")
        if previous[3] not in ("i", "o", "-") or previous[4] < 0:
            raise ValueError("invalid sourceMap jump or modifier depth")
        entries.append(tuple(previous))
    return entries


def functions(ast: object, source_id: int) -> list[dict]:
    found = []
    pending = [ast]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            if node.get("nodeType") in ("FunctionDefinition", "ModifierDefinition"):
                start, length, file_id = map(int, node["src"].split(":"))
                if file_id == source_id:
                    found.append(
                        {
                            "name": node.get("name") or node.get("kind", "<unnamed>"),
                            "start": start,
                            "length": length,
                        }
                    )
            pending.extend(node.values())
    return sorted(found, key=lambda item: item["length"])


@dataclass
class Artifact:
    name: str
    build_sha256: str
    compiler: str
    code: bytes
    mask: frozenset[int]
    mappings: dict[int, tuple]
    sources: dict[int, dict]

    def matches(self, code: bytes) -> bool:
        return len(self.code) == len(code) and all(
            left == right or index in self.mask
            for index, (left, right) in enumerate(zip(self.code, code))
        )

    def location(self, pc: int) -> tuple[dict | None, str]:
        mapping = self.mappings.get(pc)
        if mapping is None:
            return None, "no-source-map-entry"
        start, length, source_id, jump, modifier_depth = mapping
        source = self.sources.get(source_id)
        if start < 0 or length < 0 or source_id < 0:
            return None, "compiler-unmapped"
        if source is None:
            return None, "source-unavailable"
        content = source["content"].encode("utf-8")
        if start + length > len(content):
            raise ValueError(
                f"{self.name}: source span exceeds embedded source content"
            )
        # Solidity offsets and lengths are bytes, not Unicode character indices.
        prefix = content[:start]
        function = next(
            (
                item
                for item in source["functions"]
                if item["start"] <= start
                and start + length <= item["start"] + item["length"]
            ),
            None,
        )
        return {
            "file": source["name"],
            "source_id": source_id,
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "kind": source["kind"],
            "start": start,
            "length": length,
            "line": prefix.count(b"\n") + 1,
            "column_bytes": len(prefix.rsplit(b"\n", 1)[-1]) + 1,
            "function": function,
            "jump": jump,
            "modifier_depth": modifier_depth,
            "snippet": content[start : start + min(length, 240)].decode(
                "utf-8", errors="replace"
            ),
        }, "mapped"


def runtime_template(runtime: dict) -> tuple[bytes, frozenset[int]]:
    text = runtime["object"]
    if not isinstance(text, str):
        raise TypeError("bytecode object must be a string")
    text = text.removeprefix("0x")
    if len(text) % 2:
        raise ValueError("odd-length bytecode object")
    size = len(text) // 2
    ranges = []
    for values in runtime.get("immutableReferences", {}).values():
        ranges.extend(values)
    for libraries in runtime.get("linkReferences", {}).values():
        for values in libraries.values():
            ranges.extend(values)
    mask = set()
    for entry in ranges:
        start = integer(entry["start"], "reference start")
        length = integer(entry["length"], "reference length", 1)
        if start + length > size:
            raise ValueError("bytecode reference exceeds runtime length")
        indices = set(range(start, start + length))
        if mask & indices:
            raise ValueError("overlapping bytecode references")
        mask.update(indices)
    normalized = "".join(
        "00" if index in mask else text[index * 2 : index * 2 + 2]
        for index in range(size)
    )
    code = bytes.fromhex(normalized)
    immediate_bytes = set()
    for pc, opcode in instructions(code).items():
        if 0x60 <= opcode <= 0x7F:
            immediate_bytes.update(range(pc + 1, min(size, pc + 1 + opcode - 0x5F)))
    if not mask <= immediate_bytes:
        raise ValueError("bytecode references must cover only PUSH immediate bytes")
    return code, frozenset(mask)


def load_build_info(paths: list[Path]) -> tuple[list[Artifact], list[dict]]:
    files = sorted(
        {
            file.resolve()
            for path in paths
            for file in (path.glob("*.json") if path.is_dir() else [path])
        }
    )
    if not files:
        raise ValueError("no build-info JSON files found")
    artifacts = []
    provenance = []
    seen = set()
    for file in files:
        raw = file.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        build = json_document(raw)
        if "input" not in build or "output" not in build:
            raise ValueError(
                f"{file.name}: expected complete Foundry build-info, not an artifact"
            )
        compiler = build.get("solcLongVersion", build.get("solcVersion", "unknown"))
        sources = {}
        for name, source in build["output"].get("sources", {}).items():
            source_id = integer(source["id"], "source ID")
            if source_id in sources:
                raise ValueError("duplicate source ID in build-info")
            content = build["input"]["sources"][name].get("content")
            if not isinstance(content, str):
                raise TypeError(f"{name}: build-info must embed source content")
            sources[source_id] = {
                "name": name,
                "content": content,
                "kind": "solidity",
                "functions": functions(source.get("ast"), source_id),
            }
        for filename, contracts in build["output"].get("contracts", {}).items():
            for name, contract in contracts.items():
                runtime = contract.get("evm", {}).get("deployedBytecode", {})
                if not runtime.get("object"):
                    continue
                code, mask = runtime_template(runtime)
                maps = source_map(runtime.get("sourceMap", ""))
                pcs = list(instructions(code))
                if len(maps) > len(pcs):
                    raise ValueError(
                        f"{filename}:{name}: more source mappings than instructions"
                    )
                scoped_sources = dict(sources)
                for generated in runtime.get("generatedSources", []):
                    source_id = integer(generated["id"], "generated source ID")
                    if source_id in scoped_sources:
                        raise ValueError("generated source ID collides with source ID")
                    scoped_sources[source_id] = {
                        "name": generated["name"],
                        "content": generated["contents"],
                        "kind": "generated",
                        "functions": [],
                    }
                artifacts.append(
                    Artifact(
                        f"{filename}:{name}",
                        digest,
                        compiler,
                        code,
                        mask,
                        dict(zip(pcs, maps)),
                        scoped_sources,
                    )
                )
        provenance.append({"file": file.name, "sha256": digest, "compiler": compiler})
    if not artifacts:
        raise ValueError("build-info contains no runtime bytecode")
    return artifacts, provenance


def match_artifact(
    code: bytes, artifacts: list[Artifact]
) -> tuple[Artifact | None, str, list[str]]:
    matches = [artifact for artifact in artifacts if artifact.matches(code)]
    # Even byte-identical contracts can have different source maps. Never choose
    # an arbitrary source location when several compilations could explain code.
    if len(matches) != 1:
        return (
            None,
            "ambiguous" if matches else "unmatched",
            sorted(item.name for item in matches),
        )
    match = matches[0]
    return match, "masked" if match.mask else "exact", [match.name]
