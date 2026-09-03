"""Manage the long-running SAM3 perception service from MCP tools."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from robot_runtime.perception.lcm_protocol import (
    SAM3_REQUEST_CHANNEL,
    SAM3_REQUEST_SCHEMA,
    SAM3_RESPONSE_CHANNEL,
)

from .models import (
    Sam3PerceptionState,
    Sam3PerceptionStatusResult,
    Sam3TargetObjectPoseErrorResult,
    Sam3TargetObjectPoseResult,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SERVICE_MODULE = "robot_runtime.perception.sam3.lcm_service"
DEFAULT_STARTUP_TIMEOUT_SEC = 120.0
DEFAULT_RPC_TIMEOUT_SEC = 30.0
DEFAULT_TERMINATION_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class Sam3PerceptionConfig:
    """Process and LCM settings for the SAM3 perception service."""

    command: tuple[str, ...]
    cwd: Path
    request_lcm_channel: str
    response_lcm_channel: str
    startup_timeout_sec: float = DEFAULT_STARTUP_TIMEOUT_SEC
    rpc_timeout_sec: float = DEFAULT_RPC_TIMEOUT_SEC
    termination_timeout_sec: float = DEFAULT_TERMINATION_TIMEOUT_SEC

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> Sam3PerceptionConfig:
        values = dict(os.environ if env is None else env)
        root = (repository_root or REPOSITORY_ROOT).resolve()
        python_executable = values.get(
            "ROBOCLAW_SAM3_SERVICE_PYTHON",
            sys.executable,
        ).strip()
        if not python_executable:
            raise ValueError("ROBOCLAW_SAM3_SERVICE_PYTHON cannot be blank.")
        return cls(
            command=(python_executable, "-m", DEFAULT_SERVICE_MODULE),
            cwd=root,
            request_lcm_channel=SAM3_REQUEST_CHANNEL,
            response_lcm_channel=SAM3_RESPONSE_CHANNEL,
        )


class _TargetPoseRpcError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.request_id = request_id
        super().__init__(message)


class _LcmResponseReceiver:
    """Receive the response that matches one target-pose request."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.response: dict[str, object] | None = None
        self.error: str | None = None

    def __call__(self, channel: str, data: bytes) -> None:
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.error = f"Received non-JSON response on {channel}."
            return
        if not isinstance(decoded, dict):
            self.error = f"Received non-object response on {channel}."
            return
        if decoded.get("request_id") == self.request_id:
            self.response = decoded


