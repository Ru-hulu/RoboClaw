"""Dimos-compatible LCM message declarations for pubOdomSensor.

This module mirrors the small part of dimos' LCM message shape that the
FastLIO-compatible simulation bridge will need. It is declaration-only for now:
the current publisher still uses ``lcm_protocol.py`` and no runtime dependency on
``dimos_lcm`` is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass


REGISTERED_SCAN_STREAM = "registered_scan"
ODOMETRY_STREAM = "odometry"

POINTCLOUD2_TYPE = "sensor_msgs.PointCloud2"
ODOMETRY_TYPE = "nav_msgs.Odometry"

REGISTERED_SCAN_CHANNEL = f"/{REGISTERED_SCAN_STREAM}#{POINTCLOUD2_TYPE}"
ODOMETRY_CHANNEL = f"/{ODOMETRY_STREAM}#{ODOMETRY_TYPE}"


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
