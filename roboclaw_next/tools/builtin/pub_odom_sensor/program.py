"""Start and manage the pubOdomSensor ROS process."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from robot_runtime.navigation.pub_odom_sensor.constants import (
    DEFAULT_ENTITY_STATE_SERVICE,
    DEFAULT_LIDAR_TOPIC,
    DEFAULT_MODEL_NAME,
)
from robot_runtime.navigation.pub_odom_sensor.lcm_protocol import ODOM_SENSOR_CHANNEL

from .models import PubOdomSensorState, PubOdomSensorStatusResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class PubOdomSensorManager:
    """Keep one pubOdomSensor process alive after startup."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = PubOdomSensorState.STOPPED
        self._model_name: str | None = None
        self._entity_state_service: str | None = None
        self._lidar_topic: str | None = None
        self._lcm_channel: str | None = None
        self._lidar_received = False
        self._entity_state_received = False
        self._published_count = 0
        self._dropped_lidar_count = 0
        self._last_service_latency_sec: float | None = None
        self._last_error: str | None = None
        self._message = "pubOdomSensor is stopped."

    async def start(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        entity_state_service: str = DEFAULT_ENTITY_STATE_SERVICE,
        lidar_topic: str = DEFAULT_LIDAR_TOPIC,
        lcm_channel: str = ODOM_SENSOR_CHANNEL,
        startup_timeout_sec: float = 10.0,
    ) -> PubOdomSensorStatusResult:
        async with self._lock:
            self._refresh_state()
            if self._process is not None and self._process.returncode is None:
                self._message = "pubOdomSensor is already running."
                return self._status()

            self._state = PubOdomSensorState.STARTING
            self._model_name = model_name
            self._entity_state_service = entity_state_service
            self._lidar_topic = lidar_topic
            self._lcm_channel = lcm_channel
            self._lidar_received = False
            self._entity_state_received = False
            self._published_count = 0
            self._dropped_lidar_count = 0
            self._last_service_latency_sec = None
            self._last_error = None
            self._message = "pubOdomSensor is starting."

            try:
                self._process = await asyncio.create_subprocess_exec(
                    os.environ.get(
                        "ROBOCLAW_PUB_ODOM_SENSOR_ROS_PYTHON",
                        sys.executable,
                    ),
                    "-m",
                    "robot_runtime.navigation.pub_odom_sensor.ros_node",
                    "--model-name",
                    model_name,
                    "--entity-state-service",
                    entity_state_service,
                    "--lidar-topic",
                    lidar_topic,
                    "--lcm-channel",
                    lcm_channel,
                    "--startup-timeout-sec",
                    str(startup_timeout_sec),
                    cwd=REPOSITORY_ROOT,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                self._state = PubOdomSensorState.FAILED
                self._message = str(exc)
                return self._status()

            assert self._process.stdout is not None
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=startup_timeout_sec + 2.0,
                )
            except TimeoutError:
                self._process.terminate()
                await self._process.wait()
                self._state = PubOdomSensorState.FAILED
                self._message = "pubOdomSensor did not report startup."
                return self._status()

            if not line:
                await self._process.wait()
                self._state = PubOdomSensorState.FAILED
                self._message = "pubOdomSensor exited before startup."
                return self._status()

            try:
                payload = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._process.terminate()
                await self._process.wait()
                self._state = PubOdomSensorState.FAILED
                self._message = f"Invalid pubOdomSensor startup JSON: {exc}"
                return self._status()

            if not isinstance(payload, dict):
                self._process.terminate()
                await self._process.wait()
                self._state = PubOdomSensorState.FAILED
                self._message = "Invalid pubOdomSensor startup JSON."
                return self._status()

            self._lidar_received = bool(payload.get("lidar_received"))
            self._entity_state_received = bool(payload.get("entity_state_received"))
            self._published_count = _int_field(payload, "published_count")
            self._dropped_lidar_count = _int_field(payload, "dropped_lidar_count")
            self._last_service_latency_sec = _optional_float_field(
                payload,
                "last_service_latency_sec",
            )
            last_error = payload.get("last_error")
            self._last_error = last_error if isinstance(last_error, str) else None
            self._message = str(payload.get("message") or "")
            if payload.get("ok") is not True:
                self._state = PubOdomSensorState.FAILED
                await self._process.wait()
                return self._status()

            self._state = PubOdomSensorState.RUNNING
            return self._status()

    async def get_status(self) -> PubOdomSensorStatusResult:
        self._refresh_state()
        return self._status()

    async def stop(self) -> PubOdomSensorStatusResult:
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
            self._message = "pubOdomSensor is stopped."
            self._state = PubOdomSensorState.STOPPED
            return self._status()

    def _refresh_state(self) -> None:
        if self._process is None:
            self._state = PubOdomSensorState.STOPPED
            return
        if (
            self._process.returncode is not None
            and self._state != PubOdomSensorState.STOPPED
        ):
            self._state = PubOdomSensorState.FAILED
            self._message = "pubOdomSensor exited."

    def _status(self) -> PubOdomSensorStatusResult:
        return PubOdomSensorStatusResult(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=self._process.returncode if self._process is not None else None,
            model_name=self._model_name,
            entity_state_service=self._entity_state_service,
            lidar_topic=self._lidar_topic,
            lcm_channel=self._lcm_channel,
            lidar_received=self._lidar_received,
            entity_state_received=self._entity_state_received,
            published_count=self._published_count,
            dropped_lidar_count=self._dropped_lidar_count,
            last_service_latency_sec=self._last_service_latency_sec,
            last_error=self._last_error,
            message=self._message,
        )


def _int_field(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    return value if isinstance(value, int) else 0


def _optional_float_field(payload: dict[str, object], name: str) -> float | None:
    value = payload.get(name)
    if isinstance(value, (int, float)):
        return float(value)
    return None
