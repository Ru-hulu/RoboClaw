"""FastMCP integration for the Gazebo RealSense RGB-D listener."""

from __future__ import annotations

__all__ = ["register_gazebo_realsense_camera_tool"]


def __getattr__(name: str) -> object:
    if name == "register_gazebo_realsense_camera_tool":
        from .tool import register_gazebo_realsense_camera_tool

        return register_gazebo_realsense_camera_tool
    raise AttributeError(name)
