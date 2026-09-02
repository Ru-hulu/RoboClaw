"""ROS 2 node that listens to Gazebo RealSense RGB-D streams."""

from __future__ import annotations

import argparse
import json
import struct
import time
from collections.abc import Sequence

import lcm
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


LOOP_HZ = 30.0
COLOR_LCM_CHANNEL = "ROBOCLAW_REALSENSE_COLOR_IMAGE"
DEPTH_LCM_CHANNEL = "ROBOCLAW_REALSENSE_DEPTH_IMAGE"
_HEADER_LENGTH = struct.Struct("<I")


class GazeboRealsenseLcmBridgeNode(Node):
    """Subscribe to Gazebo RealSense image streams and relay them over LCM."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        super().__init__("gazebo_realsense_lcm_bridge")
        self._lcm = lcm.LCM()
        self.color_received = False
        self.depth_received = False
        self.color_subscription = self.create_subscription(
            Image,
            arguments.color_image_topic,
            self._on_color,
            10,
        )
        self.depth_subscription = self.create_subscription(
            Image,
            arguments.depth_image_topic,
            self._on_depth,
            10,
        )

    @property
    def received_first_message(self) -> bool:
        return self.color_received or self.depth_received

    def _on_color(self, message: Image) -> None:
        self.color_received = True
        self._lcm.publish(COLOR_LCM_CHANNEL, _encode_image_message("color", message))

    def _on_depth(self, message: Image) -> None:
        self.depth_received = True
        self._lcm.publish(DEPTH_LCM_CHANNEL, _encode_image_message("depth", message))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    rclpy.init()
    node: GazeboRealsenseLcmBridgeNode | None = None
    try:
        node = GazeboRealsenseLcmBridgeNode(arguments)
        deadline = time.monotonic() + arguments.frame_timeout_sec
        startup_reported = False
        rate = node.create_rate(LOOP_HZ)
        while rclpy.ok():
            if not startup_reported and node.received_first_message:
                _emit_stdout(
                    {
                        "ok": True,
                        "color_image_received": node.color_received,
                        "depth_image_received": node.depth_received,
                        "color_lcm_channel": COLOR_LCM_CHANNEL,
                        "depth_lcm_channel": DEPTH_LCM_CHANNEL,
                        "message": "Gazebo RealSense node received its first image message.",
                    }
                )
                startup_reported = True
            if not startup_reported and time.monotonic() >= deadline:
                _emit_stdout(
                    {
                        "ok": False,
                        "color_image_received": False,
                        "depth_image_received": False,
                        "message": "Timed out before Gazebo RealSense produced an image message.",
                    }
                )
                return 1
            rclpy.spin_once(node, timeout_sec=0.0)
            rate.sleep()
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge Gazebo RealSense RGB-D images to LCM"
    )
    parser.add_argument("--color-image-topic", required=True)
    parser.add_argument("--depth-image-topic", required=True)
    parser.add_argument("--frame-timeout-sec", type=float, required=True)
    return parser.parse_args(argv)


def _encode_image_message(kind: str, message: Image) -> bytes:
    header = {
        "schema": "roboclaw.camera_image.v1",
        "kind": kind,
        "frame_id": message.header.frame_id,
        "stamp_sec": int(message.header.stamp.sec),
        "stamp_nanosec": int(message.header.stamp.nanosec),
        "height": int(message.height),
        "width": int(message.width),
        "encoding": message.encoding,
        "is_bigendian": int(message.is_bigendian),
        "step": int(message.step),
        "data_size": len(message.data),
    }
    header_bytes = json.dumps(
        header,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _HEADER_LENGTH.pack(len(header_bytes)) + header_bytes + bytes(message.data)


def _emit_stdout(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

if __name__ == "__main__":
    raise SystemExit(main())
