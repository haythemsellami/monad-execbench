from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import zstandard

CALLS_SCHEMA = "monad-execbench/calls-v1"
FIXTURE_SCHEMA = "monad-execbench/v1"
PROVENANCE_SCHEMA = "monad-execbench/provenance-v1"
DEFAULT_EXECUTION_ENV = "MONAD_TEN"
EMPTY_CODE_HASH = "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
EMPTY_STORAGE_ROOT = (
    "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
)
EVMC_MAX_GAS = (1 << 63) - 1


class CaptureError(RuntimeError):
    pass


class Rpc(Protocol):
    def call(self, method: str, params: list[Any]) -> Any: ...

    def batch(self, method: str, params: list[list[Any]]) -> list[Any]: ...


@dataclass(frozen=True)
class CaptureBundle:
    manifest: dict[str, Any]
    cases: list[dict[str, Any]]
    state: dict[str, Any]
    chain_id: int
    block_number: int
    block_hash: str


def parse_quantity(value: Any, path: str) -> int:
    if isinstance(value, bool):
        raise CaptureError(f"{path}: expected an unsigned quantity")
    if isinstance(value, int):
        if value < 0:
            raise CaptureError(f"{path}: expected an unsigned quantity")
        return value
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{path}: expected an unsigned quantity")
    base = 16 if value.startswith("0x") else 10
    digits = value[2:] if base == 16 else value
    if not digits:
        raise CaptureError(f"{path}: expected an unsigned quantity")
    try:
        result = int(digits, base)
    except ValueError as error:
        raise CaptureError(f"{path}: invalid unsigned quantity") from error
    if result < 0:
        raise CaptureError(f"{path}: expected an unsigned quantity")
    return result


def quantity(value: int) -> str:
    return hex(value)


def decimal_quantity(value: Any, path: str) -> str:
    return str(parse_quantity(value, path))


