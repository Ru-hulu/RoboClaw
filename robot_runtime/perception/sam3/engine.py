"""Image validation, output normalization, and atomic SAM3 artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError

from .config import Sam3RuntimeConfig
from .errors import Sam3ErrorCode, Sam3RuntimeError
from .models import Sam3Instance, Sam3Request, Sam3Result


SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_IMAGE_FILE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_OVERLAY_COLORS = (
    (255, 99, 71),
    (0, 191, 255),
    (50, 205, 50),
    (255, 215, 0),
    (186, 85, 211),
    (255, 140, 0),
)


@dataclass(frozen=True)
class BackendOutput:
    """Raw arrays returned by a SAM3 image backend."""

    masks: np.ndarray
    boxes: np.ndarray
    scores: np.ndarray


class Sam3BackendProtocol(Protocol):
    """Minimal model boundary used by the engine and CPU-only tests."""

    def load(self) -> float:
        """Load the model once and return elapsed milliseconds."""

    def infer(
        self,
        image: Image.Image,
        text_prompt: str,
        confidence_threshold: float,
    ) -> tuple[BackendOutput, float]:
        """Run one request and return raw output plus elapsed milliseconds."""


class Sam3Engine:
    """Run validated image inference and publish complete result directories."""

    def __init__(
        self,
        config: Sam3RuntimeConfig,
        backend: Sam3BackendProtocol,
    ) -> None:
        self._config = config
        self._backend = backend
        self._load_duration_ms: float | None = None

    def load(self) -> float:
        """Load the backend at most once for this worker process."""

        if self._load_duration_ms is None:
            duration = float(self._backend.load())
            if not math.isfinite(duration) or duration < 0:
                raise Sam3RuntimeError(
                    Sam3ErrorCode.MODEL_UNAVAILABLE,
                    "SAM3 backend returned an invalid model load duration.",
                )
            self._load_duration_ms = duration
        return self._load_duration_ms

    def infer(self, request: Sam3Request) -> Sam3Result:
        """Run one inference and atomically write its artifacts."""

        load_duration_ms = self.load()
        image_path, image, input_sha256 = self._load_image(request.image_path)
        raw_output, inference_duration_ms = self._backend.infer(
            image,
            request.text_prompt,
            request.confidence_threshold,
        )
        if not math.isfinite(inference_duration_ms) or inference_duration_ms < 0:
            raise Sam3RuntimeError(
                Sam3ErrorCode.MODEL_UNAVAILABLE,
                "SAM3 backend returned an invalid inference duration.",
            )
        masks, boxes, scores = self._normalize_output(
            raw_output,
            image.width,
            image.height,
            request.confidence_threshold,
        )
        return self._write_artifacts(
            request=request,
            image_path=image_path,
            image=image,
            input_sha256=input_sha256,
            masks=masks,
            boxes=boxes,
            scores=scores,
            load_duration_ms=load_duration_ms,
            inference_duration_ms=float(inference_duration_ms),
        )

    def _load_image(self, requested_path: str) -> tuple[Path, Image.Image, str]:
        try:
            path = Path(requested_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise _invalid_input(f"Image does not exist: {requested_path}") from error
        if not path.is_file():
            raise _invalid_input(f"Image is not a regular file: {path}")
        if not any(
            path.is_relative_to(root.resolve()) for root in self._config.input_roots
        ):
            raise _invalid_input(
                f"Image is outside the configured allowed input roots: {path}"
            )
        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise _invalid_input(
                "Image must use a supported image extension: .jpg, .jpeg, .png, or .webp."
            )
        try:
            size = path.stat().st_size
        except OSError as error:
            raise _invalid_input(f"Cannot read image metadata: {path}") from error
        if size > MAX_IMAGE_FILE_BYTES:
            raise _invalid_input("Image file exceeds the 50 MiB limit.")

        try:
            with Image.open(path) as candidate:
                width, height = candidate.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise _invalid_input(
                        "Decoded image exceeds the 40 million pixel limit."
                    )
                candidate.verify()
            with Image.open(path) as candidate:
                image = candidate.convert("RGB")
                image.load()
        except Sam3RuntimeError:
            raise
        except (OSError, ValueError, UnidentifiedImageError) as error:
            raise _invalid_input(f"Image could not be decoded: {path}") from error

        return path, image, _sha256_file(path)

    def _normalize_output(
        self,
        output: BackendOutput,
        width: int,
        height: int,
        confidence_threshold: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        masks = np.asarray(output.masks)
        if masks.ndim == 4 and masks.shape[1] == 1:
            masks = masks[:, 0, :, :]
        if masks.ndim != 3 or masks.shape[1:] != (height, width):
            raise _invalid_input(
                "SAM3 masks must have shape (N, H, W) matching the input image."
            )
        boxes = np.asarray(output.boxes, dtype=np.float64)
        scores = np.asarray(output.scores, dtype=np.float64)
        if boxes.ndim != 2 or boxes.shape[1:] != (4,):
            raise _invalid_input("SAM3 boxes must have shape (N, 4).")
        if scores.ndim != 1:
            raise _invalid_input("SAM3 scores must have shape (N,).")
        if not (len(masks) == len(boxes) == len(scores)):
            raise _invalid_input(
                "SAM3 masks, boxes, and scores must contain the same number of instances."
            )
        if not np.isfinite(boxes).all() or not np.isfinite(scores).all():
            raise _invalid_input("SAM3 boxes and scores must contain finite values.")

        selected = np.flatnonzero(scores >= confidence_threshold)
        if len(selected):
            selected = selected[
                np.argsort(-scores[selected], kind="stable")
            ]
        masks = masks[selected].astype(bool, copy=False)
        boxes = boxes[selected].copy()
        scores = scores[selected].copy()
        if len(boxes):
            boxes[:, (0, 2)] = np.clip(boxes[:, (0, 2)], 0.0, float(width - 1))
            boxes[:, (1, 3)] = np.clip(boxes[:, (1, 3)], 0.0, float(height - 1))
        return masks, boxes, scores

    def _write_artifacts(
        self,
        *,
        request: Sam3Request,
        image_path: Path,
        image: Image.Image,
        input_sha256: str,
        masks: np.ndarray,
        boxes: np.ndarray,
        scores: np.ndarray,
        load_duration_ms: float,
        inference_duration_ms: float,
    ) -> Sam3Result:
        output_root = self._config.output_root
        final_directory = output_root / request.request_id
        if final_directory.exists():
            raise Sam3RuntimeError(
                Sam3ErrorCode.OUTPUT_EXISTS,
                f"SAM3 result already exists for request_id {request.request_id}.",
            )
        temporary_directory = output_root / (
            f".{request.request_id}.{uuid4().hex}.tmp"
        )

        try:
            output_root.mkdir(parents=True, exist_ok=True)
            if final_directory.exists():
                raise Sam3RuntimeError(
                    Sam3ErrorCode.OUTPUT_EXISTS,
                    f"SAM3 result already exists for request_id {request.request_id}.",
                )
            temporary_directory.mkdir()
            np.savez_compressed(temporary_directory / "masks.npz", masks=masks)

            instances: list[Sam3Instance] = []
            for index, (mask, box, score) in enumerate(zip(masks, boxes, scores)):
                filename = f"mask_{index:03d}.png"
                Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(
                    temporary_directory / filename,
                    format="PNG",
                )
                instances.append(
                    Sam3Instance(
                        index=index,
                        score=float(score),
                        box_xyxy_pixels=tuple(float(value) for value in box),
                        mask_png_path=str(final_directory / filename),
                        mask_area_pixels=int(mask.sum()),
                    )
                )

            overlay = _render_overlay(image, masks, boxes)
            overlay.save(temporary_directory / "overlay.png", format="PNG")
            result = Sam3Result(
                request_id=request.request_id,
                image_path=str(image_path),
                input_sha256=input_sha256,
                text_prompt=request.text_prompt,
                image_width=image.width,
                image_height=image.height,
                model_revision=self._config.source_revision,
                checkpoint_sha256=self._config.checkpoint_sha256,
                load_duration_ms=load_duration_ms,
                inference_duration_ms=inference_duration_ms,
                instances=tuple(instances),
                result_json_path=str(final_directory / "result.json"),
                masks_npz_path=str(final_directory / "masks.npz"),
                overlay_path=str(final_directory / "overlay.png"),
            )
            (temporary_directory / "result.json").write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary_directory.replace(final_directory)
            return result
        except Sam3RuntimeError:
            _remove_temporary_directory(temporary_directory)
            raise
        except (OSError, ValueError) as error:
            _remove_temporary_directory(temporary_directory)
            raise Sam3RuntimeError(
                Sam3ErrorCode.OUTPUT_WRITE_FAILED,
                f"Failed to write SAM3 result artifacts for request_id {request.request_id}.",
            ) from error


def _render_overlay(
    image: Image.Image,
    masks: np.ndarray,
    boxes: np.ndarray,
) -> Image.Image:
    pixels = np.asarray(image, dtype=np.uint8).copy()
    for index, mask in enumerate(masks):
        color = np.asarray(_OVERLAY_COLORS[index % len(_OVERLAY_COLORS)])
        pixels[mask] = (
            pixels[mask].astype(np.float32) * 0.55 + color.astype(np.float32) * 0.45
        ).astype(np.uint8)
    overlay = Image.fromarray(pixels, mode="RGB")
    draw = ImageDraw.Draw(overlay)
    for index, box in enumerate(boxes):
        draw.rectangle(
            tuple(float(value) for value in box),
            outline=_OVERLAY_COLORS[index % len(_OVERLAY_COLORS)],
            width=2,
        )
    return overlay


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_temporary_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _invalid_input(message: str) -> Sam3RuntimeError:
    return Sam3RuntimeError(Sam3ErrorCode.INVALID_INPUT, message)
