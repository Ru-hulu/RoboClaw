"""Send OpenArm joint trajectories through ROS 2 FollowJointTrajectory."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from robot_runtime.openarm_ik import ARM_JOINT_VELOCITY_LIMITS_RAD_S, arm


DEFAULT_ACTION_NAME = "/openarm_joint_trajectory_controller/follow_joint_trajectory"
DEFAULT_SPEED_SCALE = 0.2
DEFAULT_MIN_SEGMENT_SEC = 0.05
DEFAULT_SERVER_TIMEOUT_SEC = 2.0
DEFAULT_RESULT_GRACE_SEC = 10.0


@dataclass(frozen=True)
class TimedJointPoint:
    """One position-only command with a strictly positive time from start."""

    time_from_start: float
    positions: tuple[float, ...]


@dataclass(frozen=True)
class TrajectoryExecution:
    """Result returned by the FollowJointTrajectory action server."""

    success: bool
    sent: bool
    action_name: str
    point_count: int
    duration_sec: float
    status: int
    error_code: int
    error_string: str


def retime_joint_positions(
    positions: Sequence[Sequence[float]],
    *,
    speed_scale: float = DEFAULT_SPEED_SCALE,
    min_segment_sec: float = DEFAULT_MIN_SEGMENT_SEC,
) -> tuple[TimedJointPoint, ...]:
    """Apply a velocity-bound time scale to a sequence of 7-joint positions.

    The first position is the measured planning start and is not sent as a
    zero-time trajectory point. Each later point receives a monotonically
    increasing time that respects the documented per-joint velocity limits.
    Acceleration and collision constraints are intentionally outside this
    minimal sender.
    """

    if not 0.0 < speed_scale <= 1.0:
        raise ValueError("speed_scale must be in (0, 1]")
    if not math.isfinite(min_segment_sec) or min_segment_sec <= 0.0:
        raise ValueError("min_segment_sec must be finite and positive")
    if not positions:
        raise ValueError("trajectory must contain at least one position")

    normalized = tuple(_validate_positions(point) for point in positions)
    if len(normalized) == 1:
        return ()

    elapsed = 0.0
    timed: list[TimedJointPoint] = []
    previous = normalized[0]
    limits = ARM_JOINT_VELOCITY_LIMITS_RAD_S
    for current in normalized[1:]:
        required = max(
            abs(value - prior) / (limit * speed_scale)
            for value, prior, limit in zip(current, previous, limits)
        )
        elapsed += max(min_segment_sec, required)
        timed.append(TimedJointPoint(elapsed, current))
        previous = current
    return tuple(timed)


def send_joint_trajectory(
    side: str,
    points: Sequence[TimedJointPoint],
    *,
    action_name: str = DEFAULT_ACTION_NAME,
    server_timeout_sec: float = DEFAULT_SERVER_TIMEOUT_SEC,
    result_grace_sec: float = DEFAULT_RESULT_GRACE_SEC,
) -> TrajectoryExecution:
    """Synchronously send one trajectory and wait for its action result.

    ROS imports are intentionally lazy so planning and unit tests remain usable
    on machines that do not have ROS 2 installed.
    """

    kinematics = arm(side)
    normalized = _validate_timed_points(points)
    if not normalized:
        return TrajectoryExecution(
            success=True,
            sent=False,
            action_name=action_name,
            point_count=0,
            duration_sec=0.0,
            status=0,
            error_code=0,
            error_string="The arm is already at the planned target.",
        )
    if server_timeout_sec <= 0.0 or result_grace_sec <= 0.0:
        raise ValueError("trajectory action timeouts must be positive")

    try:
        import rclpy
        from action_msgs.msg import GoalStatus
        from builtin_interfaces.msg import Duration
        from control_msgs.action import FollowJointTrajectory
        from rclpy.action import ActionClient
        from rclpy.context import Context
        from rclpy.signals import SignalHandlerOptions
        from trajectory_msgs.msg import JointTrajectoryPoint
    except ImportError as exc:
        raise RuntimeError(
            "ROS 2 trajectory packages are unavailable. Source "
            "/opt/ros/humble/setup.bash before starting the MCP server."
        ) from exc

    context = Context()
    node = None
    client = None
    executor = None
    try:
        rclpy.init(
            args=None,
            context=context,
            signal_handler_options=SignalHandlerOptions.NO,
        )
        from rclpy.executors import SingleThreadedExecutor

        node = rclpy.create_node(
            f"openarm_{side}_trajectory_sender",
            context=context,
        )
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        client = ActionClient(node, FollowJointTrajectory, action_name)
        if not client.wait_for_server(timeout_sec=server_timeout_sec):
            raise RuntimeError(
                f"OpenArm trajectory action server is unavailable: {action_name}"
            )

        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(kinematics.joint_names)
        for point in normalized:
            message = JointTrajectoryPoint()
            message.positions = list(point.positions)
            seconds = int(point.time_from_start)
            nanoseconds = round((point.time_from_start - seconds) * 1_000_000_000)
            if nanoseconds == 1_000_000_000:
                seconds += 1
                nanoseconds = 0
            message.time_from_start = Duration(sec=seconds, nanosec=nanoseconds)
            goal.trajectory.points.append(message)

        send_future = client.send_goal_async(goal)
        executor.spin_until_future_complete(
            send_future,
            timeout_sec=server_timeout_sec,
        )
        if not send_future.done():
            raise RuntimeError("Timed out while sending the OpenArm trajectory goal.")
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError("OpenArm trajectory controller rejected the goal.")

        result_future = goal_handle.get_result_async()
        result_timeout = normalized[-1].time_from_start + result_grace_sec
        executor.spin_until_future_complete(
            result_future,
            timeout_sec=result_timeout,
        )
        if not result_future.done():
            cancel_future = goal_handle.cancel_goal_async()
            executor.spin_until_future_complete(
                cancel_future,
                timeout_sec=server_timeout_sec,
            )
            raise RuntimeError(
                f"OpenArm trajectory execution timed out after {result_timeout:.1f} s."
            )

        wrapped_result = result_future.result()
        if wrapped_result is None:
            raise RuntimeError("OpenArm trajectory action returned no result.")
        result = wrapped_result.result
        status = int(wrapped_result.status)
        error_code = int(result.error_code)
        return TrajectoryExecution(
            success=(
                status == GoalStatus.STATUS_SUCCEEDED
                and error_code == FollowJointTrajectory.Result.SUCCESSFUL
            ),
            sent=True,
            action_name=action_name,
            point_count=len(normalized),
            duration_sec=normalized[-1].time_from_start,
            status=status,
            error_code=error_code,
            error_string=str(result.error_string),
        )
    finally:
        if client is not None:
            client.destroy()
        if executor is not None:
            if node is not None:
                executor.remove_node(node)
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if context.ok():
            rclpy.shutdown(context=context)


def _validate_positions(values: Sequence[float]) -> tuple[float, ...]:
    positions = tuple(float(value) for value in values)
    if len(positions) != 7:
        raise ValueError(f"trajectory point must contain 7 joints, got {len(positions)}")
    if not all(math.isfinite(value) for value in positions):
        raise ValueError("trajectory point contains a non-finite joint position")
    return positions


def _validate_timed_points(
    points: Sequence[TimedJointPoint],
) -> tuple[TimedJointPoint, ...]:
    normalized: list[TimedJointPoint] = []
    previous_time = 0.0
    for point in points:
        timestamp = float(point.time_from_start)
        if not math.isfinite(timestamp) or timestamp <= previous_time:
            raise ValueError("trajectory times must be finite and strictly increasing")
        normalized.append(TimedJointPoint(timestamp, _validate_positions(point.positions)))
        previous_time = timestamp
    return tuple(normalized)
