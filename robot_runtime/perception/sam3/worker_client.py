"""Client for the isolated SAM3 JSON-Lines worker process."""

from __future__ import annotations

import base64
import json
import os
import select
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from robot_runtime.perception.lcm_protocol import DECODE_OK, DecodeImageResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKER_RESPONSE_TIMEOUT_SEC = 120.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.5


class Sam3WorkerClient:
    """Start one SAM3 worker and exchange JSON-Lines messages with it."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> None:
        worker_python = os.environ.get(
            "ROBOCLAW_SAM3_PYTHON",
            sys.executable,
        ).strip()
        if not worker_python:
            raise RuntimeError("ROBOCLAW_SAM3_PYTHON cannot be blank.")
        # /Users/hongru/paper_project/RoboClaw/robot_runtime/perception/sam3/__main__.py
        # 实际上对应的就是sam3的worker
        self._process = subprocess.Popen(
            (
                worker_python,
                "-m",
                "robot_runtime.perception.sam3",
                "serve",
            ),
            cwd=REPOSITORY_ROOT,
            env=dict(os.environ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        try:
            ready = _read_worker_message(self._process.stdout)
            if ready.get("event") != "ready":
                raise RuntimeError(_worker_error_message(ready))
        except Exception:
            self.close()
            raise

    def infer_frame(
        self,
        request_id: str,
        frame: DecodeImageResult,
        prompt: str,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> dict[str, object]:
        """Send one decoded in-memory LCM color frame to the worker."""

        if (
            frame.state != DECODE_OK
            or frame.header is None
            or frame.image_bytes is None
        ):
            raise ValueError("SAM3 requires one valid decoded color frame.")

        request = {
            "request_id": request_id,
            "image_frame": {
                "width": frame.header["width"],
                "height": frame.header["height"],
                "step": frame.header["step"],
                "encoding": frame.header["encoding"],
                "data_base64": base64.b64encode(frame.image_bytes).decode("ascii"),
            },
            "text_prompt": prompt,
            "confidence_threshold": confidence_threshold,
        }
        return self._send_request(request_id, request)

    def _send_request(
        self,
        request_id: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("SAM3 worker is not connected.")

        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response = _read_worker_message(process.stdout)
        if response.get("request_id") != request_id:
            raise RuntimeError("SAM3 worker returned a mismatched request_id.")
        if response.get("ok") is not True:
            raise RuntimeError(_worker_error_message(response))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("SAM3 worker response is missing its result.")
        return result

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _read_worker_message(stream: TextIO) -> dict[str, object]:
    ready, _, _ = select.select([stream], [], [], WORKER_RESPONSE_TIMEOUT_SEC)
    if not ready:
        raise RuntimeError("SAM3 worker response timed out.")
    line = stream.readline()
    if not line:
        raise RuntimeError("SAM3 worker exited without a response.")
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise RuntimeError("SAM3 worker response must be a JSON object.")
    return payload


def _worker_error_message(payload: dict[str, object]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return str(error["message"])
    return "SAM3 worker failed."
