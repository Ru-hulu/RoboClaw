"""Pydantic contracts for pubOdomSensor tools."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PubOdomSensorState(str, Enum):
    """Lifecycle state for the pubOdomSensor process."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class PubOdomSensorStatusResult(BaseModel):
    """Current pubOdomSensor process state."""

    state: PubOdomSensorState = Field(description="Current process state.")
    pid: int | None = Field(default=None, description="Operating system process ID.")
    return_code: int | None = Field(
        default=None,
        description="Process return code after it exits.",
    )
    model_name: str | None = Field(default=None, description="Gazebo model name.")
    entity_state_service: str | None = Field(
        default=None,
        description="ROS gazebo_msgs/srv/GetEntityState service.",
    )
    lidar_topic: str | None = Field(
        default=None,
        description="ROS sensor_msgs/msg/PointCloud2 lidar topic.",
    )
    lcm_channel: str | None = Field(default=None, description="LCM publish channel.")
    lidar_received: bool = Field(
        default=False,
        description="Whether the node received lidar frames at startup.",
    )
    entity_state_received: bool = Field(
        default=False,
        description="Whether the node received Gazebo entity state at startup.",
    )
    published_count: int = Field(
        default=0,
        description="Aligned frames published before startup returned.",
    )
    dropped_lidar_count: int = Field(
        default=0,
        description="Lidar frames dropped before startup returned.",
    )
    last_service_latency_sec: float | None = Field(
        default=None,
        description="Most recent Gazebo state service latency reported at startup.",
    )
    last_error: str | None = Field(
        default=None,
        description="Most recent frame processing error reported by the ROS node.",
    )
    message: str = Field(description="Human-readable lifecycle information.")
