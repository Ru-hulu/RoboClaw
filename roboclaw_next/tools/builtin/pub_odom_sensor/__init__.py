"""pubOdomSensor tool package."""

from __future__ import annotations

__all__ = ["register_pub_odom_sensor_tools"]


def __getattr__(name: str):
    if name == "register_pub_odom_sensor_tools":
        from .tool import register_pub_odom_sensor_tools

        return register_pub_odom_sensor_tools
    raise AttributeError(name)
