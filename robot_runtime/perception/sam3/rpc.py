"""SAM3-specific RPC contract carried by the shared LCM RPC helper."""

from __future__ import annotations

import math
from dataclasses import dataclass

import lcm

from robot_runtime.ipc.lcm_rpc import LcmRpcClient, LcmRpcRequest, LcmRpcServer


SAM3_RPC_REQUEST_CHANNEL = "ROBOCLAW_SAM3_RPC_REQUEST"
SAM3_RPC_RESPONSE_CHANNEL = "ROBOCLAW_SAM3_RPC_RESPONSE"

SAM3_RPC_METHOD_SEGMENT = "segment"

DEFAULT_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_FRAME_TIMEOUT_SEC = 3.0
DEFAULT_RPC_TIMEOUT_SEC = 10.0

@dataclass(frozen=True)
class Sam3SegmentRequest:
    request_id: str
    text_prompt: str
    confidence_threshold: float
    frame_timeout_sec: float

    @classmethod
    def from_rpc_request(cls, request: LcmRpcRequest) -> Sam3SegmentRequest:
        payload = request.payload
        method = payload.get("method")
        if method != SAM3_RPC_METHOD_SEGMENT:
            raise ValueError("unsupported SAM3 RPC method")

        prompt_value = payload.get("text_prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise ValueError("text_prompt is required")

        return cls(
            request_id=request.request_id,
            text_prompt=prompt_value.strip(),
            confidence_threshold=_read_float(
                payload,
                "confidence_threshold",
                DEFAULT_CONFIDENCE_THRESHOLD,
            ),
            frame_timeout_sec=_read_float(
                payload,
                "frame_timeout_sec",
                DEFAULT_FRAME_TIMEOUT_SEC,
            ),
        )


@dataclass(frozen=True)
class Sam3SegmentResponse:
    ok: bool
    result: dict[str, object] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"ok": self.ok}
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


class Sam3RpcClient:
    """Business-facing client for one SAM3 segmentation request."""

    def __init__(self, lc: lcm.LCM | None = None) -> None:
        self._client = LcmRpcClient(
            SAM3_RPC_REQUEST_CHANNEL,
            SAM3_RPC_RESPONSE_CHANNEL,
            lc,
        )

    def segment(
        self,
        text_prompt: str,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        frame_timeout_sec: float = DEFAULT_FRAME_TIMEOUT_SEC,
        timeout_sec: float = DEFAULT_RPC_TIMEOUT_SEC,
    ) -> dict[str, object]:
        response = self._client.call(
            {
                "method": SAM3_RPC_METHOD_SEGMENT,
                "text_prompt": text_prompt,
                "confidence_threshold": confidence_threshold,
                "frame_timeout_sec": frame_timeout_sec,
            },
            timeout_sec=timeout_sec,
        )
        if response.get("ok") is not True:
            error = response.get("error")
            raise RuntimeError(error if isinstance(error, str) else "SAM3 RPC failed")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("SAM3 RPC response is missing result")
        return result


class Sam3RpcServer:
    """SAM3 service-side wrapper around the generic LCM RPC server."""

    def __init__(self, lc: lcm.LCM | None = None) -> None:
        self._server = LcmRpcServer(
            SAM3_RPC_REQUEST_CHANNEL,
            SAM3_RPC_RESPONSE_CHANNEL,
            lc,
        )

    def poll(self, timeout_ms: int) -> Sam3SegmentRequest | None:
        request = self._server.poll(timeout_ms)
        if request is None:
            return None
        try:
            return Sam3SegmentRequest.from_rpc_request(request)
        except ValueError as error:
            self.respond_error(request.request_id, str(error))
            return None

    def respond_success(
        self,
        request_id: str,
        sam3_result: dict[str, object],
    ) -> None:
        result = dict(sam3_result)
        result.setdefault("position_valid", False)
        result.setdefault("position", None)
        self._server.respond(
            request_id,
            Sam3SegmentResponse(ok=True, result=result).to_dict(),
        )

    def respond_error(self, request_id: str, error: str) -> None:
        self._server.respond(
            request_id,
            Sam3SegmentResponse(ok=False, error=error).to_dict(),
        )


def _read_float(
    payload: dict[str, object],
    key: str,
    default: float,
) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} must be finite")
    return number
