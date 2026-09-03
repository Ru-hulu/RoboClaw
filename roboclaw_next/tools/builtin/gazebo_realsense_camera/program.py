"""Start and manage the Gazebo RealSense listener node."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from .models import (
    GazeboRealsenseCameraState,
    GazeboRealsenseCameraStatusResult,
)


DEFAULT_COLOR_IMAGE_TOPIC = "/head_realsense/color/image_raw"
DEFAULT_DEPTH_IMAGE_TOPIC = "/head_realsense/depth/depth/image_raw"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class GazeboRealsenseCameraManager:
    """Keep one Gazebo RealSense listener process alive after startup."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = GazeboRealsenseCameraState.STOPPED
        self._color_image_topic: str | None = None
        self._depth_image_topic: str | None = None
        self._color_image_received = False
        self._depth_image_received = False
        self._message = "Gazebo RealSense listener is stopped."

    async def start(
        self,
        *,
        color_image_topic: str = DEFAULT_COLOR_IMAGE_TOPIC,
        depth_image_topic: str = DEFAULT_DEPTH_IMAGE_TOPIC,
        frame_timeout_sec: float = 10.0,
    ) -> GazeboRealsenseCameraStatusResult:
        async with self._lock:
            self._refresh_state()
            if self._process is not None and self._process.returncode is None:
                self._message = "Gazebo RealSense listener is already running."
                return self._status()

            self._state = GazeboRealsenseCameraState.STARTING
            self._color_image_topic = color_image_topic
            self._depth_image_topic = depth_image_topic
            self._color_image_received = False
            self._depth_image_received = False
            try:
                self._process = await asyncio.create_subprocess_exec(
                    os.environ.get(
                        "ROBOCLAW_CAMERA_CAPTURE_ROS_PYTHON",
                        sys.executable,
                    ),
                    "-m",
                    "robot_runtime.perception.gazebo_realsense_capture.ros_node",
                    "--color-image-topic",
                    color_image_topic,
                    "--depth-image-topic",
                    depth_image_topic,
                    "--frame-timeout-sec",
                    str(frame_timeout_sec),
                    cwd=REPOSITORY_ROOT,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                self._state = GazeboRealsenseCameraState.FAILED
                self._message = str(exc)
                return self._status()

            assert self._process.stdout is not None
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=frame_timeout_sec + 2.0,
                )
            except TimeoutError:
                self._process.terminate()
                await self._process.wait()
                self._state = GazeboRealsenseCameraState.FAILED
                self._message = "Gazebo RealSense listener did not report startup."
                return self._status()

            if not line:
                await self._process.wait()
                self._state = GazeboRealsenseCameraState.FAILED
                self._message = "Gazebo RealSense listener exited before startup."
                return self._status()

            try:
                payload = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._process.terminate()
                await self._process.wait()
                self._state = GazeboRealsenseCameraState.FAILED
                self._message = f"Invalid Gazebo RealSense startup JSON: {exc}"
                return self._status()

            if not isinstance(payload, dict):
                self._process.terminate()
                await self._process.wait()
                self._state = GazeboRealsenseCameraState.FAILED
                self._message = "Invalid Gazebo RealSense startup JSON."
                return self._status()

            self._color_image_received = bool(payload.get("color_image_received"))
            self._depth_image_received = bool(payload.get("depth_image_received"))
            self._message = str(payload.get("message") or "")
            if payload.get("ok") is not True:
                self._state = GazeboRealsenseCameraState.FAILED
                await self._process.wait()
                return self._status()

            self._state = GazeboRealsenseCameraState.RUNNING
            return self._status()

    async def get_status(self) -> GazeboRealsenseCameraStatusResult:
        self._refresh_state()
        return self._status()

    async def stop(self) -> GazeboRealsenseCameraStatusResult:
        async with self._lock:
            self._refresh_state()
            if self._process is not None and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            self._process = None
            self._message = "Gazebo RealSense listener is stopped."
            self._state = GazeboRealsenseCameraState.STOPPED
            return self._status()

    def _refresh_state(self) -> None:
        if self._process is None:
            self._state = GazeboRealsenseCameraState.STOPPED
            return
        if (
            self._process.returncode is not None
            and self._state != GazeboRealsenseCameraState.STOPPED
        ):
            self._state = GazeboRealsenseCameraState.FAILED
            self._message = "Gazebo RealSense listener exited."

    def _status(self) -> GazeboRealsenseCameraStatusResult:
        return GazeboRealsenseCameraStatusResult(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=self._process.returncode if self._process is not None else None,
            color_image_topic=self._color_image_topic,
            depth_image_topic=self._depth_image_topic,
            color_image_received=self._color_image_received,
            depth_image_received=self._depth_image_received,
            message=self._message,
        )
