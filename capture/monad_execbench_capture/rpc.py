from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any


class RpcError(RuntimeError):
    pass


class RpcClient:
    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._next_id = 1

    def call(self, method: str, params: Sequence[Any]) -> Any:
        request_id = self._allocate_id()
        response = self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise RpcError(f"{method} returned an invalid JSON-RPC response")
        return self._result(method, response)

    def batch(self, method: str, params: Sequence[Sequence[Any]]) -> list[Any]:
        requests: list[dict[str, Any]] = []
        request_ids: list[int] = []
        for item in params:
            request_id = self._allocate_id()
            request_ids.append(request_id)
            requests.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": item,
                }
            )
        if not requests:
            return []

        response = self._send(requests)
        if not isinstance(response, list):
            raise RpcError(f"{method} returned an invalid JSON-RPC batch response")
        by_id = {item.get("id"): item for item in response if isinstance(item, dict)}
        results: list[Any] = []
        for request_id in request_ids:
            item = by_id.get(request_id)
            if item is None:
                raise RpcError(f"{method} omitted JSON-RPC response {request_id}")
            results.append(self._result(method, item))
        return results

    def _allocate_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _send(self, payload: object) -> Any:
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RpcError(f"JSON-RPC transport failed: {error}") from error

    @staticmethod
    def _result(method: str, response: dict[str, Any]) -> Any:
        error = response.get("error")
        if error is not None:
            if isinstance(error, dict):
                code = error.get("code", "unknown")
                message = error.get("message", "unknown error")
                raise RpcError(f"{method} failed ({code}): {message}")
            raise RpcError(f"{method} failed: {error}")
        if "result" not in response:
            raise RpcError(f"{method} response has no result")
        return response["result"]
