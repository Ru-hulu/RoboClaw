"""Dimos-compatible LCM message declarations and encoders for pubOdomSensor.

This module mirrors the small part of dimos' generated LCM message shape that
the FastLIO-compatible simulation bridge needs. It does not depend on the
``dimos_lcm`` package at runtime.
"""

from __future__ import annotations

from io import BytesIO
import struct
from dataclasses import dataclass
from typing import Any


REGISTERED_SCAN_STREAM = "registered_scan"
ODOMETRY_STREAM = "odometry"

POINTCLOUD2_TYPE = "sensor_msgs.PointCloud2"
ODOMETRY_TYPE = "nav_msgs.Odometry"

REGISTERED_SCAN_CHANNEL = f"/{REGISTERED_SCAN_STREAM}#{POINTCLOUD2_TYPE}"
ODOMETRY_CHANNEL = f"/{ODOMETRY_STREAM}#{ODOMETRY_TYPE}"

_UINT64_MASK = 0xFFFFFFFFFFFFFFFF
_TIME_HASH_BASE = 0xDE1D24A3A8ECB648
_HEADER_HASH_BASE = 0xDBB33F5B4C19B8EA
_POINT_FIELD_HASH_BASE = 0x702E0E03F04285D7
_POINTCLOUD2_HASH_BASE = 0xEABE7183C4D74215


def _rotate_left_one(value: int) -> int:
    return (((value << 1) & _UINT64_MASK) + (value >> 63)) & _UINT64_MASK


_TIME_FINGERPRINT = _rotate_left_one(_TIME_HASH_BASE)
_HEADER_FINGERPRINT = _rotate_left_one((_HEADER_HASH_BASE + _TIME_FINGERPRINT) & _UINT64_MASK)
_POINT_FIELD_FINGERPRINT = _rotate_left_one(_POINT_FIELD_HASH_BASE)
_POINTCLOUD2_FINGERPRINT = _rotate_left_one(
    (_POINTCLOUD2_HASH_BASE + _HEADER_FINGERPRINT + _POINT_FIELD_FINGERPRINT)
    & _UINT64_MASK
)


@dataclass(frozen=True)
class DimosLcmTopic:
    stream: str
    message_type: str
    channel: str


@dataclass(frozen=True)
class Time:
    sec: int
    nsec: int


@dataclass(frozen=True)
class Header:
    seq: int
    stamp: Time
    frame_id: str


@dataclass(frozen=True)
class PointField:
    name: str
    offset: int
    datatype: int
    count: int


@dataclass(frozen=True)
class PointCloud2Message:
    header: Header
    height: int
    width: int
    fields: tuple[PointField, ...]
    is_bigendian: bool
    point_step: int
    row_step: int
    data: bytes
    is_dense: bool


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True)
class Pose:
    position: Vector3
    orientation: Quaternion


@dataclass(frozen=True)
class Twist:
    linear: Vector3
    angular: Vector3


@dataclass(frozen=True)
class OdometryMessage:
    header: Header
    child_frame_id: str
    pose: Pose
    twist: Twist


REGISTERED_SCAN_TOPIC = DimosLcmTopic(
    stream=REGISTERED_SCAN_STREAM,
    message_type=POINTCLOUD2_TYPE,
    channel=REGISTERED_SCAN_CHANNEL,
)
ODOMETRY_TOPIC = DimosLcmTopic(
    stream=ODOMETRY_STREAM,
    message_type=ODOMETRY_TYPE,
    channel=ODOMETRY_CHANNEL,
)


def ros_pointcloud2_to_dimos_lcm_message(message: Any) -> PointCloud2Message:
    """Map a ROS ``sensor_msgs/msg/PointCloud2`` object to the local LCM shape."""
    return PointCloud2Message(
        header=Header(
            seq=0,
            stamp=Time(
                sec=int(message.header.stamp.sec),
                nsec=int(message.header.stamp.nanosec),
            ),
            frame_id=str(message.header.frame_id),
        ),
        height=int(message.height),
        width=int(message.width),
        fields=tuple(
            PointField(
                name=str(field.name),
                offset=int(field.offset),
                datatype=int(field.datatype),
                count=int(field.count),
            )
            for field in message.fields
        ),
        is_bigendian=bool(message.is_bigendian),
        point_step=int(message.point_step),
        row_step=int(message.row_step),
        data=bytes(message.data),
        is_dense=bool(message.is_dense),
    )


def encode_dimos_pointcloud2_lcm(message: PointCloud2Message) -> bytes:
    """Encode ``PointCloud2Message`` using dimos_lcm's generated wire layout."""
    buffer = BytesIO()
    buffer.write(struct.pack(">Q", _POINTCLOUD2_FINGERPRINT))

    buffer.write(struct.pack(">ii", len(message.fields), len(message.data)))
    buffer.write(struct.pack(">i", message.header.seq))
    buffer.write(
        struct.pack(">ii", message.header.stamp.sec, message.header.stamp.nsec)
    )
    frame_id = message.header.frame_id.encode("utf-8")
    buffer.write(struct.pack(">I", len(frame_id) + 1))
    buffer.write(frame_id)
    buffer.write(b"\0")

    buffer.write(struct.pack(">ii", message.height, message.width))
    for field in message.fields:
        name = field.name.encode("utf-8")
        buffer.write(struct.pack(">I", len(name) + 1))
        buffer.write(name)
        buffer.write(b"\0")
        buffer.write(struct.pack(">iBi", field.offset, field.datatype, field.count))

    buffer.write(
        struct.pack(
            ">bii",
            1 if message.is_bigendian else 0,
            message.point_step,
            message.row_step,
        )
    )
    buffer.write(message.data)
    buffer.write(struct.pack(">b", 1 if message.is_dense else 0))
    return buffer.getvalue()
