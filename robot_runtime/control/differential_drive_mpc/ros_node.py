"""Minimal ROS 2 node that runs MPC from external posture feedback."""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from rclpy.node import Node

from robot_runtime.debug.rviz_path import DebugPathPublisher

from .controller import (
    DifferentialDriveMPC,
    MPCConfig,
    Pose2D,
    WheelCommand,
)
from .reference_path import (
    DEFAULT_REFERENCE_LINEAR_SPEED,
    load_hybrid_astar_reference_path,
)


class DifferentialDriveMPCNode(Node):
    """Publish MPC commands using posture feedback from another ROS node."""

    def __init__(self) -> None:
        super().__init__("differential_drive_mpc")

        self.config = MPCConfig()
        self.controller = DifferentialDriveMPC(self.config)
        self.current_pose: Pose2D | None = None
        self.declare_parameter("reference_path_file", "")
        reference_path_file = (
            self.get_parameter("reference_path_file")
            .get_parameter_value()
            .string_value
            .strip()
        )
        if not reference_path_file:
            raise ValueError(
                "reference_path_file is required. Run Hybrid A* first or pass "
                "a Hybrid A* JSON path with "
                "--ros-args -p reference_path_file:=..."
            )
        reference_path = load_hybrid_astar_reference_path(
            reference_path_file,
            step_distance=DEFAULT_REFERENCE_LINEAR_SPEED * self.config.dt,
        )
        self.reference_path = list(reference_path.poses)
        self.reference_path_source = reference_path.source
        self.path_steps = max(1, len(self.reference_path) - 1)
        self.debug_reference_path_poses = tuple(
            (pose.x, pose.y, pose.yaw)
            for pose in self.reference_path[: self.path_steps + 1]
        )
        self.step_index = 0
        self.finished = False

        self.posture_subscription = self.create_subscription(
            PoseStamped,
            "/robot_posture",
            self.posture_callback,
            10,
        )
        self.cmd_vel_publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self.debug_reference_path_publisher = DebugPathPublisher(
            self,
            "/reference_path",
        )
        self.publish_reference_path()
        self.control_timer = self.create_timer(self.config.dt, self.control_tick)
        self.get_logger().info(
            f"MPC started: {1.0 / self.config.dt:.1f} Hz, "
            f"{self.path_steps} steps, reference={self.reference_path_source}"
        )

    def posture_callback(self, message: PoseStamped) -> None:
        """Cache the latest posture received from the state node."""

        received_initial_posture = self.current_pose is None
        orientation = message.pose.orientation
        yaw = math.atan2(
            2.0
            * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        self.current_pose = Pose2D(
            x=message.pose.position.x,
            y=message.pose.position.y,
            yaw=yaw,
        )
        if received_initial_posture:
            self.get_logger().info("Received initial robot posture")

    def control_tick(self) -> None:
        """Solve one MPC step from the latest posture and publish it."""

        self.publish_reference_path()

        if self.current_pose is None:
            return

        if self.step_index >= self.path_steps:
            self.finish()
            return

        reference_window = self.reference_path[
            self.step_index : self.step_index + self.config.horizon + 1
        ]
        result = self.controller.solve(self.current_pose, reference_window)
        self.publish_command(result.command)
        self.step_index += 1

        if self.step_index == 1 or self.step_index % 10 == 0:
            self.get_logger().info(
                f"step={self.step_index:02d} "
                f"pose=({self.current_pose.x:.3f}, "
                f"{self.current_pose.y:.3f}, "
                f"{self.current_pose.yaw:.3f}) "
                f"wheels=({result.command.left_speed:.3f}, "
                f"{result.command.right_speed:.3f})"
            )

    def publish_command(self, command: WheelCommand) -> None:
        """Convert wheel speeds to the standard ROS body velocity command."""

        message = Twist()
        message.linear.x = command.linear_speed
        message.angular.z = command.angular_speed
        self.cmd_vel_publisher.publish(message)

    def publish_reference_path(self) -> None:
        """Republish the debug reference path at the MPC control frequency."""

        self.debug_reference_path_publisher.publish_planar_path(
            self.debug_reference_path_poses
        )

    def publish_stop(self) -> None:
        """Publish a zero body velocity command."""

        self.cmd_vel_publisher.publish(Twist())

    def finish(self) -> None:
        """Stop the controller after the reference path is complete."""

        self.publish_stop()
        self.control_timer.cancel()
        self.finished = True
        target = self.reference_path[
            min(self.path_steps, len(self.reference_path) - 1)
        ]
        assert self.current_pose is not None
        position_error = math.hypot(
            self.current_pose.x - target.x,
            self.current_pose.y - target.y,
        )
        self.get_logger().info(
            f"MPC finished: final position error={position_error:.6f} m"
        )


def main() -> None:
    rclpy.init()
    node = DifferentialDriveMPCNode()
    try:
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        node.get_logger().info("MPC interrupted")
    finally:
        node.publish_stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
