"""Pydantic contracts for SAM3 current-view MCP results."""

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


class Sam3FrameResult(BaseModel):
    """Segmentation result for one captured ROS image frame."""

    frame_index: int = Field(ge=0)
    frame_id: str
    stamp_sec: int
    stamp_nanosec: int = Field(ge=0)
    captured_image_path: str
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    inference_duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    instance_count: int = Field(ge=0)
    instances: list[Sam3InstanceResult]
    result_json_path: str
    masks_npz_path: str
    overlay_path: str

    @model_validator(mode="after")
    def validate_instance_count(self) -> Self:
        if self.instance_count != len(self.instances):
            raise ValueError("instance_count does not match instances.")
        return self


class Sam3CurrentViewResult(BaseModel):
    """Aggregate result for one one-shot current-view segmentation job."""

    ok: Literal[True] = True
    schema_version: Literal[1]
    request_id: str
    image_topic: str
    text_prompt: str
    confidence_threshold: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    requested_frame_count: int = Field(gt=0)
    processed_frame_count: int = Field(ge=0)
    node_pid: int = Field(gt=0)
    worker_pid: int = Field(gt=0)
    model_load_duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    model_revision: str
    checkpoint_sha256: str
    result_json_path: str
    frames: list[Sam3FrameResult]
    best_frame_index: int | None = Field(default=None, ge=0)
    best_instance_index: int | None = Field(default=None, ge=0)
    best_score: float | None = Field(default=None, ge=0.0, le=1.0)
    message: str

    @model_validator(mode="after")
    def validate_frame_count(self) -> Self:
        if self.processed_frame_count != len(self.frames):
            raise ValueError("processed_frame_count does not match frames.")
        if self.processed_frame_count != self.requested_frame_count:
            raise ValueError("processed_frame_count must match requested_frame_count.")
        return self
