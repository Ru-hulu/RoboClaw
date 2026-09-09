"""Pydantic contracts for target object position Tool results."""

from __future__ import annotations

from pydantic import BaseModel


class TargetObjectPosition(BaseModel):
    frame_id: str
    x: float
    y: float
    z: float


class TargetObjectPositionSource(BaseModel):
    segmentation_request_id: str | None
    mask_area_pixels: int | None
    box_xyxy_pixels: list[float] | None
    result_json_path: str | None
    overlay_path: str | None


class TargetObjectPositionResult(BaseModel):
    success: bool
    position_valid: bool
    position: TargetObjectPosition | None
    confidence: float | None
    message: str
    source: TargetObjectPositionSource

