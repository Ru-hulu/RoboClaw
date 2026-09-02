"""Run one-shot SAM3 ROS current-view jobs and read their JSON results."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from robot_runtime.perception.sam3.errors import Sam3ErrorCode, Sam3RuntimeError

from .models import CameraCalibrationInput, Sam3CurrentViewResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_IMAGE_TOPIC = "/head_realsense/color/image_raw"
DEFAULT_RESULT_ROOT = REPOSITORY_ROOT / "runtime_data" / "sam3" / "current_view"
DEFAULT_JOB_TIMEOUT_SEC = 180.0
DEFAULT_TERMINATION_TIMEOUT_SEC = 5.0


class Sam3JobState(StrEnum):
    """Lifecycle states for the current one-shot SAM3 job."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class Sam3OneShotConfig:
    """Process settings for the ROS current-view segmentation node."""

    command_prefix: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    result_root: Path
    job_timeout_sec: float = DEFAULT_JOB_TIMEOUT_SEC
    termination_timeout_sec: float = DEFAULT_TERMINATION_TIMEOUT_SEC

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> Sam3OneShotConfig:
        values = dict(os.environ if env is None else env)
        root = (repository_root or REPOSITORY_ROOT).resolve()
        python_executable = values.get(
            "ROBOCLAW_SAM3_ROS_PYTHON",
            sys.executable,
        ).strip()
        if not python_executable:
            raise ValueError("ROBOCLAW_SAM3_ROS_PYTHON cannot be blank.")
        result_root = _resolve_path(
            values.get("ROBOCLAW_SAM3_CURRENT_VIEW_OUTPUT_ROOT", "")
            or str(DEFAULT_RESULT_ROOT),
            root,
        )
        return cls(
            command_prefix=(
                python_executable,
                "-m",
                "robot_runtime.perception.sam3.ros_node",
            ),
            cwd=root,
            environment=values,
            result_root=result_root,
            job_timeout_sec=_positive_timeout(
                values.get("ROBOCLAW_SAM3_JOB_TIMEOUT_SEC", "180"),
                "ROBOCLAW_SAM3_JOB_TIMEOUT_SEC",
            ),
            termination_timeout_sec=_positive_timeout(
                values.get("ROBOCLAW_SAM3_TERMINATION_TIMEOUT_SEC", "5"),
                "ROBOCLAW_SAM3_TERMINATION_TIMEOUT_SEC",
            ),
        )


@dataclass(frozen=True)
class Sam3JobStatus:
    """Compact state returned by status and cancel tools."""

    state: Sam3JobState
    pid: int | None
    return_code: int | None
    current_request_id: str | None
    last_result_json_path: str | None
    message: str