def normalize_address(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise CaptureError(f"{path}: expected a 20-byte address")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise CaptureError(f"{path}: invalid address") from error
    return value.lower()


def normalize_bytes(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise CaptureError(f"{path}: expected 0x-prefixed bytes")
    digits = value[2:]
    if len(digits) % 2:
        raise CaptureError(f"{path}: expected even-length bytes")
    try:
        bytes.fromhex(digits)
    except ValueError as error:
        raise CaptureError(f"{path}: invalid hexadecimal bytes") from error
    return "0x" + digits.lower()


def normalize_bytes32(value: Any, path: str) -> str:
    result = normalize_bytes(value, path)
    if len(result) != 66:
        raise CaptureError(f"{path}: expected exactly 32 bytes")
    return result


def normalize_storage_key(value: Any, path: str) -> str:
    parsed = parse_quantity(value, path)
    if parsed >= 1 << 256:
        raise CaptureError(f"{path}: storage key exceeds 256 bits")
    return "0x" + parsed.to_bytes(32, "big").hex()


def require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaptureError(f"{path}: expected an object")
    return value


def require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise CaptureError(f"{path}: expected an array")
    return value


def reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CaptureError(f"{path}: unknown field {unknown[0]!r}")


def load_calls_document(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError(f"calls manifest is not valid JSON: {error}") from error
    manifest = require_mapping(document, "calls")
    reject_unknown_keys(manifest, {"schema", "cases"}, "calls")
    if manifest.get("schema") != CALLS_SCHEMA:
        raise CaptureError(
            f"calls.schema: expected {CALLS_SCHEMA!r}, got {manifest.get('schema')!r}"
        )
    cases = require_list(manifest.get("cases"), "calls.cases")
    if not cases:
        raise CaptureError("calls.cases: expected at least one case")
    return dict(manifest)


def normalize_access_list(value: Any, path: str) -> list[dict[str, Any]]:
    entries = require_list(value, path)
    result: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entries):
        entry_path = f"{path}[{index}]"
        entry = require_mapping(raw_entry, entry_path)
        reject_unknown_keys(entry, {"address", "storageKeys"}, entry_path)
        address = normalize_address(entry.get("address"), f"{entry_path}.address")
        keys = require_list(entry.get("storageKeys"), f"{entry_path}.storageKeys")
        result.append(
            {
                "address": address,
                "storageKeys": [
                    normalize_storage_key(key, f"{entry_path}.storageKeys[{key_index}]")
                    for key_index, key in enumerate(keys)
                ],
            }
        )
    return result


def normalize_call(
    raw_case: Any, index: int, block_gas_limit: int, block_base_fee: int
) -> tuple[str, dict[str, Any]]:
    path = f"calls.cases[{index}]"
    case = require_mapping(raw_case, path)
    reject_unknown_keys(
        case,
        {"name", "from", "to", "input", "value", "gas", "gasPrice", "accessList"},
        path,
    )
    name = case.get("name")
    if not isinstance(name, str) or not name:
        raise CaptureError(f"{path}.name: expected a non-empty string")
    sender = normalize_address(case.get("from"), f"{path}.from")
    recipient = normalize_address(case.get("to"), f"{path}.to")
    input_data = normalize_bytes(case.get("input", "0x"), f"{path}.input")
    value = parse_quantity(case.get("value", 0), f"{path}.value")
    gas = parse_quantity(case.get("gas", block_gas_limit), f"{path}.gas")
    gas_price = parse_quantity(case.get("gasPrice", block_base_fee), f"{path}.gasPrice")
    if gas == 0:
        raise CaptureError(f"{path}.gas: expected a positive quantity")
    if gas_price < block_base_fee:
        raise CaptureError(f"{path}.gasPrice: must be at least the block base fee")
    access_list = normalize_access_list(
        case.get("accessList", []), f"{path}.accessList"
    )
    return name, {
        "from": sender,
        "to": recipient,
        "data": input_data,
        "value": quantity(value),
        "gas": quantity(gas),
        "gasPrice": quantity(gas_price),
        "accessList": access_list,
    }


def derive_execution_gas(
    rpc_gas_limit: int, call_trace: Mapping[str, Any], path: str
) -> tuple[int, int]:
    execution_limit = parse_quantity(call_trace.get("gas"), f"{path}.gas")
    total_used = parse_quantity(call_trace.get("gasUsed"), f"{path}.gasUsed")
    if execution_limit > rpc_gas_limit:
        raise CaptureError(f"{path}: tracer gas exceeds the supplied gas limit")
    intrinsic_gas = rpc_gas_limit - execution_limit
    if total_used < intrinsic_gas:
        raise CaptureError(f"{path}: tracer gas used is below intrinsic gas")
    execution_used = total_used - intrinsic_gas
    if execution_limit > EVMC_MAX_GAS:
        raise CaptureError(f"{path}: execution gas exceeds the EVMC signed range")
    if execution_used > execution_limit:
        raise CaptureError(f"{path}: execution gas used exceeds execution gas")
    return execution_limit, execution_used


def collect_logs(
    frame: Mapping[str, Any], path: str = "callTrace"
) -> list[dict[str, Any]]:
    if frame.get("error") is not None:
        return []
    positioned: list[tuple[int, int, dict[str, Any]]] = []
    sequence = 0

    def visit(current: Mapping[str, Any], current_path: str) -> None:
        nonlocal sequence
        if current.get("error") is not None:
            return
        for index, raw_log in enumerate(current.get("logs", [])):
            log_path = f"{current_path}.logs[{index}]"
            log = require_mapping(raw_log, log_path)
            topics = require_list(log.get("topics"), f"{log_path}.topics")
            position = parse_quantity(
                log.get("position", sequence), f"{log_path}.position"
            )
            positioned.append(
                (
                    position,
                    sequence,
                    {
                        "address": normalize_address(
                            log.get("address"), f"{log_path}.address"
                        ),
                        "data": normalize_bytes(
                            log.get("data", "0x"), f"{log_path}.data"
                        ),
                        "topics": [
                            normalize_bytes32(
                                topic, f"{log_path}.topics[{topic_index}]"
                            )
                            for topic_index, topic in enumerate(topics)
                        ],
                    },
                )
            )
            sequence += 1
        for index, raw_child in enumerate(current.get("calls", [])):
            child_path = f"{current_path}.calls[{index}]"
            visit(require_mapping(raw_child, child_path), child_path)

    visit(frame, path)
    positioned.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in positioned]


def expected_state(
    diff_trace: Any, sender: str, path: str
) -> dict[str, dict[str, Any]]:
    diff = require_mapping(diff_trace, path)
    post = require_mapping(diff.get("post", {}), f"{path}.post")
    result: dict[str, dict[str, Any]] = {}
    for raw_address, raw_account in post.items():
        address = normalize_address(raw_address, f"{path}.post address")
        account = require_mapping(raw_account, f"{path}.post.{address}")
        assertion: dict[str, Any] = {}
        if "nonce" in account and address != sender:
            assertion["nonce"] = decimal_quantity(
                account["nonce"], f"{path}.post.{address}.nonce"
            )
        if "code" in account:
            assertion["code"] = normalize_bytes(
                account["code"], f"{path}.post.{address}.code"
            )
        if "storage" in account:
            storage = require_mapping(
                account["storage"], f"{path}.post.{address}.storage"
            )
            assertion["storage"] = {
                normalize_storage_key(
                    key, f"{path}.post.{address}.storage key"
                ): normalize_bytes32(value, f"{path}.post.{address}.storage.{key}")
                for key, value in storage.items()
            }
        if assertion:
            result[address] = assertion
    return dict(sorted(result.items()))


def add_prestate_requirements(
    requirements: dict[str, set[str]], prestate: Any, path: str
) -> None:
    accounts = require_mapping(prestate, path)
    for raw_address, raw_account in accounts.items():
        address = normalize_address(raw_address, f"{path} address")
        account = require_mapping(raw_account, f"{path}.{address}")
        keys = requirements.setdefault(address, set())
        storage = require_mapping(
            account.get("storage", {}), f"{path}.{address}.storage"
        )
        for key in storage:
            keys.add(normalize_storage_key(key, f"{path}.{address}.storage key"))


def capture_suite(
    rpc: Rpc,
    calls_document: Mapping[str, Any],
    *,
    block_selector: str = "latest",
    execution_env: str = DEFAULT_EXECUTION_ENV,
) -> CaptureBundle:
    if execution_env != DEFAULT_EXECUTION_ENV:
        raise CaptureError(f"unsupported execution environment: {execution_env}")
    if calls_document.get("schema") != CALLS_SCHEMA:
        raise CaptureError(f"calls.schema: expected {CALLS_SCHEMA!r}")

    requested_tag = normalize_block_selector(block_selector)
    block = require_mapping(
        rpc.call("eth_getBlockByNumber", [requested_tag, False]), "block"
    )
    block_number = parse_quantity(block.get("number"), "block.number")
    block_tag = quantity(block_number)
    block_hash = normalize_bytes32(block.get("hash"), "block.hash")
    chain_id = parse_quantity(rpc.call("eth_chainId", []), "chainId")
    block_gas_limit = parse_quantity(block.get("gasLimit"), "block.gasLimit")
    beneficiary = normalize_address(
        block.get("miner", block.get("beneficiary")), "block.beneficiary"
    )
    prev_randao = normalize_bytes32(
        block.get("prevRandao", block.get("mixHash")), "block.prevRandao"
    )
    base_fee = parse_quantity(block.get("baseFeePerGas"), "block.baseFeePerGas")

    block_hashes = capture_block_hashes(rpc, block_number)
    requirements: dict[str, set[str]] = {beneficiary: set()}
    captured_cases: list[dict[str, Any]] = []
    names: set[str] = set()
    raw_cases = require_list(calls_document.get("cases"), "calls.cases")

    for index, raw_case in enumerate(raw_cases):
        name, call = normalize_call(raw_case, index, block_gas_limit, base_fee)
        if name in names:
            raise CaptureError(f"calls.cases[{index}].name: duplicate case {name!r}")
        names.add(name)
        case_path = f"cases[{index}]"
        prestate = rpc.call(
            "debug_traceCall", [call, block_tag, {"tracer": "prestateTracer"}]
        )
        diff = rpc.call(
            "debug_traceCall",
            [
                call,
                block_tag,
                {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}},
            ],
        )
        call_trace = require_mapping(
            rpc.call(
                "debug_traceCall",
                [
                    call,
                    block_tag,
                    {"tracer": "callTracer", "tracerConfig": {"withLog": True}},
                ],
            ),
            f"{case_path}.callTrace",
        )

        add_prestate_requirements(requirements, prestate, f"{case_path}.prestate")
        requirements.setdefault(call["from"], set())
        requirements.setdefault(call["to"], set())
        for access_entry in call["accessList"]:
            requirements.setdefault(access_entry["address"], set()).update(
                access_entry["storageKeys"]
            )

        rpc_gas_limit = parse_quantity(call["gas"], f"{case_path}.message.gas")
        execution_limit, execution_used = derive_execution_gas(
            rpc_gas_limit, call_trace, f"{case_path}.callTrace"
        )
        trace_error = call_trace.get("error")
        if trace_error is None:
            status = "success"
        elif str(trace_error).lower() == "execution reverted":
            status = "revert"
        else:
            raise CaptureError(
                f"{case_path}.callTrace: unsupported execution error {trace_error!r}"
            )

        expected: dict[str, Any] = {
            "status": status,
            "output": normalize_bytes(
                call_trace.get("output", "0x"), f"{case_path}.callTrace.output"
            ),
            "gasUsed": str(execution_used),
            "logs": collect_logs(call_trace, f"{case_path}.callTrace"),
        }
        state_assertion = expected_state(diff, call["from"], f"{case_path}.diff")
        if state_assertion:
            expected["state"] = state_assertion
        captured_cases.append(
            {
                "name": name,
                "message": {
                    "from": call["from"],
                    "to": call["to"],
                    "input": call["data"],
                    "value": decimal_quantity(call["value"], f"{case_path}.value"),
                    "gas": str(execution_limit),
                    "gasPrice": decimal_quantity(
                        call["gasPrice"], f"{case_path}.gasPrice"
                    ),
                    "accessList": call["accessList"],
                },
                "expected": expected,
            }
        )

    state = hydrate_state(rpc, requirements, block_tag)
    stable_block = require_mapping(
        rpc.call("eth_getBlockByNumber", [block_tag, False]), "block recheck"
    )
    if normalize_bytes32(stable_block.get("hash"), "block recheck.hash") != block_hash:
        raise CaptureError("selected block changed during capture")

    manifest = {
        "schema": FIXTURE_SCHEMA,
        "chain": {"chainId": str(chain_id), "executionEnv": execution_env},
        "block": {
            "number": str(block_number),
            "hash": block_hash,
            "parentHash": normalize_bytes32(
                block.get("parentHash"), "block.parentHash"
            ),
            "timestamp": decimal_quantity(block.get("timestamp"), "block.timestamp"),
            "gasLimit": str(block_gas_limit),
            "baseFee": str(base_fee),
            "beneficiary": beneficiary,
            "prevRandao": prev_randao,
            "blockHashes": block_hashes,
        },
        "state": "state.json.zst",
        "cases": "cases.json",
    }
    return CaptureBundle(
        manifest=manifest,
        cases=captured_cases,
        state=state,
        chain_id=chain_id,
        block_number=block_number,
        block_hash=block_hash,
    )


