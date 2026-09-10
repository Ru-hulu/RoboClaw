"""Lifecycle management for the MPC path tracking ROS process."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from robot_runtime.control.differential_drive_mpc.reference_path import (
    load_hybrid_astar_path_points,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PLAN_OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "runtime_data"
    / "hybrid_astar"
    / "latest_hybrid_astar_path.json"
)


class TrackingState(str, Enum):
    """Lifecycle states reported by the path tracking process."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TrackingStatus:
    """Internal status returned by the process manager."""

    state: TrackingState
    pid: int | None = None
    return_code: int | None = None
    message: str | None = None
    reference_path_file: str | None = None


class PathTrackingProcessManager:
    """Start, inspect, and stop one MPC path tracking process."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._state = TrackingState.IDLE
        self._message: str | None = None
        self._reference_path_file: str | None = None

    async def start(self, reference_path_file: str | None = None) -> TrackingStatus:
        """Start MPC with a validated Hybrid A* reference path."""

        self._refresh_state()
        if self._state == TrackingState.RUNNING:
            if reference_path_file:
                self._message = (
                    "MPC path tracking process is already running; stop it "
                    "before changing reference_path_file."
                )
            return self._status()

        try:
            resolved_reference_path = self._resolve_reference_path_file(
                reference_path_file,
                REPOSITORY_ROOT,
            )
        except ValueError as exc:
            self._state = TrackingState.FAILED
            self._reference_path_file = None
            self._message = str(exc)
            return self._status()

        command = [
            sys.executable,
            "-m",
            "robot_runtime.control.differential_drive_mpc.ros_node",
        ]
        command.extend(
            [
                "--ros-args",
                "-p",
                f"reference_path_file:={resolved_reference_path}",
            ]
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=REPOSITORY_ROOT,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            self._state = TrackingState.FAILED
            self._reference_path_file = None
            self._message = str(exc)
            return self._status()

        self._state = TrackingState.RUNNING
        self._reference_path_file = str(resolved_reference_path)
        self._message = (
            "MPC path tracking process started with reference path file: "
            f"{self._reference_path_file}"
        )
        await asyncio.sleep(0.2)
        self._refresh_state()
        return self._status()

    async def get_status(self) -> TrackingStatus:
        """Return the latest MPC process state."""

        self._refresh_state()
        return self._status()

    async def stop(self) -> TrackingStatus:
        """Stop the active MPC process; repeated calls are safe."""

        self._refresh_state()
        if self._process is None:
            self._state = TrackingState.STOPPED
            self._message = "MPC path tracking process is not running."
            return self._status()
        if self._process.returncode is not None:
            return self._status()

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()

        self._state = TrackingState.STOPPED
        self._message = "MPC path tracking process stopped."
        return self._status()

    def _refresh_state(self) -> None:
        if (
            self._process is not None
            and self._process.returncode is not None
            and self._state == TrackingState.RUNNING
        ):
            self._state = (
                TrackingState.SUCCEEDED
                if self._process.returncode == 0
                else TrackingState.FAILED
            )
            self._message = (
                "MPC path tracking process completed."
                if self._process.returncode == 0
                else "MPC path tracking process exited unexpectedly."
            )

    def _status(self) -> TrackingStatus:
        return TrackingStatus(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=(
                self._process.returncode if self._process is not None else None
            ),
            message=self._message,
            reference_path_file=self._reference_path_file,
        )

    def _resolve_reference_path_file(
        self,
        reference_path_file: str | None,
        repository_root: Path,
    ) -> Path:
        requested_path = (reference_path_file or "").strip()
        if requested_path:
            path = Path(requested_path).expanduser()
            if not path.is_absolute():
                path = repository_root / path
        elif DEFAULT_PLAN_OUTPUT_PATH.is_file():
            path = DEFAULT_PLAN_OUTPUT_PATH
        else:
            raise ValueError(
                "Cannot start path tracking because no Hybrid A* reference "
                f"path JSON was provided and latest path does not exist: "
                f"{DEFAULT_PLAN_OUTPUT_PATH}"
            )

        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"Reference path file does not exist: {path}")
        self._validate_reference_path_file(path)
        return path

    def _validate_reference_path_file(self, path: Path) -> None:
        try:
            load_hybrid_astar_path_points(path)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
