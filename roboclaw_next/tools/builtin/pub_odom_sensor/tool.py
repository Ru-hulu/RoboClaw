"""FastMCP contracts for pubOdomSensor process management."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from robot_runtime.navigation.pub_odom_sensor.constants import (
    DEFAULT_ENTITY_STATE_SERVICE,
    DEFAULT_LIDAR_TOPIC,
    DEFAULT_MODEL_NAME,
)
from robot_runtime.navigation.pub_odom_sensor.lcm_protocol import ODOM_SENSOR_CHANNEL

from .models import PubOdomSensorStatusResult
from .program import PubOdomSensorManager


class PubOdomSensorErrorResult(BaseModel):
    """Stable failure result that does not terminate the MCP transport."""

    ok: Literal[False] = False
    message: str


def register_pub_odom_sensor_tools(
    mcp: FastMCP,
    manager: PubOdomSensorManager | None = None,
) -> None:
    """Register pubOdomSensor lifecycle Tools."""

    process_manager = manager or PubOdomSensorManager()

    @mcp.tool(
        name="start_pub_odom_sensor",
        title="Start pubOdomSensor",
        description=(
            "Start the ROS node that listens to Livox PointCloud2 lidar frames. "
            "For each lidar frame, the node immediately calls Gazebo's "
            "GetEntityState service for the model ground-truth pose and "
            "publishes one odom/lidar frame over LCM. This tool returns after "
            "the node publishes its first LCM frame."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def start_pub_odom_sensor(
        model_name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=128,
                description="Gazebo model name to extract from model_states.",
            ),
        ] = DEFAULT_MODEL_NAME,
        entity_state_service: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="ROS gazebo_msgs/srv/GetEntityState service.",
            ),
        ] = DEFAULT_ENTITY_STATE_SERVICE,
        lidar_topic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="ROS sensor_msgs/msg/PointCloud2 lidar topic.",
            ),
        ] = DEFAULT_LIDAR_TOPIC,
        lcm_channel: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="LCM channel for aligned odom/lidar frames.",
            ),
        ] = ODOM_SENSOR_CHANNEL,
        startup_timeout_sec: Annotated[
            float,
            Field(
                gt=0.0,
                le=60.0,
                allow_inf_nan=False,
                description="Maximum seconds to wait for the first aligned frame.",
            ),
        ] = 10.0,
    ) -> PubOdomSensorStatusResult | PubOdomSensorErrorResult:
        try:
            return await process_manager.start(
                model_name=model_name,
                entity_state_service=entity_state_service,
                lidar_topic=lidar_topic,
                lcm_channel=lcm_channel,
                startup_timeout_sec=startup_timeout_sec,
            )
        except (OSError, TimeoutError, ValueError) as error:
            return PubOdomSensorErrorResult(message=str(error))

    @mcp.tool(
        name="get_pub_odom_sensor_status",
        title="Get pubOdomSensor Status",
        description="Read the current pubOdomSensor process state.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_pub_odom_sensor_status() -> PubOdomSensorStatusResult:
        return await process_manager.get_status()

    @mcp.tool(
        name="stop_pub_odom_sensor",
        title="Stop pubOdomSensor",
        description="Stop the active pubOdomSensor ROS node.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_pub_odom_sensor() -> PubOdomSensorStatusResult:
        return await process_manager.stop()
