"""Small JSON request/response helper built on LCM."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from uuid import uuid4

import lcm


DEFAULT_POLL_TIMEOUT_MS = 100


@dataclass(frozen=True)
class LcmRpcRequest:
    request_id: str
    payload: dict[str, object]


class LcmRpcClient:
    """Send one JSON request and wait for the matching JSON response."""

    def __init__(
        self,
        request_channel: str,
        response_channel: str,
        lc: lcm.LCM | None = None,
    ) -> None:
        self._request_channel = request_channel
        self._response_channel = response_channel
        self._lcm = lc if lc is not None else lcm.LCM()
        self._responses: dict[str, dict[str, object]] = {}
        self._lcm.subscribe(response_channel, self._on_response)

    def call(
        self,
        payload: dict[str, object],
        timeout_sec: float,
        poll_timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS,
    ) -> dict[str, object]:
        request_id = str(uuid4())
        request = dict(payload)
        request["request_id"] = request_id
        self._lcm.publish(self._request_channel, _encode_json(request))

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if request_id in self._responses:
                return self._responses.pop(request_id)
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            self._lcm.handle_timeout(min(poll_timeout_ms, remaining_ms))

        raise TimeoutError("LCM RPC response timed out.")

    def _on_response(self, channel: str, payload: bytes) -> None:
        del channel
        message = _decode_json(payload)
        request_id = message.get("request_id")
        if isinstance(request_id, str):
            self._responses[request_id] = message


class LcmRpcServer:
    """Receive JSON requests and publish JSON responses on fixed LCM channels."""

    def __init__(
        self,
        request_channel: str,
        response_channel: str,
        lc: lcm.LCM | None = None,
    ) -> None:
        self._request_channel = request_channel
        self._response_channel = response_channel
        self._lcm = lc if lc is not None else lcm.LCM()
        self._requests: list[LcmRpcRequest] = []
        self._lcm.subscribe(request_channel, self._on_request)

    def poll(self, timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS) -> LcmRpcRequest | None:
        if self._requests:
            return self._requests.pop(0)
        self._lcm.handle_timeout(timeout_ms)
        if self._requests:
            return self._requests.pop(0)
        return None

    def respond(self, request_id: str, payload: dict[str, object]) -> None:
        response = dict(payload)
        response["request_id"] = request_id
        self._lcm.publish(self._response_channel, _encode_json(response))

    def _on_request(self, channel: str, payload: bytes) -> None:
        del channel
        message = _decode_json(payload)
        request_id = message.get("request_id")
        if isinstance(request_id, str):
            self._requests.append(LcmRpcRequest(request_id, message))


def _encode_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _decode_json(payload: bytes) -> dict[str, object]:
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("LCM RPC payload must be a JSON object.")
    return message