def normalize_block_selector(value: str) -> str:
    if value in {"latest", "safe", "finalized"}:
        return value
    return quantity(parse_quantity(value, "block selector"))


def capture_block_hashes(rpc: Rpc, block_number: int) -> dict[str, str]:
    numbers = list(range(max(0, block_number - 256), block_number))
    result: dict[str, str] = {}
    for offset in range(0, len(numbers), 50):
        chunk = numbers[offset : offset + 50]
        blocks = rpc.batch(
            "eth_getBlockByNumber", [[quantity(number), False] for number in chunk]
        )
        for number, raw_block in zip(chunk, blocks, strict=True):
            block = require_mapping(raw_block, f"blockHashes.{number}")
            result[str(number)] = normalize_bytes32(
                block.get("hash"), f"blockHashes.{number}.hash"
            )
    return result


def hydrate_state(
    rpc: Rpc, requirements: Mapping[str, set[str]], block_tag: str
) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    absent_accounts: list[str] = []
    for address in sorted(requirements):
        storage_keys = sorted(requirements[address])
        proof = require_mapping(
            rpc.call("eth_getProof", [address, storage_keys, block_tag]),
            f"proof.{address}",
        )
        proof_address = normalize_address(
            proof.get("address"), f"proof.{address}.address"
        )
        if proof_address != address:
            raise CaptureError(f"proof.{address}: response address mismatch")
        balance = parse_quantity(proof.get("balance"), f"proof.{address}.balance")
        nonce = parse_quantity(proof.get("nonce"), f"proof.{address}.nonce")
        code_hash = normalize_bytes32(
            proof.get("codeHash"), f"proof.{address}.codeHash"
        )
        storage_root = normalize_bytes32(
            proof.get("storageHash"), f"proof.{address}.storageHash"
        )
        code = normalize_bytes(
            rpc.call("eth_getCode", [address, block_tag]), f"code.{address}"
        )
        computed_code_hash = normalize_bytes32(
            rpc.call("web3_sha3", [code]), f"codeHash.{address}"
        )
        if computed_code_hash != code_hash:
            raise CaptureError(f"proof.{address}: runtime code hash mismatch")

        storage_proofs = require_list(
            proof.get("storageProof"), f"proof.{address}.storageProof"
        )
        storage: dict[str, str] = {}
        for index, raw_storage_proof in enumerate(storage_proofs):
            storage_proof = require_mapping(
                raw_storage_proof, f"proof.{address}.storageProof[{index}]"
            )
            key = normalize_storage_key(
                storage_proof.get("key"),
                f"proof.{address}.storageProof[{index}].key",
            )
            value_path = f"proof.{address}.storageProof[{index}].value"
            value = parse_quantity(storage_proof.get("value"), value_path)
            if value >= 1 << 256:
                raise CaptureError(f"{value_path}: value exceeds 256 bits")
            storage[key] = "0x" + value.to_bytes(32, "big").hex()
        if set(storage) != set(storage_keys):
            raise CaptureError(
                f"proof.{address}: storage proof keys do not match trace"
            )

        if (
            balance == 0
            and nonce == 0
            and code_hash == EMPTY_CODE_HASH
            and storage_root == EMPTY_STORAGE_ROOT
        ):
            absent_accounts.append(address)
            continue
        accounts[address] = {
            "balance": str(balance),
            "nonce": str(nonce),
            "code": code,
            "codeHash": code_hash,
            "storage": storage,
        }
    return {"accounts": accounts, "absentAccounts": absent_accounts}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()


