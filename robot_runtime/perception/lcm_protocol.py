"""Shared LCM channels and image payload codec for perception processes."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass


COLOR_IMAGE_CHANNEL = "ROBOCLAW_REALSENSE_COLOR_IMAGE"
DEPTH_IMAGE_CHANNEL = "ROBOCLAW_REALSENSE_DEPTH_IMAGE"
SAM3_REQUEST_CHANNEL = "ROBOCLAW_SAM3_TARGET_POSE_REQUEST"
SAM3_RESPONSE_CHANNEL = "ROBOCLAW_SAM3_TARGET_POSE_RESPONSE"

CAMERA_IMAGE_SCHEMA = "roboclaw.camera_image.v1"
SAM3_REQUEST_SCHEMA = "roboclaw.sam3.target_pose_request.v1"

DECODE_OK = "ok"
ERR_PAYLOAD_TOO_SHORT = "payload_too_short"
ERR_HEADER_TRUNCATED = "header_truncated"
ERR_HEADER_JSON_INVALID = "header_json_invalid"
ERR_HEADER_FIELDS_INVALID = "header_fields_invalid"
ERR_DATA_SIZE_MISMATCH = "data_size_mismatch"
ERR_LAYOUT_SIZE_MISMATCH = "layout_size_mismatch"

_HEADER_LENGTH = struct.Struct("<I")


@dataclass(frozen=True)
class DecodeImageResult:
    state: str
    header: dict[str, object] | None = None
    image_bytes: bytes | None = None


def encode_image_message(
    kind: str,
    metadata: dict[str, object],
    image_bytes: bytes,
) -> bytes:
    header = dict(metadata)
    header.update(
        {
            "schema": CAMERA_IMAGE_SCHEMA,
            "kind": kind,
            "data_size": len(image_bytes),
        }
    )
    header_bytes = json.dumps(
        header,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _HEADER_LENGTH.pack(len(header_bytes)) + header_bytes + image_bytes


def decode_image_message(payload: bytes) -> DecodeImageResult:
    if len(payload) < _HEADER_LENGTH.size:
        return DecodeImageResult(ERR_PAYLOAD_TOO_SHORT)

    header_length = _HEADER_LENGTH.unpack_from(payload, 0)[0]
    header_start = _HEADER_LENGTH.size
    header_end = header_start + header_length
    if len(payload) < header_end:
        return DecodeImageResult(ERR_HEADER_TRUNCATED)

    try:
        header = json.loads(payload[header_start:header_end].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return DecodeImageResult(ERR_HEADER_JSON_INVALID)
    if not isinstance(header, dict):
        return DecodeImageResult(ERR_HEADER_FIELDS_INVALID)

    image_bytes = payload[header_end:]
    try:
        data_size = header["data_size"]
        layout_size = header["height"] * header["step"]
    except (KeyError, TypeError):
        return DecodeImageResult(ERR_HEADER_FIELDS_INVALID, header)
    if len(image_bytes) != data_size:
        return DecodeImageResult(ERR_DATA_SIZE_MISMATCH, header)
    if len(image_bytes) != layout_size:
        return DecodeImageResult(ERR_LAYOUT_SIZE_MISMATCH, header)
    return DecodeImageResult(DECODE_OK, header, image_bytes)
