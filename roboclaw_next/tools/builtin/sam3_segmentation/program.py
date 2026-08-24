"""Lifecycle management for the lazy SAM3 GPU worker process."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import sys
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from robot_runtime.perception.sam3.errors import Sam3ErrorCode, Sam3RuntimeError

from .models import Sam3SegmentationResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
LOGGER = logging.getLogger(__name__)
DEFAULT_IDLE_TIMEOUT_SEC = 120.0
DEFAULT_TERMINATION_TIMEOUT_SEC = 5.0
MAX_PROTOCOL_MESSAGE_BYTES = 4 * 1024 * 1024


class Sam3WorkerState(StrEnum):
    """Lifecycle states exposed by the SAM3 manager."""

    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"


@dataclass(frozen=True)
class Sam3ManagerConfig:
    """Process-level settings that do not import the SAM3 runtime environment."""

    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    idle_timeout_sec: float = 120.0
    request_timeout_sec: float = 120.0
    termination_timeout_sec: float = 5.0

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> Sam3ManagerConfig:
        values = dict(os.environ if env is None else env)
        root = (repository_root or REPOSITORY_ROOT).resolve()
        python_executable = values.get(
            "ROBOCLAW_SAM3_PYTHON",
            sys.executable,
        ).strip()
        if not python_executable:
            raise ValueError("ROBOCLAW_SAM3_PYTHON cannot be blank.")
        return cls(
            command=(
                python_executable,
                "-m",
                "robot_runtime.perception.sam3",
                "serve",
            ),
            cwd=root,
            environment=values,
            idle_timeout_sec=_positive_timeout(
                values.get("ROBOCLAW_SAM3_IDLE_TIMEOUT_SEC", "120"),
                "ROBOCLAW_SAM3_IDLE_TIMEOUT_SEC",
            ),
            request_timeout_sec=_positive_timeout(
                values.get("ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC", "120"),
                "ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC",
            ),
        )


@dataclass(frozen=True)
class Sam3WorkerStatus:
    """Compact process state returned by status and unload tools."""

    state: Sam3WorkerState
    pid: int | None
    current_request_id: str | None
    last_activity_at: str | None
    idle_timeout_sec: float
    load_duration_ms: float | None
    message: str


class Sam3WorkerProcessManager:
    """Start, serialize requests to, and evict one SAM3 worker process."""

    def __init__(self, config: Sam3ManagerConfig | None = None) -> None:
        self._config = config
        self._request_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = Sam3WorkerState.STOPPED
        self._current_request_id: str | None = None
        self._last_activity_at: str | None = None
        self._load_duration_ms: float | None = None
        self._message = "SAM3 worker is not running."
        self._idle_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=100)
        self._activity_generation = 0

    async def infer(
        self,
        image_path: str,
        text_prompt: str,
        confidence_threshold: float = 0.5,
    ) -> dict[str, object]:
        """Run one serialized request, starting the worker when necessary."""

        async with self._request_lock:
            config = self._resolve_config()
            process = await self._ensure_worker()

            try:
                async with self._state_lock:
                    if self._process is not process:
                        raise Sam3RuntimeError(
                            Sam3ErrorCode.WORKER_EXITED,
                            "SAM3 worker was stopped before inference started.",
                        )
                    assert process.stdin is not None
                    assert process.stdout is not None
                    self._cancel_idle_locked()
                    request_id = str(uuid4())
                    self._state = Sam3WorkerState.BUSY
                    self._current_request_id = request_id
                    self._message = "SAM3 inference is running."
                payload = {
                    "request_id": request_id,
                    "image_path": image_path,
                    "text_prompt": text_prompt,
                    "confidence_threshold": confidence_threshold,
                }
                process.stdin.write(
                    (json.dumps(payload, separators=(",", ":")) + "\n").encode(
                        "utf-8"
                    )
                )
                await process.stdin.drain()
                response = await _read_worker_message(
                    process.stdout,
                    timeout_sec=config.request_timeout_sec,
                )
                if response.get("request_id") != request_id:
                    raise Sam3RuntimeError(
                        Sam3ErrorCode.WORKER_EXITED,
                        "SAM3 worker response request_id did not match the active request.",
                    )
                if response.get("ok") is not True:
                    raise _worker_error(response)
                result = response.get("result")
                if not isinstance(result, dict):
                    raise Sam3RuntimeError(
                        Sam3ErrorCode.WORKER_EXITED,
                        "SAM3 worker returned a success response without a result object.",
                    )
                result = dict(result)
                result["worker_pid"] = process.pid
                result.setdefault("model_load_duration_ms", self._load_duration_ms)
                try:
                    Sam3SegmentationResult.model_validate({"ok": True, **result})
                except ValidationError as error:
                    raise Sam3RuntimeError(
                        Sam3ErrorCode.WORKER_EXITED,
                        "SAM3 worker returned an invalid success result.",
                    ) from error
                async with self._state_lock:
                    if self._process is not process:
                        raise Sam3RuntimeError(
                            Sam3ErrorCode.WORKER_EXITED,
                            "SAM3 worker was stopped before its result was accepted.",
                        )
                    self._mark_ready_locked("SAM3 inference completed.")
            except asyncio.CancelledError:
                await self._stop_after_cancellation(
                    process,
                    "SAM3 worker stopped after request cancellation.",
                )
                raise
            except TimeoutError as error:
                await self._stop_process(
                    process,
                    "SAM3 worker stopped after request timeout.",
                )
                raise Sam3RuntimeError(
                    Sam3ErrorCode.INFERENCE_TIMEOUT,
                    "SAM3 inference exceeded the configured request timeout.",
                ) from error
            except (BrokenPipeError, ConnectionError) as error:
                await self._stop_process(
                    process,
                    "SAM3 worker pipe closed unexpectedly.",
                )
                raise Sam3RuntimeError(
                    Sam3ErrorCode.WORKER_EXITED,
                    "SAM3 worker exited before returning a result.",
                ) from error
            except Sam3RuntimeError as error:
                if error.code in {
                    Sam3ErrorCode.WORKER_EXITED,
                    Sam3ErrorCode.GPU_OOM,
                    Sam3ErrorCode.MODEL_UNAVAILABLE,
                }:
                    await self._stop_process(
                        process,
                        f"SAM3 worker stopped after {error.code.value}."
                    )
                else:
                    async with self._state_lock:
                        if self._process is process:
                            self._mark_ready_locked(
                                "SAM3 worker rejected the request."
                            )
                raise

            return result

    async def get_status(self) -> Sam3WorkerStatus:
        """Read lifecycle state without starting the worker."""

        async with self._state_lock:
            if self._process is not None and self._process.returncode is not None:
                await self._stop_locked("SAM3 worker exited unexpectedly.")
            return self._status_locked()

    async def unload(self) -> Sam3WorkerStatus:
        """Stop the worker and release model VRAM; repeated calls are safe."""

        async with self._state_lock:
            if self._process is None:
                self._state = Sam3WorkerState.STOPPED
                self._message = "SAM3 worker is not running."
                self._cancel_idle_locked()
            else:
                await self._stop_locked("SAM3 worker unloaded explicitly.")
            return self._status_locked()

    async def _ensure_worker(self) -> asyncio.subprocess.Process:
        config = self._resolve_config()
        process: asyncio.subprocess.Process | None = None
        try:
            async with self._state_lock:
                if self._process is not None and self._process.returncode is None:
                    if self._state in {
                        Sam3WorkerState.READY,
                        Sam3WorkerState.BUSY,
                    }:
                        return self._process
                if self._process is not None:
                    await self._stop_locked("Discarded an exited SAM3 worker.")

                self._state = Sam3WorkerState.STARTING
                self._message = "SAM3 worker is loading the model."
                subprocess_options: dict[str, Any] = {}
                if os.name != "nt":
                    subprocess_options["start_new_session"] = True
                process = await asyncio.create_subprocess_exec(
                    *config.command,
                    cwd=config.cwd,
                    env=config.environment,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=MAX_PROTOCOL_MESSAGE_BYTES,
                    **subprocess_options,
                )
                self._process = process
                assert process.stderr is not None
                self._stderr_tail.clear()
                self._stderr_task = asyncio.create_task(
                    self._drain_stderr(process.stderr)
                )
        except asyncio.CancelledError:
            await self._stop_after_cancellation(
                process,
                "SAM3 worker stopped after startup cancellation.",
            )
            raise
        except OSError as error:
            async with self._state_lock:
                self._state = Sam3WorkerState.STOPPED
                self._message = "SAM3 worker could not be started."
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker process could not be started.",
            ) from error

        assert process is not None
        assert process.stdout is not None
        try:
            ready = await _read_worker_message(
                process.stdout,
                timeout_sec=config.request_timeout_sec,
            )
        except asyncio.CancelledError:
            await self._stop_after_cancellation(
                process,
                "SAM3 worker stopped after startup cancellation.",
            )
            raise
        except TimeoutError as error:
            await self._stop_process(
                process,
                "SAM3 worker stopped after startup timeout.",
            )
            raise Sam3RuntimeError(
                Sam3ErrorCode.INFERENCE_TIMEOUT,
                "SAM3 worker model load exceeded the configured request timeout.",
            ) from error
        except Sam3RuntimeError:
            await self._stop_process(
                process,
                "SAM3 worker emitted an invalid startup response.",
            )
            raise

        if ready.get("event") == "startup_error":
            error = _worker_error(ready)
            await self._stop_process(
                process,
                f"SAM3 worker startup failed with {error.code.value}."
            )
            raise error
        if ready.get("event") != "ready":
            await self._stop_process(
                process,
                "SAM3 worker did not emit a ready event.",
            )
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker did not emit the required ready event.",
            )
        duration = ready.get("load_duration_ms")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or float(duration) < 0.0
        ):
            await self._stop_process(
                process,
                "SAM3 worker emitted an invalid ready event.",
            )
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker ready event did not contain a valid load duration.",
            )
        async with self._state_lock:
            if self._process is not process:
                raise Sam3RuntimeError(
                    Sam3ErrorCode.WORKER_EXITED,
                    "SAM3 worker was stopped while loading the model.",
                )
            self._load_duration_ms = float(duration)
            self._state = Sam3WorkerState.READY
            self._last_activity_at = _now_iso()
            self._message = "SAM3 worker is ready."
        return process

    async def _stop_process(
        self,
        process: asyncio.subprocess.Process | None,
        message: str,
    ) -> None:
        async with self._state_lock:
            if process is not None and self._process is not process:
                return
            await self._stop_locked(message)

    async def _stop_after_cancellation(
        self,
        process: asyncio.subprocess.Process | None,
        message: str,
    ) -> None:
        cleanup = asyncio.create_task(self._stop_process(process, message))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup

    def _mark_ready_locked(self, message: str) -> None:
        self._state = Sam3WorkerState.READY
        self._current_request_id = None
        self._last_activity_at = _now_iso()
        self._message = message
        self._activity_generation += 1
        generation = self._activity_generation
        self._cancel_idle_locked()
        self._idle_task = asyncio.create_task(self._evict_after_idle(generation))

    async def _evict_after_idle(self, generation: int) -> None:
        try:
            await asyncio.sleep(self._idle_timeout_sec)
            async with self._state_lock:
                if (
                    generation == self._activity_generation
                    and self._state == Sam3WorkerState.READY
                ):
                    await self._stop_locked(
                        "SAM3 worker stopped after the idle timeout."
                    )
        except asyncio.CancelledError:
            return

    async def _stop_locked(self, message: str) -> None:
        self._cancel_idle_locked()
        process = self._process
        if process is not None and process.returncode is None:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=self._termination_timeout_sec,
                )
            except TimeoutError:
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except (OSError, ProcessLookupError):
                    pass
                await process.wait()

        stderr_task = self._stderr_task
        self._stderr_task = None
        if stderr_task is not None and stderr_task is not asyncio.current_task():
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task
        self._process = None
        self._state = Sam3WorkerState.STOPPED
        self._current_request_id = None
        self._load_duration_ms = None
        self._last_activity_at = _now_iso()
        self._message = message

    def _cancel_idle_locked(self) -> None:
        idle_task = self._idle_task
        self._idle_task = None
        if idle_task is not None and idle_task is not asyncio.current_task():
            idle_task.cancel()

    async def _drain_stderr(
        self,
        stream: asyncio.StreamReader,
    ) -> None:
        while line := await stream.readline():
            decoded = line.decode("utf-8", errors="replace").rstrip()
            self._stderr_tail.append(decoded)
            sanitized = "".join(
                character if character >= " " or character == "\t" else "�"
                for character in decoded
            )[:2000]
            LOGGER.warning("SAM3 worker stderr: %s", sanitized)

    def _status_locked(self) -> Sam3WorkerStatus:
        return Sam3WorkerStatus(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            current_request_id=self._current_request_id,
            last_activity_at=self._last_activity_at,
            idle_timeout_sec=self._idle_timeout_sec,
            load_duration_ms=self._load_duration_ms,
            message=self._message,
        )

    def _resolve_config(self) -> Sam3ManagerConfig:
        if self._config is not None:
            return self._config
        try:
            self._config = Sam3ManagerConfig.from_env()
        except ValueError as error:
            raise Sam3RuntimeError(
                Sam3ErrorCode.MODEL_UNAVAILABLE,
                f"Invalid SAM3 manager configuration: {error}",
            ) from error
        return self._config

    @property
    def _idle_timeout_sec(self) -> float:
        if self._config is None:
            return DEFAULT_IDLE_TIMEOUT_SEC
        return self._config.idle_timeout_sec

    @property
    def _termination_timeout_sec(self) -> float:
        if self._config is None:
            return DEFAULT_TERMINATION_TIMEOUT_SEC
        return self._config.termination_timeout_sec


def _decode_worker_message(raw_message: bytes) -> dict[str, object]:
    if not raw_message:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker exited without returning a protocol message.",
        )
    try:
        payload = json.loads(raw_message.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker returned malformed JSON.",
        ) from error
    if not isinstance(payload, dict):
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker protocol message must be a JSON object.",
        )
    return payload


async def _read_worker_message(
    stream: asyncio.StreamReader,
    *,
    timeout_sec: float,
) -> dict[str, object]:
    try:
        raw_message = await asyncio.wait_for(
            stream.readline(),
            timeout=timeout_sec,
        )
    except TimeoutError:
        raise
    except (OSError, ValueError) as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker protocol message exceeded the size limit or could not be read.",
        ) from error
    return _decode_worker_message(raw_message)


def _worker_error(payload: dict[str, object]) -> Sam3RuntimeError:
    error_payload = payload.get("error")
    if not isinstance(error_payload, dict):
        return Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker returned an invalid error response.",
        )
    code_value = error_payload.get("code")
    message = error_payload.get("message")
    try:
        code = Sam3ErrorCode(str(code_value))
    except ValueError:
        code = Sam3ErrorCode.WORKER_EXITED
    if not isinstance(message, str) or not message:
        message = "SAM3 worker returned an error without a recovery message."
    return Sam3RuntimeError(code, message)


def _positive_timeout(value: str, variable: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a finite number.") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{variable} must be greater than zero.")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