class Sam3OneShotProcessManager:
    """Start exactly one ROS current-view segmentation job per tool call."""

    def __init__(self, config: Sam3OneShotConfig | None = None) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = Sam3JobState.IDLE
        self._current_request_id: str | None = None
        self._last_result_json_path: str | None = None
        self._message = "SAM3 current-view job is idle."

    async def segment_current_view(
        self,
        *,
        text_prompt: str,
        frame_count: int = 3,
        confidence_threshold: float = 0.5,
        image_topic: str = DEFAULT_IMAGE_TOPIC,
        depth_image_topic: str | None = None,
        camera_calibration: CameraCalibrationInput | None = None,
        frame_timeout_sec: float = 10.0,
    ) -> Sam3CurrentViewResult:
        """Run one ROS node job, read the aggregate JSON, then let it exit."""

        _validate_request(
            text_prompt=text_prompt,
            frame_count=frame_count,
            confidence_threshold=confidence_threshold,
            image_topic=image_topic,
            depth_image_topic=depth_image_topic,
            frame_timeout_sec=frame_timeout_sec,
        )
        async with self._lock:
            config = self._resolve_config()
            request_id = str(uuid4())
            result_json_path = config.result_root / request_id / "result.json"
            command = (
                *config.command_prefix,
                "--request-id",
                request_id,
                "--image-topic",
                image_topic,
                "--prompt",
                text_prompt.strip(),
                "--confidence",
                repr(float(confidence_threshold)),
                "--frame-count",
                str(frame_count),
                "--frame-timeout-sec",
                repr(float(frame_timeout_sec)),
                "--result-json",
                str(result_json_path),
            )
            if depth_image_topic is not None:
                command += ("--depth-image-topic", depth_image_topic.strip())
            if camera_calibration is not None:
                command += (
                    "--camera-calibration-json",
                    camera_calibration.model_dump_json(),
                )

            try:
                self._state = Sam3JobState.RUNNING
                self._current_request_id = request_id
                self._last_result_json_path = str(result_json_path)
                self._message = "SAM3 current-view segmentation is running."
                self._process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=config.cwd,
                    env=config.environment,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=(os.name != "nt"),
                )
            except OSError as error:
                self._state = Sam3JobState.FAILED
                self._current_request_id = None
                self._message = "SAM3 current-view ROS node could not be started."
                raise Sam3RuntimeError(
                    Sam3ErrorCode.WORKER_EXITED,
                    self._message,
                ) from error

            process = self._process
            assert process is not None
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=config.job_timeout_sec,
                )
            except TimeoutError as error:
                await self._terminate_process(process, config)
                self._state = Sam3JobState.FAILED
                self._current_request_id = None
                self._message = (
                    f"SAM3 current-view job timed out after "
                    f"{config.job_timeout_sec:g} seconds."
                )
                raise Sam3RuntimeError(
                    Sam3ErrorCode.INFERENCE_TIMEOUT,
                    self._message,
                ) from error
            except asyncio.CancelledError:
                await self._terminate_process(process, config)
                self._state = Sam3JobState.CANCELED
                self._current_request_id = None
                self._message = "SAM3 current-view job was canceled."
                raise

            stderr_message = stderr.decode("utf-8", errors="replace").strip()
            stdout_message = stdout.decode("utf-8", errors="replace").strip()
            if process.returncode != 0:
                self._state = Sam3JobState.FAILED
                self._current_request_id = None
                self._message = _compact_message(
                    stderr_message or stdout_message or "SAM3 current-view job failed."
                )
                raise _result_or_process_error(result_json_path, self._message)

            try:
                result = _read_result_json(result_json_path)
            except Sam3RuntimeError as error:
                self._state = Sam3JobState.FAILED
                self._current_request_id = None
                self._message = error.message
                raise

            self._state = Sam3JobState.SUCCEEDED
            self._current_request_id = None
            self._message = result.message
            return result

    async def get_status(self) -> Sam3JobStatus:
        """Read the current or most recent one-shot job state."""

        self._refresh_state()
        return self._status()

    async def cancel(self) -> Sam3JobStatus:
        """Terminate the active one-shot job if it is still running."""

        self._refresh_state()
        if self._process is None or self._process.returncode is not None:
            self._state = Sam3JobState.IDLE
            self._current_request_id = None
            self._message = "No SAM3 current-view job is running."
            return self._status()

        await self._terminate_process(self._process, self._resolve_config())
        self._state = Sam3JobState.CANCELED
        self._current_request_id = None
        self._message = "SAM3 current-view job was canceled."
        return self._status()

    def _refresh_state(self) -> None:
        if (
            self._process is not None
            and self._process.returncode is not None
            and self._state == Sam3JobState.RUNNING
        ):
            self._state = (
                Sam3JobState.SUCCEEDED
                if self._process.returncode == 0
                else Sam3JobState.FAILED
            )
            self._current_request_id = None
            self._message = (
                "SAM3 current-view job completed."
                if self._process.returncode == 0
                else "SAM3 current-view job exited unexpectedly."
            )

    def _status(self) -> Sam3JobStatus:
        return Sam3JobStatus(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=(
                self._process.returncode if self._process is not None else None
            ),
            current_request_id=self._current_request_id,
            last_result_json_path=self._last_result_json_path,
            message=self._message,
        )

    def _resolve_config(self) -> Sam3OneShotConfig:
        if self._config is not None:
            return self._config
        try:
            self._config = Sam3OneShotConfig.from_env()
        except ValueError as error:
            raise Sam3RuntimeError(
                Sam3ErrorCode.MODEL_UNAVAILABLE,
                f"Invalid SAM3 one-shot configuration: {error}",
            ) from error
        return self._config

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        config: Sam3OneShotConfig,
    ) -> None:
        if process.returncode is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, ProcessLookupError):
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=config.termination_timeout_sec)
        except TimeoutError:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (OSError, ProcessLookupError):
                return
            await process.wait()


def _validate_request(
    *,
    text_prompt: str,
    frame_count: int,
    confidence_threshold: float,
    image_topic: str,
    depth_image_topic: str | None,
    frame_timeout_sec: float,
) -> None:
    if not text_prompt.strip():
        raise Sam3RuntimeError(Sam3ErrorCode.INVALID_INPUT, "text_prompt is required.")
    if frame_count <= 0:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "frame_count must be greater than zero.",
        )
    if (
        isinstance(confidence_threshold, bool)
        or not math.isfinite(float(confidence_threshold))
        or not 0.0 <= float(confidence_threshold) <= 1.0
    ):
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "confidence_threshold must be between 0.0 and 1.0.",
        )
    if not image_topic.strip() or not image_topic.startswith("/"):
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "image_topic must be an absolute ROS topic name.",
        )
    if depth_image_topic is not None and (
        not depth_image_topic.strip() or not depth_image_topic.startswith("/")
    ):
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "depth_image_topic must be an absolute ROS topic name.",
        )
    if not math.isfinite(frame_timeout_sec) or frame_timeout_sec <= 0.0:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "frame_timeout_sec must be greater than zero.",
        )


def _read_result_json(path: Path) -> Sam3CurrentViewResult:
    if not path.is_file():
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            f"SAM3 current-view result JSON was not written: {path}",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            f"SAM3 current-view result JSON is invalid: {path}",
        ) from error
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise _error_from_payload(payload)
    try:
        return Sam3CurrentViewResult.model_validate(payload)
    except ValidationError as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            f"SAM3 current-view result JSON does not match the MCP schema: {path}",
        ) from error


def _result_or_process_error(path: Path, process_message: str) -> Sam3RuntimeError:
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("ok") is False:
            return _error_from_payload(payload)
    return Sam3RuntimeError(Sam3ErrorCode.WORKER_EXITED, process_message)


def _error_from_payload(payload: dict[str, object]) -> Sam3RuntimeError:
    code_value = payload.get("error_code")
    message = payload.get("message")
    try:
        code = Sam3ErrorCode(str(code_value))
    except ValueError:
        code = Sam3ErrorCode.WORKER_EXITED
    if not isinstance(message, str) or not message:
        message = "SAM3 current-view job failed."
    return Sam3RuntimeError(code, message)


def _resolve_path(value: str, repository_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repository_root / path
    return path.resolve()


def _positive_timeout(value: str, variable: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a finite number.") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{variable} must be greater than zero.")
    return parsed


def _compact_message(message: str) -> str:
    return " ".join(message.split())[-1000:]