def write_bundle(
    output: Path,
    bundle: CaptureBundle,
    *,
    calls_bytes: bytes,
    monad_commit: str,
    capture_version: str,
    force: bool = False,
    created_at: str | None = None,
) -> None:
    output = output.resolve()
    if output.exists():
        if not force:
            raise CaptureError(f"output already exists: {output}")
        if output.is_dir():
            shutil.rmtree(output)
        else:
            output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest_bytes = canonical_json(bundle.manifest)
    cases_bytes = canonical_json(bundle.cases)
    state_bytes = canonical_json(bundle.state)
    state_compressed = zstandard.ZstdCompressor(
        level=10, write_content_size=True
    ).compress(state_bytes)
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "createdAt": created_at
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "chainId": str(bundle.chain_id),
            "blockNumber": str(bundle.block_number),
            "blockHash": bundle.block_hash,
        },
        "executionEnv": bundle.manifest["chain"]["executionEnv"],
        "monadCommit": monad_commit,
        "captureTool": {
            "name": "monad-execbench-capture",
            "version": capture_version,
        },
        "inputs": {"callsSha256": sha256(calls_bytes)},
        "files": {
            "manifest.json": sha256(manifest_bytes),
            "cases.json": sha256(cases_bytes),
            "state.json.zst": sha256(state_compressed),
            "state.normalized.json": sha256(state_bytes),
        },
    }

    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        (temporary / "cases.json").write_bytes(cases_bytes)
        (temporary / "state.json.zst").write_bytes(state_compressed)
        (temporary / "provenance.json").write_bytes(canonical_json(provenance))
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
