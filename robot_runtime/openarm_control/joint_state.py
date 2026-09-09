"""Continuously cache OpenArm joint angles from ROS ``/joint_states``.

The first read lazily starts one process-wide ROS node. Its background executor
keeps the latest joint-state message in memory for all later MCP calls. The
kinematics package stays dependency-free; all rclpy lifecycle code lives here.
"""

from __future__ import annotations

import atexit
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from robot_runtime.openarm_ik.model import arm


JOINT_STATES_TOPIC = "/joint_states"
ROS_SETUP_PATH = "/opt/ros/humble/setup.bash"
DEFAULT_TIMEOUT_SEC = 2.0
DEFAULT_MAX_AGE_SEC = 1.0


@dataclass(frozen=True)
class ArmJointState:
    """One arm's joint angles, ordered to match the kinematic model."""

    side: str
    names: tuple[str, ...]
    positions: tuple[float, ...]


class JointStateReader:
    """Own one long-lived ROS subscriber and a thread-safe latest-state cache."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._positions_by_name: dict[str, float] | None = None
        self._received_at: float | None = None
        self._spin_error: BaseException | None = None
        self._rclpy: Any | None = None
        self._context: Any | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._subscription: Any | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the subscriber once; repeated calls are safe."""

        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._thread is not None:
                raise RuntimeError("OpenArm joint-state listener has stopped")

            try:
                import rclpy
                from rclpy.context import Context
                from rclpy.executors import SingleThreadedExecutor
                from rclpy.signals import SignalHandlerOptions
                from sensor_msgs.msg import JointState
            except ImportError as exc:
                raise RuntimeError(
                    "ROS 2 Python packages are not available, so current joint "
                    f"angles cannot be read. Source {ROS_SETUP_PATH} before "
                    "starting the MCP server."
                ) from exc

            context = Context()
            node = None
            executor = None
            try:
                rclpy.init(
                    args=None,
                    context=context,
                    signal_handler_options=SignalHandlerOptions.NO,
                )
                node = rclpy.create_node(
                    "openarm_joint_state_reader",
                    context=context,
                )
                executor = SingleThreadedExecutor(context=context)
                executor.add_node(node)
                subscription = node.create_subscription(
                    JointState,
                    JOINT_STATES_TOPIC,
                    self._on_joint_state,
                    10,
                )
            except BaseException:
                self._cleanup_ros(rclpy, context, node, executor)
                raise

            self._rclpy = rclpy
            self._context = context
            self._node = node
            self._executor = executor
            self._subscription = subscription
            with self._condition:
                self._positions_by_name = None
                self._received_at = None
                self._spin_error = None
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._spin,
                name="openarm-joint-state-reader",
                daemon=True,
            )
            self._thread.start()

    def read_arm(
        self,
        side: str,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    ) -> ArmJointState:
        """Return a fresh cached state for one arm, waiting when necessary."""

        kinematics = arm(side)
        if timeout_sec < 0.0:
            raise ValueError("timeout_sec must not be negative")
        if max_age_sec < 0.0:
            raise ValueError("max_age_sec must not be negative")
        self.start()

        deadline = time.monotonic() + timeout_sec
        with self._condition:
            while True:
                if self._spin_error is not None:
                    raise RuntimeError(
                        "OpenArm joint-state listener stopped unexpectedly"
                    ) from self._spin_error
                now = time.monotonic()
                if (
                    self._positions_by_name is not None
                    and self._received_at is not None
                    and now - self._received_at <= max_age_sec
                ):
                    by_name = self._positions_by_name.copy()
                    break
                remaining = deadline - now
                if remaining <= 0.0:
                    raise RuntimeError(
                        f"No fresh message received on {JOINT_STATES_TOPIC} within "
                        f"{timeout_sec:.1f} s. Make sure the simulation is running "
                        "and joint_state_broadcaster is active."
                    )
                self._condition.wait(timeout=remaining)

        positions = kinematics.order_joint_positions(by_name)
        invalid = [
            name
            for name, value in zip(kinematics.joint_names, positions)
            if not math.isfinite(value)
        ]
        if invalid:
            raise RuntimeError(f"joint state contains non-finite values: {invalid}")
        return ArmJointState(
            side=kinematics.side,
            names=kinematics.joint_names,
            positions=positions,
        )

    def close(self) -> None:
        """Stop the executor thread and release ROS resources."""

        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()

        if thread is not threading.current_thread():
            thread.join(timeout=1.0)

        with self._lifecycle_lock:
            self._cleanup_ros(
                self._rclpy,
                self._context,
                self._node,
                self._executor,
            )
            self._rclpy = None
            self._context = None
            self._node = None
            self._executor = None
            self._subscription = None
            self._thread = None

    def _on_joint_state(self, message: object) -> None:
        by_name = dict(zip(message.name, message.position))
        received_at = time.monotonic()
        with self._condition:
            self._positions_by_name = by_name
            self._received_at = received_at
            self._condition.notify_all()

    def _spin(self) -> None:
        try:
            while not self._stop_event.is_set() and self._context.ok():
                self._executor.spin_once(timeout_sec=0.1)
        except BaseException as exc:
            with self._condition:
                self._spin_error = exc
                self._condition.notify_all()

    @staticmethod
    def _cleanup_ros(rclpy, context, node, executor) -> None:
        if executor is not None:
            if node is not None:
                executor.remove_node(node)
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if context is not None and context.ok():
            rclpy.shutdown(context=context)


_DEFAULT_READER = JointStateReader()
atexit.register(_DEFAULT_READER.close)


def read_arm_joint_state(
    side: str,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
) -> ArmJointState:
    """Read one arm from the shared process-wide joint-state listener."""

    return _DEFAULT_READER.read_arm(
        side,
        timeout_sec=timeout_sec,
        max_age_sec=max_age_sec,
    )
