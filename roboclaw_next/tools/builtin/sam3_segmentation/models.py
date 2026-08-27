"""Shared Pydantic contracts for SAM3 worker and MCP results."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class Sam3InstanceResult(BaseModel):
    """One scored mask artifact returned by SAM3."""

    index: int = Field(ge=0, description="Zero-based instance index.")
    score: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description="SAM3 confidence score.",
    )
    box_xyxy_pixels: list[float] = Field(
        min_length=4,
        max_length=4,
        description="Pixel box [x0, y0, x1, y1] clamped to image bounds.",
    )
    mask_png_path: str = Field(description="Absolute path to the binary mask PNG.")
    mask_area_pixels: int = Field(
        ge=0,
        description="Foreground area of the mask in pixels.",
    )


class Sam3SegmentationResult(BaseModel):
    """Compact metadata and artifact paths for one successful inference."""

    ok: Literal[True] = True
    schema_version: Literal[1]
    request_id: str
    image_path: str
    input_sha256: str
    text_prompt: str
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    model_revision: str
    checkpoint_sha256: str
    load_duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    inference_duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    instance_count: int = Field(ge=0)
    instances: list[Sam3InstanceResult]
    result_json_path: str
    masks_npz_path: str
    overlay_path: str
    worker_pid: int = Field(gt=0)
    model_load_duration_ms: float = Field(ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_instance_count(self) -> Self:
        if self.instance_count != len(self.instances):
            raise ValueError("instance_count does not match instances.")
        return self
