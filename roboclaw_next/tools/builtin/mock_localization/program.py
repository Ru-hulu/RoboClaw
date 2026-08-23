"""Lifecycle management for the mock localization ROS process."""

from __future__ import annotations

import asyncio
import shlex
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


POSE_SERVICE_NAME = "/mock_localization/get_pose"
POSE_SERVICE_TYPE = "roboclaw_interfaces/srv/GetMockLocalizationPose"
ROS_SETUP_PATH = "/opt/ros/humble/setup.bash"


class MockLocalizationState(StrEnum):
    """Lifecycle states exposed by the process manager."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class MockLocalizationStatus:
    """Current state of the managed ROS process."""

    state: MockLocalizationState
    pid: int | None = None
    return_code: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class MockLocalizationPose:
    """Current pose returned by the mock localization ROS service."""

    success: bool
    frame_id: str | None = None
    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    message: str | None = None


class MockLocalizationProcessManager:
    """Start, inspect, and stop one mock localization process."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._state = MockLocalizationState.IDLE
        self._message: str | None = None

    # 开始定位进程的位置
    async def start(self) -> MockLocalizationStatus:
        """Start the ROS node, or return its status if already running."""

        self._refresh_state()
        if self._state == MockLocalizationState.RUNNING:
            return self._status()

        repository_root = Path(__file__).resolve().parents[4]
        command = (
            f"source {ROS_SETUP_PATH} >/dev/null 2>&1; "
            "source install/setup.bash >/dev/null 2>&1 || true; "
            f"exec {shlex.quote(sys.executable)} -m "
            "robot_runtime.localization.mock_localization.kinematic_node"
        )
        # 真正开始运行location模块的地方。
        try:
            self._process = await asyncio.create_subprocess_exec(
                "bash",
                "-lc",
                command,
                cwd=repository_root,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            self._state = MockLocalizationState.FAILED
            self._message = str(exc)
            return self._status()

        self._state = MockLocalizationState.RUNNING
        self._message = "Mock localization process started."
        await asyncio.sleep(0.2)
        self._refresh_state()
        return self._status()

    async def get_status(self) -> MockLocalizationStatus:
        """Return the latest process state."""

        self._refresh_state()
        return self._status()

    async def get_pose(self, timeout_sec: float = 3.0) -> MockLocalizationPose:
        """Read the current pose with a short-lived ROS 2 service client."""

        try:
            return await asyncio.to_thread(_call_pose_service, timeout_sec)
        except TimeoutError:
            return MockLocalizationPose(
                success=False,
                message=(
                    f"Timed out waiting for ROS service {POSE_SERVICE_NAME}. "
                    "Make sure mock localization is running."
                ),
            )
        except (RuntimeError, ValueError) as exc:
            return MockLocalizationPose(success=False, message=str(exc))

    # 如何将定位进程停止
    async def stop(self) -> MockLocalizationStatus:
        """Stop the active process; repeated calls are safe."""

        self._refresh_state()
        if self._process is None or self._process.returncode is not None:
            self._state = MockLocalizationState.STOPPED
            self._message = "Mock localization process is not running."
            return self._status()

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except TimeoutError:
            self._process.kill()
            await self._process.wait() # wait() 不是让子进程清理自己的资源，而是让父进程完成对子进程退出状态的处理。

        self._state = MockLocalizationState.STOPPED
        self._message = "Mock localization process stopped."
        return self._status()

    # 对进程状态进行刷新
    def _refresh_state(self) -> None:
        if (
            self._process is not None
            and self._process.returncode is not None
            and self._state == MockLocalizationState.RUNNING
        ):
            self._state = (
                MockLocalizationState.STOPPED
                if self._process.returncode == 0
                else MockLocalizationState.FAILED
            )
            self._message = (
                "Mock localization process exited."
                if self._process.returncode == 0
                else "Mock localization process exited unexpectedly."
            )

    def _status(self) -> MockLocalizationStatus:
        return MockLocalizationStatus(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=(
                self._process.returncode if self._process is not None else None
            ),
            message=self._message,
        )


def _call_pose_service(timeout_sec: float) -> MockLocalizationPose:
    """Call /mock_localization/get_pose through an in-process ROS client node."""

    try:
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
        from roboclaw_interfaces.srv import GetMockLocalizationPose
    except ImportError as exc:
        raise RuntimeError(
            "ROS 2 Python packages or roboclaw_interfaces are not available. "
            f"Run this tool after sourcing {ROS_SETUP_PATH} and "
            "install/setup.bash."
        ) from exc

    context = Context()
    rclpy.init(
        args=None,
        context=context,
        signal_handler_options=SignalHandlerOptions.NO,
    )
    node = None
    executor = None
    try:
        node = rclpy.create_node(
            "mock_localization_pose_client",
            context=context,
        )
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        client = node.create_client(GetMockLocalizationPose, POSE_SERVICE_NAME)
        if not client.wait_for_service(timeout_sec=timeout_sec):
            raise TimeoutError

        future = client.call_async(GetMockLocalizationPose.Request())
        rclpy.spin_until_future_complete(
            node,
            future,
            executor=executor,
            timeout_sec=timeout_sec,
        )
        if not future.done():
            raise TimeoutError

        response = future.result()
        if response is None:
            error = future.exception()
            message = str(error) if error is not None else "empty service response"
            raise RuntimeError(
                f"Failed to call ROS service {POSE_SERVICE_NAME}: {message}"
            )
        if not response.success:
            return MockLocalizationPose(
                success=False,
                message=response.message or (
                    f"ROS service {POSE_SERVICE_NAME} returned failure."
                ),
            )
        return MockLocalizationPose(
            success=response.success,
            frame_id=response.frame_id,
            x=response.x,
            y=response.y,
            yaw=response.yaw,
            message=response.message,
        )
    finally:
        if executor is not None:
            if node is not None:
                executor.remove_node(node)
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if context.ok():
            rclpy.shutdown(context=context)
