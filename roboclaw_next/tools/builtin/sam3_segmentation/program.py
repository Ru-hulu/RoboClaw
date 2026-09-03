"""Manage the long-running SAM3 perception service from MCP tools."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import (
    Sam3PerceptionState,
    Sam3PerceptionStatusResult,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SERVICE_MODULE = "robot_runtime.perception.sam3.lcm_service"
DEFAULT_STARTUP_TIMEOUT_SEC = 120.0
DEFAULT_TERMINATION_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class Sam3PerceptionConfig:
    """Process settings for the SAM3 perception service."""

    command: tuple[str, ...]
    cwd: Path
    startup_timeout_sec: float = DEFAULT_STARTUP_TIMEOUT_SEC
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
        )


class Sam3PerceptionManager:
    """Manage the lifecycle of the SAM3 perception service process."""

    def __init__(self, config: Sam3PerceptionConfig | None = None) -> None:
        self._config = config
        self._lifecycle_lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._state = Sam3PerceptionState.STOPPED
        self._model_loaded = False
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

            self._model_loaded = False
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
            # 等待 Service 确认 SAM3 模型已经完成加载。
            try:
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
            self._model_loaded = True
            self._message = "SAM3 perception service is running."
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
            self._model_loaded = False
            self._message = "SAM3 perception service is stopped."
            return self._status()

    def _resolve_config(self) -> Sam3PerceptionConfig:
        if self._config is None:
            self._config = Sam3PerceptionConfig.from_env()
        return self._config

    def _refresh_state(self) -> None:
        if self._process is None:
            self._model_loaded = False
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
            self._model_loaded = False
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
            model_loaded=self._model_loaded,
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
