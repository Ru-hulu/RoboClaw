"""Business logic for querying target object position from SAM3 segmentation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .models import (
    TargetObjectPosition,
    TargetObjectPositionResult,
    TargetObjectPositionSource,
)


class SegmentClient(Protocol):
    def segment(self, text_prompt: str) -> dict[str, object]: ...


class TargetObjectPositionResolver:
    """Call SAM3 RPC and adapt the segmentation result to a position-shaped result."""

    def __init__(
        self,
        client_factory: Callable[[], SegmentClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory

    def get_position(self, prompt: str) -> TargetObjectPositionResult:
        text_prompt = prompt.strip()
        if not text_prompt:
            return _failure("prompt cannot be blank.")

        try:
            segment_result = self._client_factory().segment(text_prompt)
        except Exception as error:
            return _failure(str(error))

        best_instance = _best_instance(segment_result.get("instances"))
        confidence = _read_float(best_instance, "score") if best_instance else None
        position = _read_position(segment_result.get("position"))
        source = TargetObjectPositionSource(
            segmentation_request_id=_read_str(segment_result, "request_id"),
            mask_area_pixels=_read_int(best_instance, "mask_area_pixels"),
            box_xyxy_pixels=_read_box(best_instance),
            result_json_path=_read_str(segment_result, "result_json_path"),
            overlay_path=_read_str(segment_result, "overlay_path"),
        )
        if best_instance is None:
            message = "SAM3 RPC succeeded, but no target instances were returned."
        elif position is None:
            message = (
                "SAM3 segmentation succeeded, but target position was not returned."
            )
        else:
            message = "Target position estimated from SAM3 mask and depth."

        return TargetObjectPositionResult(
            success=True,
            position_valid=position is not None,
            position=position,
            confidence=confidence,
            message=message,
            source=source,
        )


def _default_client_factory() -> SegmentClient:
    from robot_runtime.perception.sam3.rpc import Sam3RpcClient

    return Sam3RpcClient()


def _failure(message: str) -> TargetObjectPositionResult:
    return TargetObjectPositionResult(
        success=False,
        position_valid=False,
        position=None,
        confidence=None,
        message=message,
        source=TargetObjectPositionSource(
            segmentation_request_id=None,
            mask_area_pixels=None,
            box_xyxy_pixels=None,
            result_json_path=None,
            overlay_path=None,
        ),
    )


def _best_instance(value: object) -> dict[str, object] | None:
    if not isinstance(value, list):
        return None
    candidates = [item for item in value if isinstance(item, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _read_float(item, "score") or 0.0)


def _read_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _read_int(payload: dict[str, object] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _read_float(payload: dict[str, object] | None, key: str) -> float | None:
    if payload is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _read_box(payload: dict[str, object] | None) -> list[float] | None:
    if payload is None:
        return None
    value = payload.get("box_xyxy_pixels")
    if not isinstance(value, list) or len(value) != 4:
        return None
    box: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        box.append(float(item))
    return box


def _read_position(value: object) -> TargetObjectPosition | None:
    if not isinstance(value, dict):
        return None
    frame_id = _read_str(value, "frame_id")
    x = _read_float(value, "x")
    y = _read_float(value, "y")
    z = _read_float(value, "z")
    if frame_id is None or x is None or y is None or z is None:
        return None
    return TargetObjectPosition(frame_id=frame_id, x=x, y=y, z=z)
