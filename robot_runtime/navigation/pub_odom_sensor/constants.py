"""Default pubOdomSensor settings that do not require ROS imports."""

from __future__ import annotations


DEFAULT_MODEL_NAME = "openarm_v20"
DEFAULT_ENTITY_STATE_SERVICE = "/gazebo/get_entity_state"
DEFAULT_LIDAR_TOPIC = "/livox/lidar"

BASE_FRAME_ID = "base_footprint"
ODOM_FRAME_ID = "world"
