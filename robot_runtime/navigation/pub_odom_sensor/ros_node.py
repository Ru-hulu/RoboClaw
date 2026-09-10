"""ROS 2 node that pairs each Gazebo lidar frame with current model state."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Sequence

import lcm
import rclpy
from gazebo_msgs.srv import GetEntityState
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2

from robot_runtime.navigation.pub_odom_sensor.constants import (
    BASE_FRAME_ID,
    DEFAULT_ENTITY_STATE_SERVICE,
    DEFAULT_LIDAR_TOPIC,
    DEFAULT_MODEL_NAME,
    ODOM_FRAME_ID,
)
from robot_runtime.navigation.pub_odom_sensor.lcm_protocol import (
    ODOM_SENSOR_CHANNEL,
    encode_odom_sensor_frame,
)


LOOP_HZ = 100.0


class PubOdomSensorNode(Node):
    """Publish one LCM odom/lidar frame for each lidar callback."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        super().__init__("pub_odom_sensor")
        self._model_name = arguments.model_name
        self._entity_state_service = arguments.entity_state_service
        self._lcm_channel = arguments.lcm_channel
        self._lcm = lcm.LCM()
        self._state_client = self.create_client(
            GetEntityState,
            self._entity_state_service,
        )
        self.lidar_received = False
        self.entity_state_received = False
        self.published_count = 0
        self.dropped_lidar_count = 0
        self.last_service_latency_sec: float | None = None
        self.last_error: str | None = None

        self.lidar_subscription = self.create_subscription(
            PointCloud2,
            arguments.lidar_topic,
            self._on_lidar,
            10,
        )

    @property
    def published_first_frame(self) -> bool:
        return self.published_count > 0

    def _on_lidar(self, message: PointCloud2) -> None:
        self.lidar_received = True
        request = GetEntityState.Request()
        request.name = self._model_name
        request.reference_frame = ODOM_FRAME_ID
        started = time.monotonic()
        future = self._state_client.call_async(request)
        future.add_done_callback(
            lambda done_future: self._on_entity_state_response(
                message,
                done_future,
                started,
            )
        )

    def _on_entity_state_response(
        self,
        message: PointCloud2,
        future: object,
        started: float,
    ) -> None:
        response = self._future_result(future)
        if response is None:
            self.dropped_lidar_count += 1
            return
        if not response.success:
            self.last_error = "Gazebo get_entity_state returned success=false."
            self.dropped_lidar_count += 1
            return
        self.last_service_latency_sec = time.monotonic() - started
        self.entity_state_received = True
        metadata = {
            "stamp_sec": int(message.header.stamp.sec),
            "stamp_nanosec": int(message.header.stamp.nanosec),
            "odom": _odom_metadata(self._model_name, response),
            "lidar": _pointcloud_metadata(message),
        }
        self._lcm.publish(
            self._lcm_channel,
            encode_odom_sensor_frame(metadata, bytes(message.data)),
        )
        self.published_count += 1

    def _future_result(self, future: object) -> object | None:
        try:
            error = future.exception()
        except Exception as error:
            self.last_error = str(error)
            return None
        if error is not None:
            self.last_error = str(error)
            return None
        response = future.result()
        if response is None:
            self.last_error = "empty response"
            return None
        self.last_error = None
        return response


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    rclpy.init()
    node: PubOdomSensorNode | None = None
    try:
        node = PubOdomSensorNode(arguments)
        deadline = time.monotonic() + arguments.startup_timeout_sec
        startup_reported = False
        while rclpy.ok():
            if not startup_reported and node.published_first_frame:
                _emit_stdout(
                    {
                        "ok": True,
                        "lidar_received": node.lidar_received,
                        "entity_state_received": node.entity_state_received,
                        "published_count": node.published_count,
                        "dropped_lidar_count": node.dropped_lidar_count,
                        "last_service_latency_sec": node.last_service_latency_sec,
                        "last_error": node.last_error,
                        "lcm_channel": arguments.lcm_channel,
                        "message": "pubOdomSensor published its first odom/lidar frame.",
                    }
                )
                startup_reported = True
            if not startup_reported and time.monotonic() >= deadline:
                _emit_stdout(
                    {
                        "ok": False,
                        "lidar_received": bool(node and node.lidar_received),
                        "entity_state_received": bool(
                            node and node.entity_state_received
                        ),
                        "published_count": 0,
                        "dropped_lidar_count": (
                            node.dropped_lidar_count if node is not None else 0
                        ),
                        "last_service_latency_sec": (
                            node.last_service_latency_sec
                            if node is not None
                            else None
                        ),
                        "last_error": node.last_error if node is not None else None,
                        "lcm_channel": arguments.lcm_channel,
                        "message": (
                            "Timed out before pubOdomSensor produced an "
                            "odom/lidar frame."
                        ),
                    }
                )
                return 1
            rclpy.spin_once(node, timeout_sec=1.0 / LOOP_HZ)
    except (KeyboardInterrupt, ExternalShutdownException):
        return 0
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish Gazebo model state and lidar frames over LCM"
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--entity-state-service", default=DEFAULT_ENTITY_STATE_SERVICE)
    parser.add_argument("--lidar-topic", default=DEFAULT_LIDAR_TOPIC)
    parser.add_argument("--lcm-channel", default=ODOM_SENSOR_CHANNEL)
    parser.add_argument("--startup-timeout-sec", type=_positive_float, required=True)
    return parser.parse_args(argv)


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be a positive finite float")
    return parsed


def _stamp_to_float(stamp: object) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0


def _odom_metadata(model_name: str, response: object) -> dict[str, object]:
    state = response.state
    return {
        "model_name": model_name,
        "frame_id": ODOM_FRAME_ID,
        "child_frame_id": BASE_FRAME_ID,
        "stamp_sec": _stamp_to_float(response.header.stamp),
        "pose": {
            "position": _vector3(state.pose.position),
            "orientation_xyzw": _quaternion(state.pose.orientation),
            "yaw": _yaw_from_quaternion(state.pose.orientation),
        },
        "twist": {
            "linear": _vector3(state.twist.linear),
            "angular": _vector3(state.twist.angular),
        },
    }


def _pointcloud_metadata(message: PointCloud2) -> dict[str, object]:
    return {
        "frame_id": message.header.frame_id,
        "height": int(message.height),
        "width": int(message.width),
        "fields": [
            {
                "name": field.name,
                "offset": int(field.offset),
                "datatype": int(field.datatype),
                "count": int(field.count),
            }
            for field in message.fields
        ],
        "is_bigendian": bool(message.is_bigendian),
        "point_step": int(message.point_step),
        "row_step": int(message.row_step),
        "is_dense": bool(message.is_dense),
    }


def _vector3(value: object) -> dict[str, float]:
    return {
        "x": float(value.x),
        "y": float(value.y),
        "z": float(value.z),
    }


def _quaternion(value: object) -> dict[str, float]:
    return {
        "x": float(value.x),
        "y": float(value.y),
        "z": float(value.z),
        "w": float(value.w),
    }


def _yaw_from_quaternion(value: object) -> float:
    x = float(value.x)
    y = float(value.y)
    z = float(value.z)
    w = float(value.w)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _emit_stdout(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
