"""Run the standalone Hybrid A* planner and validate its JSON result."""

from __future__ import annotations

import asyncio
import math
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .models import HybridAStarPlan


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PLANNER_ROOT = REPOSITORY_ROOT / "robot_runtime" / "planning" / "hybrid_astar"
DEFAULT_MAP_PATH = PLANNER_ROOT / "maps" / "empty_80x80.png"
DEFAULT_EXECUTABLE_PATH = (
    REPOSITORY_ROOT / "install" / "lib" / "hybrid_astar" / "hybrid_astar_plan"
)
STANDALONE_EXECUTABLE_PATH = PLANNER_ROOT / "build" / "hybrid_astar_plan"
DEFAULT_PLAN_OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "runtime_data"
    / "hybrid_astar"
    / "latest_hybrid_astar_path.json"
)


class HybridAStarPlannerRunner:
    """Execute one Hybrid A* planning request without a ROS process or service."""

    def __init__(
        self,
        *,
        executable_path: Path | None = None,
        map_path: Path | None = None,
        plan_output_path: Path | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be greater than zero.")

        self._executable_path = executable_path
        self._map_path = (map_path or DEFAULT_MAP_PATH).resolve()
        self._plan_output_path = (
            plan_output_path or DEFAULT_PLAN_OUTPUT_PATH
        ).resolve()
        self._timeout_sec = timeout_sec

    async def plan(
        self,
        start_x: float,
        start_y: float,
        start_yaw: float,
        goal_x: float,
        goal_y: float,
        goal_yaw: float,
    ) -> HybridAStarPlan:
        """Run the planner once with six map-frame pose values."""

        values = (start_x, start_y, start_yaw, goal_x, goal_y, goal_yaw)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Planner coordinates and yaw values must be finite.")
        if not self._map_path.is_file():
            message = f"Hybrid A* map does not exist: {self._map_path}"
            self._store_latest_plan(self._failure_plan(message))
            raise RuntimeError(message)

        try:
            executable = self._resolve_executable()
        except RuntimeError as error:
            self._store_latest_plan(self._failure_plan(str(error)))
            raise

        self._store_latest_plan(
            self._failure_plan(
                "Hybrid A* planning is running; no completed latest plan is available."
            )
        )
        command = (
            str(executable),
            "--start-x",
            repr(start_x),
            "--start-y",
            repr(start_y),
            "--start-yaw",
            repr(start_yaw),
            "--goal-x",
            repr(goal_x),
            "--goal-y",
            repr(goal_y),
            "--goal-yaw",
            repr(goal_yaw),
            "--map-path",
            str(self._map_path),
        )

        # 捕获规划器 CLI 的输出，而不是让它直接打印到终端。
        # 这里约定 stdout 只包含一个机器可读的 JSON 对象，用来表示路径结果；
        # 调试信息和错误信息应该写到 stderr，方便后面严格校验 stdout。
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=PLANNER_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            # communicate() 会等待规划器进程结束，并返回捕获到的 stdout/stderr 字节。
            # 超时保护结束后，路径结果会从 stdout 中的 JSON 解码出来。
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_sec,
            )
        except TimeoutError as error:
            if process.returncode is None:
                process.kill()
                await process.wait()
            message = (
                f"Hybrid A* planning timed out after {self._timeout_sec:g} seconds."
            )
            self._store_latest_plan(self._failure_plan(message))
            raise RuntimeError(message) from error
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

        stderr_message = stderr.decode("utf-8", errors="replace").strip()
        try:
            result = _decode_plan(stdout)
        except ValidationError as error:
            details = stderr_message or stdout.decode(
                "utf-8", errors="replace"
            ).strip()
            suffix = f" Planner output: {details}" if details else ""
            message = f"Hybrid A* returned invalid result JSON.{suffix}"
            self._store_latest_plan(self._failure_plan(message))
            raise RuntimeError(message) from error

        if process.returncode != 0 and result.success:
            message = (
                "Hybrid A* reported success but exited with code "
                f"{process.returncode}. {stderr_message}".strip()
            )
            self._store_latest_plan(self._failure_plan(message))
            raise RuntimeError(message)
        return self._store_latest_plan(result)

    def _resolve_executable(self) -> Path:
        for candidate in self._executable_candidates():
            executable_path = candidate.resolve()
            if not executable_path.is_file():
                continue
            if os.access(executable_path, os.X_OK):
                return executable_path
            raise RuntimeError(
                f"Hybrid A* executable is not executable: {executable_path}"
            )

        searched = ", ".join(
            str(candidate.resolve()) for candidate in self._executable_candidates()
        )
        raise RuntimeError(
            "Hybrid A* executable does not exist. Searched: "
            f"{searched}. Build the ROS 2 workspace with "
            "`colcon build --packages-up-to roboclaw_interfaces hybrid_astar`, "
            "or build the standalone planner with "
            "`cmake -S robot_runtime/planning/hybrid_astar "
            "-B robot_runtime/planning/hybrid_astar/build` followed by "
            "`cmake --build robot_runtime/planning/hybrid_astar/build`."
        )

    def _executable_candidates(self) -> tuple[Path, ...]:
        if self._executable_path is not None:
            return (self._executable_path,)
        return (DEFAULT_EXECUTABLE_PATH, STANDALONE_EXECUTABLE_PATH)

    def _store_latest_plan(self, result: HybridAStarPlan) -> HybridAStarPlan:
        """Persist the latest planner result with an atomic file replacement."""

        self._plan_output_path.parent.mkdir(parents=True, exist_ok=True)
        stored_result = result.model_copy(
            update={"path_file": str(self._plan_output_path)}
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._plan_output_path.parent,
                prefix=f".{self._plan_output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(stored_result.model_dump_json(indent=2))
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            temporary_path.replace(self._plan_output_path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Failed to store latest Hybrid A* plan: {self._plan_output_path}"
            ) from error
        return stored_result

    def _failure_plan(self, message: str) -> HybridAStarPlan:
        return HybridAStarPlan(
            success=False,
            frame_id="map",
            waypoints=(),
            waypoint_count=0,
            map_path=str(self._map_path),
            planning_time_ms=0.0,
            message=message,
        )


def _decode_plan(stdout: bytes) -> HybridAStarPlan:
    return HybridAStarPlan.model_validate_json(stdout)
