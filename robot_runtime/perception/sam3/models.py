"""JSON-friendly request and result contracts for SAM3 image inference."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from .errors import Sam3ErrorCode, Sam3RuntimeError


@dataclass(frozen=True)
class Sam3Request:
    """One validated local-image segmentation request."""

    request_id: str
    image_path: str
    text_prompt: str
    confidence_threshold: float = 0.5

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Sam3Request:
        """Validate and normalize an untrusted JSON request object."""

        request_id_value = payload.get("request_id")
        if not isinstance(request_id_value, str):
            raise _invalid("request_id must be a UUID string.")
        try:
            request_id = str(UUID(request_id_value))
        except (ValueError, AttributeError) as error:
            raise _invalid("request_id must be a valid UUID string.") from error

        image_path_value = payload.get("image_path")
        if not isinstance(image_path_value, str) or not image_path_value.strip():
            raise _invalid("image_path must be a non-empty string.")

        prompt_value = payload.get("text_prompt")
        if not isinstance(prompt_value, str):
            raise _invalid("text_prompt must contain 1 to 256 characters.")
        prompt = prompt_value.strip()
        if not 1 <= len(prompt) <= 256:
            raise _invalid("text_prompt must contain 1 to 256 characters.")

        threshold_value = payload.get("confidence_threshold", 0.5)
        if isinstance(threshold_value, bool) or not isinstance(
            threshold_value, (int, float)
        ):
            raise _invalid("confidence_threshold must be a number.")
        threshold = float(threshold_value)
        if not math.isfinite(threshold):
            raise _invalid("confidence_threshold must be finite.")
        if not 0.0 <= threshold <= 1.0:
            raise _invalid("confidence_threshold must be between 0.0 and 1.0.")

        return cls(
            request_id=request_id,
            image_path=image_path_value.strip(),
            text_prompt=prompt,
            confidence_threshold=threshold,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "image_path": self.image_path,
            "text_prompt": self.text_prompt,
            "confidence_threshold": self.confidence_threshold,
        }


@dataclass(frozen=True)
class Sam3Instance:
    """One scored SAM3 mask and its persisted artifact."""

    index: int
    score: float
    box_xyxy_pixels: tuple[float, float, float, float]
    mask_png_path: str
    mask_area_pixels: int

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "score": self.score,
            "box_xyxy_pixels": list(self.box_xyxy_pixels),
            "mask_png_path": self.mask_png_path,
            "mask_area_pixels": self.mask_area_pixels,
        }


@dataclass(frozen=True)
class Sam3Result:
    """Complete metadata for one atomic SAM3 result directory."""

    request_id: str
    image_path: str
    input_sha256: str
    text_prompt: str
    image_width: int
    image_height: int
    model_revision: str
    checkpoint_sha256: str
    load_duration_ms: float
    inference_duration_ms: float
    instances: tuple[Sam3Instance, ...]
    result_json_path: str
    masks_npz_path: str
    overlay_path: str
    schema_version: int = 1

    @property
    def instance_count(self) -> int:
        return len(self.instances)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "image_path": self.image_path,
            "input_sha256": self.input_sha256,
            "text_prompt": self.text_prompt,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "model_revision": self.model_revision,
            "checkpoint_sha256": self.checkpoint_sha256,
            "load_duration_ms": self.load_duration_ms,
            "inference_duration_ms": self.inference_duration_ms,
            "instance_count": self.instance_count,
            "instances": [instance.to_dict() for instance in self.instances],
            "result_json_path": self.result_json_path,
            "masks_npz_path": self.masks_npz_path,
            "overlay_path": self.overlay_path,
        }


def _invalid(message: str) -> Sam3RuntimeError:
    return Sam3RuntimeError(Sam3ErrorCode.INVALID_INPUT, message)
