"""Pydantic contracts for Gazebo RealSense camera node tools."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class GazeboRealsenseCameraState(str, Enum):
    """Lifecycle state for the Gazebo RealSense listener process."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class GazeboRealsenseCameraStatusResult(BaseModel):
    """Current Gazebo RealSense listener process state."""

    state: GazeboRealsenseCameraState
    pid: int | None
    return_code: int | None
    color_image_topic: str | None
    depth_image_topic: str | None
    color_image_received: bool
    depth_image_received: bool
    message: str