class Sam3PerceptionManager:
    """Lifecycle and RPC client for the SAM3 LCM perception service."""

    def __init__(self, config: Sam3PerceptionConfig | None = None) -> None:
        self._config = config
        self._lifecycle_lock = asyncio.Lock()
        self._rpc_lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = Sam3PerceptionState.STOPPED
        self._current_request_id: str | None = None
        self._last_request_id: str | None = None
        self._last_error: str | None = None
        self._message = "SAM3 perception service is stopped."

    async def start(self) -> Sam3PerceptionStatusResult:
        """Start the long-running SAM3 perception service process."""

        async with self._lifecycle_lock:
            self._refresh_state()
            if self._process is not None and self._process.returncode is None:
                self._state = Sam3PerceptionState.RUNNING
                self._message = "SAM3 perception service is already running."
                return self._status()

            try:
                config = self._resolve_config()
            except ValueError as error:
                self._state = Sam3PerceptionState.FAILED
                self._last_error = str(error)
                self._message = f"Invalid SAM3 perception configuration: {error}"
                return self._status()
            self._state = Sam3PerceptionState.STARTING
            self._message = "Starting SAM3 perception service."
            self._last_error = None
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *config.command,
                    cwd=config.cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=None,
                    start_new_session=True,
                )
            except OSError as error:
                self._state = Sam3PerceptionState.FAILED
                self._last_error = str(error)
                self._message = f"SAM3 perception service could not be started: {error}"
                return self._status()

            assert self._process.stdout is not None
            try: # 等待 SAM3 进程真正启动输出结果
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=config.startup_timeout_sec,
                )
                ready = json.loads(line.decode("utf-8")) if line else {}
            except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
                ready = {}
            if ready.get("ok") is not True:
                if self._process.returncode is None:
                    await self._terminate_process(
                        self._process,
                        config.termination_timeout_sec,
                    )
                self._state = Sam3PerceptionState.FAILED
                service_message = ready.get("message")
                self._message = (
                    service_message
                    if isinstance(service_message, str)
                    else (
                        "SAM3 perception service did not become ready before "
                        "the timeout."
                    )
                )
                self._last_error = self._message
                return self._status()

            self._state = Sam3PerceptionState.RUNNING
            self._message = (
                "SAM3 perception service process is running and listening for "
                "LCM target-pose requests."
            )
            return self._status()

    async def get_status(self) -> Sam3PerceptionStatusResult:
        """Read the service process state without sending perception requests."""

        self._refresh_state()
        return self._status()

    async def stop(self) -> Sam3PerceptionStatusResult:
        """Stop the long-running SAM3 perception service process."""

        async with self._lifecycle_lock:
            self._refresh_state()
            if self._process is not None and self._process.returncode is None:
                config = self._resolve_config()
                await self._terminate_process(
                    self._process,
                    config.termination_timeout_sec,
                )
            self._process = None
            self._state = Sam3PerceptionState.STOPPED
            self._current_request_id = None
            self._message = "SAM3 perception service is stopped."
            return self._status()

    async def get_target_object_pose(
        self,
        prompt: str,
    ) -> Sam3TargetObjectPoseResult | Sam3TargetObjectPoseErrorResult:
        """Call the SAM3 target-pose RPC through LCM."""

        try:
            config = self._resolve_config()
        except ValueError as error:
            rpc_error = _TargetPoseRpcError(
                "INVALID_CONFIGURATION",
                f"Invalid SAM3 perception configuration: {error}",
            )
            self._last_error = rpc_error.message
            return _error_result(rpc_error)
        try:
            prompt_text = _validate_prompt(prompt)
        except _TargetPoseRpcError as error:
            return _error_result(error)

        async with self._rpc_lock:
            self._refresh_state()
            if self._process is None or self._process.returncode is not None:
                error = _TargetPoseRpcError(
                    "SERVICE_NOT_RUNNING",
                    "SAM3 perception service is not running. Call "
                    "start_sam3_perception first.",
                )
                self._last_error = error.message
                return _error_result(error)

            request_id = str(uuid4())
            self._current_request_id = request_id
            self._last_request_id = request_id
            payload: dict[str, object] = {
                "schema": SAM3_REQUEST_SCHEMA,
                "request_id": request_id,
                "prompt": prompt_text,
            }
            try:
                response_payload = await asyncio.to_thread(
                    _perform_lcm_rpc,
                    config,
                    payload,
                    config.rpc_timeout_sec,
                )
                if response_payload["ok"] is not True:
                    error_result = Sam3TargetObjectPoseErrorResult.model_validate(
                        response_payload
                    )
                    self._last_error = error_result.message
                    return error_result
                result = Sam3TargetObjectPoseResult.model_validate(response_payload)
            except _TargetPoseRpcError as error:
                self._last_error = error.message
                return _error_result(error)
            finally:
                self._current_request_id = None
                self._refresh_state()

            self._last_error = None
            self._message = result.message
            return result

    def _resolve_config(self) -> Sam3PerceptionConfig:
        if self._config is None:
            self._config = Sam3PerceptionConfig.from_env()
        return self._config

    def _refresh_state(self) -> None:
        if self._process is None:
            if self._state != Sam3PerceptionState.FAILED:
                self._state = Sam3PerceptionState.STOPPED
            return
        if self._process.returncode is None:
            if self._state == Sam3PerceptionState.STARTING:
                return
            self._state = Sam3PerceptionState.RUNNING
            return
        if self._state != Sam3PerceptionState.STOPPED:
            self._state = Sam3PerceptionState.FAILED
            self._message = (
                "SAM3 perception service exited with code "
                f"{self._process.returncode}."
            )
            self._last_error = self._message

    def _status(self) -> Sam3PerceptionStatusResult:
        return Sam3PerceptionStatusResult(
            state=self._state,
            pid=self._process.pid if self._process is not None else None,
            return_code=(
                self._process.returncode if self._process is not None else None
            ),
            current_request_id=self._current_request_id,
            last_request_id=self._last_request_id,
            last_error=self._last_error,
            message=self._message,
        )

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        timeout_sec: float,
    ) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=timeout_sec,
            )
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()


def _perform_lcm_rpc(
    config: Sam3PerceptionConfig,
    payload: dict[str, object],
    timeout_sec: float,
) -> dict[str, object]:
    import lcm

    request_id = str(payload["request_id"])
    receiver = _LcmResponseReceiver(request_id)
    lc = lcm.LCM()

    subscription = lc.subscribe(config.response_lcm_channel, receiver)
    try:
        request_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        lc.publish(config.request_lcm_channel, request_bytes)  # 发送 RPC 请求
        deadline = time.monotonic() + timeout_sec
        while receiver.response is None and receiver.error is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if lc.handle_timeout(max(1, int(remaining * 1000))) == 0:
                break
    except Exception as error:
        raise _TargetPoseRpcError(
            "RPC_TRANSPORT_ERROR",
            f"SAM3 target-pose LCM RPC failed: {error}",
            request_id,
        ) from error
    finally:
        lc.unsubscribe(subscription)

    if receiver.response is not None:
        return receiver.response
    if receiver.error is not None:
        raise _TargetPoseRpcError(
            "INVALID_RESPONSE",
            receiver.error,
            request_id,
        )
    raise _TargetPoseRpcError(
        "RPC_TIMEOUT",
        (
            f"SAM3 target-pose RPC timed out after {timeout_sec:g} seconds on "
            f"{config.response_lcm_channel}."
        ),
        request_id,
    )


def _validate_prompt(prompt: str) -> str:
    text = prompt.strip()
    if not text:
        raise _TargetPoseRpcError("INVALID_INPUT", "prompt is required.")
    if len(text) > 256:
        raise _TargetPoseRpcError(
            "INVALID_INPUT",
            "prompt must be at most 256 characters.",
        )
    return text


def _error_result(error: _TargetPoseRpcError) -> Sam3TargetObjectPoseErrorResult:
    return Sam3TargetObjectPoseErrorResult(
        error_code=error.error_code,
        message=error.message,
        request_id=error.request_id,
    )
