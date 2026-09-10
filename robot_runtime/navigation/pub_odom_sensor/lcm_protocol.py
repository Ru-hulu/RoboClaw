"""LCM channel and payload codec for aligned Gazebo odometry/lidar frames."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass


ODOM_SENSOR_CHANNEL = "ROBOCLAW_ODOM_SENSOR_FRAME"
ODOM_SENSOR_SCHEMA = "roboclaw.odom_sensor_frame.v1"

DECODE_OK = "ok"
ERR_PAYLOAD_TOO_SHORT = "payload_too_short"
ERR_HEADER_TRUNCATED = "header_truncated"
ERR_HEADER_JSON_INVALID = "header_json_invalid"
ERR_HEADER_FIELDS_INVALID = "header_fields_invalid"
ERR_DATA_SIZE_MISMATCH = "data_size_mismatch"

_HEADER_LENGTH = struct.Struct("<I")


@dataclass(frozen=True)
class DecodeOdomSensorResult:
    state: str
    header: dict[str, object] | None = None
    pointcloud_bytes: bytes | None = None


def encode_odom_sensor_frame(
    metadata: dict[str, object],
    pointcloud_bytes: bytes,
) -> bytes:
    header = dict(metadata)
    header.update(
        {
            "schema": ODOM_SENSOR_SCHEMA,
            "pointcloud_data_size": len(pointcloud_bytes),
        }
    )
    header_bytes = json.dumps(
        header,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _HEADER_LENGTH.pack(len(header_bytes)) + header_bytes + pointcloud_bytes


def decode_odom_sensor_frame(payload: bytes) -> DecodeOdomSensorResult:
    if len(payload) < _HEADER_LENGTH.size:
        return DecodeOdomSensorResult(ERR_PAYLOAD_TOO_SHORT)

    header_length = _HEADER_LENGTH.unpack_from(payload, 0)[0]
    header_start = _HEADER_LENGTH.size
    header_end = header_start + header_length
    if len(payload) < header_end:
        return DecodeOdomSensorResult(ERR_HEADER_TRUNCATED)

    try:
        header = json.loads(payload[header_start:header_end].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return DecodeOdomSensorResult(ERR_HEADER_JSON_INVALID)
    if not isinstance(header, dict):
        return DecodeOdomSensorResult(ERR_HEADER_FIELDS_INVALID)

    pointcloud_bytes = payload[header_end:]
    data_size = header.get("pointcloud_data_size")
    if not isinstance(data_size, int):
        return DecodeOdomSensorResult(ERR_HEADER_FIELDS_INVALID, header)
    if len(pointcloud_bytes) != data_size:
        return DecodeOdomSensorResult(ERR_DATA_SIZE_MISMATCH, header)
    return DecodeOdomSensorResult(DECODE_OK, header, pointcloud_bytes)
