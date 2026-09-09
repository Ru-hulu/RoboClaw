"""Estimate object position from a SAM3 mask and a depth frame."""

from __future__ import annotations

import math
from pathlib import Path

from robot_runtime.perception.lcm_protocol import DecodeImageResult


_CAMERA_WIDTH_PX = 640
_CAMERA_HEIGHT_PX = 480
_HORIZONTAL_FOV_RAD = 1.211
_FX_PX = _CAMERA_WIDTH_PX / (2.0 * math.tan(_HORIZONTAL_FOV_RAD / 2.0))
_FY_PX = _FX_PX
_CX_PX = 320.5
_CY_PX = 240.5
_MIN_DEPTH_M = 0.05
_MAX_DEPTH_M = 10.0


def estimate_position_from_mask_depth(
    segment_result: dict[str, object],
    depth_frame: DecodeImageResult,
) -> dict[str, object] | None:
    instance = _best_instance(segment_result.get("instances"))
    if instance is None:
        return None

    mask_index = _read_int(instance, "index")
    masks_path = _read_str(segment_result, "masks_npz_path")
    if mask_index is None or masks_path is None:
        return None

    try:
        import numpy as np

        with np.load(Path(masks_path), allow_pickle=False) as data:
            mask = np.asarray(data["masks"][mask_index], dtype=bool)
        depth, frame_id = _decode_depth_frame(depth_frame)
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        return None

    if mask.shape != depth.shape:
        return None

    rows, cols = np.nonzero(mask)
    if len(rows) == 0:
        return None

    z = depth[rows, cols].astype(np.float64, copy=False)
    valid = np.isfinite(z) & (z >= _MIN_DEPTH_M) & (z <= _MAX_DEPTH_M)
    if not np.any(valid):
        return None

    u = cols[valid].astype(np.float64, copy=False)
    v = rows[valid].astype(np.float64, copy=False)
    z = z[valid]
    x = (u - _CX_PX) * z / _FX_PX
    y = (v - _CY_PX) * z / _FY_PX

    return {
        "frame_id": frame_id,
        "x": float(np.mean(x)),
        "y": float(np.mean(y)),
        "z": float(np.mean(z)),
    }


def _decode_depth_frame(frame: DecodeImageResult):
    import numpy as np

    if frame.header is None or frame.image_bytes is None:
        raise ValueError("depth frame is missing decoded image data")

    header = frame.header
    width = int(header["width"])
    height = int(header["height"])
    step = int(header["step"])
    encoding = str(header["encoding"]).upper()
    frame_id = _read_str(header, "frame_id") or "camera_depth_frame"

    if encoding == "32FC1":
        dtype = np.dtype(">f4" if header.get("is_bigendian") == 1 else "<f4")
        scale = 1.0
    elif encoding == "16UC1":
        dtype = np.dtype(">u2" if header.get("is_bigendian") == 1 else "<u2")
        scale = 0.001
    else:
        raise ValueError("unsupported depth encoding")

    row_values = step // dtype.itemsize
    depth = np.frombuffer(frame.image_bytes, dtype=dtype, count=height * row_values)
    depth = depth.reshape(height, row_values)[:, :width].astype(np.float32)
    if scale != 1.0:
        depth *= scale
    return depth, frame_id


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


def _read_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _read_float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
