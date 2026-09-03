"""On-demand SAM3 perception service over LCM RGB-D streams."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import lcm
from PIL import Image

from robot_runtime.perception.lcm_protocol import (
    COLOR_IMAGE_CHANNEL,
    DECODE_OK,
    DEPTH_IMAGE_CHANNEL,
    SAM3_REQUEST_CHANNEL,
    SAM3_REQUEST_SCHEMA,
    SAM3_RESPONSE_CHANNEL,
    DecodeImageResult,
    decode_image_message,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FRAME_TIMEOUT_SEC = 5.0
WORKER_TIMEOUT_SEC = 120.0
CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class ActiveRequest:
    request_id: str
    prompt: str
    started_at: float


class Sam3WorkerClient:
    """Own one SAM3 JSON-Lines worker and reuse its loaded model."""

    def __init__(self, capture_root: Path) -> None:
        self._capture_root = capture_root
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> dict[str, object]:
        worker_python = os.environ.get(
            "ROBOCLAW_SAM3_PYTHON",
            sys.executable,
        ).strip()
        worker_env = dict(os.environ)
        configured_roots = worker_env.get("ROBOCLAW_SAM3_INPUT_ROOTS", "").strip()
        roots = [str(self._capture_root)]
        if configured_roots:
            roots.extend(root for root in configured_roots.split(os.pathsep) if root)
        worker_env["ROBOCLAW_SAM3_INPUT_ROOTS"] = os.pathsep.join(roots)

        self._process = subprocess.Popen(
            (
                worker_python,
                "-m",
                "robot_runtime.perception.sam3",
                "serve",
            ),
            cwd=REPOSITORY_ROOT,
            env=worker_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        ready = _read_worker_message(self._process.stdout)
        if ready.get("event") != "ready":
            self.close()
            raise RuntimeError(_worker_error_message(ready))
        return ready

    def infer(
        self,
        request_id: str,
        image_path: Path,
        prompt: str,
    ) -> dict[str, object]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("SAM3 worker is not connected.")

        request = {
            "request_id": request_id,
            "image_path": str(image_path),
            "text_prompt": prompt,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
        }
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


class Sam3LcmService:
    """Collect the next RGB-D pair only while one target request is active."""

    def __init__(
        self,
        lc: lcm.LCM,
        worker: Sam3WorkerClient,
        capture_root: Path,
    ) -> None:
        self._lcm = lc
        self._worker = worker
        self._capture_root = capture_root
        self._active_request: ActiveRequest | None = None
        self._color: DecodeImageResult | None = None
        self._depth: DecodeImageResult | None = None
        self._lcm.subscribe(SAM3_REQUEST_CHANNEL, self._on_request)
        self._lcm.subscribe(COLOR_IMAGE_CHANNEL, self._on_color)
        self._lcm.subscribe(DEPTH_IMAGE_CHANNEL, self._on_depth)

    def expire_request(self) -> None:
        request = self._active_request
        if request is None or time.monotonic() - request.started_at < FRAME_TIMEOUT_SEC:
            return
        self._publish_error(
            request.request_id,
            "IMAGE_TIMEOUT",
            "Timed out waiting for one RGB-D image pair.",
        )
        self._reset_request()

    def _on_request(self, channel: str, data: bytes) -> None:
        del channel
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        request_id = payload.get("request_id")
        prompt = payload.get("prompt")
        if not isinstance(request_id, str):
            return
        if payload.get("schema") != SAM3_REQUEST_SCHEMA or not isinstance(prompt, str):
            self._publish_error(request_id, "INVALID_INPUT", "Invalid SAM3 request.")
            return
        if self._active_request is not None:
            self._publish_error(
                request_id,
                "BUSY",
                "SAM3 is processing another request.",
            )
            return

        self._active_request = ActiveRequest(request_id, prompt, time.monotonic())
        self._color = None
        self._depth = None

    def _on_color(self, channel: str, data: bytes) -> None:
        del channel
        if self._active_request is None or self._color is not None:
            return
        result = decode_image_message(data)
        if result.state == DECODE_OK:
            self._color = result
            self._infer_when_ready()

    def _on_depth(self, channel: str, data: bytes) -> None:
        del channel
        if self._active_request is None or self._depth is not None:
            return
        result = decode_image_message(data)
        if result.state == DECODE_OK:
            self._depth = result
            self._infer_when_ready()

    def _infer_when_ready(self) -> None:
        request = self._active_request
        color = self._color
        if request is None or color is None or self._depth is None:
            return

        try:
            with tempfile.TemporaryDirectory(
                prefix=f"{request.request_id}-",
                dir=self._capture_root,
            ) as temporary_directory:
                image_path = Path(temporary_directory) / "color.png"
                _decode_color_image(color).save(image_path, format="PNG")
                result = self._worker.infer(
                    request.request_id,
                    image_path,
                    request.prompt,
                )
            self._publish(
                {
                    "ok": True,
                    "request_id": request.request_id,
                    "pose_valid": False,
                    "frame_id": None,
                    "position_xyz": None,
                    "score": _best_score(result),
                    "message": (
                        "SAM3 segmented one RGB-D frame. Target pose is not yet "
                        "available because depth projection is not implemented."
                    ),
                }
            )
        except Exception as error:
            self._publish_error(request.request_id, "INFERENCE_FAILED", str(error))
        finally:
            self._reset_request()

    def _publish_error(self, request_id: str, code: str, message: str) -> None:
        self._publish(
            {
                "ok": False,
                "request_id": request_id,
                "error_code": code,
                "message": message,
            }
        )

    def _publish(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self._lcm.publish(SAM3_RESPONSE_CHANNEL, data)

    def _reset_request(self) -> None:
        self._active_request = None
        self._color = None
        self._depth = None


def main() -> int:
    capture_root = _capture_root()
    capture_root.mkdir(parents=True, exist_ok=True)
    worker = Sam3WorkerClient(capture_root)
    try:
        ready = worker.start()
        lc = lcm.LCM()
        service = Sam3LcmService(lc, worker, capture_root)
        _emit_stdout(
            {
                "ok": True,
                "message": "SAM3 model is loaded and the LCM service is ready.",
                "worker_pid": ready.get("pid"),
            }
        )
        while True:
            lc.handle_timeout(100)
            service.expire_request()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        _emit_stdout({"ok": False, "message": str(error)})
        return 1
    finally:
        worker.close()


def _capture_root() -> Path:
    configured = os.environ.get("ROBOCLAW_SAM3_CAPTURE_ROOT", "").strip()
    path = Path(configured) if configured else REPOSITORY_ROOT / "runtime_data/sam3/lcm"
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return path.expanduser().resolve()


def _decode_color_image(result: DecodeImageResult) -> Image.Image:
    assert result.header is not None
    assert result.image_bytes is not None
    width = int(result.header["width"])
    height = int(result.header["height"])
    step = int(result.header["step"])
    encoding = str(result.header["encoding"]).lower()
    modes = {
        "rgb8": ("RGB", "RGB"),
        "bgr8": ("RGB", "BGR"),
        "rgba8": ("RGBA", "RGBA"),
        "bgra8": ("RGBA", "BGRA"),
        "mono8": ("L", "L"),
    }
    if encoding not in modes:
        raise ValueError(f"Unsupported color encoding: {encoding}")
    mode, raw_mode = modes[encoding]
    image = Image.frombytes(
        mode,
        (width, height),
        result.image_bytes,
        "raw",
        raw_mode,
        step,
        1,
    )
    return image if image.mode == "RGB" else image.convert("RGB")


def _best_score(result: dict[str, object]) -> float | None:
    instances = result.get("instances")
    if not isinstance(instances, list):
        return None
    scores = [
        float(instance["score"])
        for instance in instances
        if isinstance(instance, dict)
        and isinstance(instance.get("score"), (int, float))
    ]
    return max(scores, default=None)


def _read_worker_message(stream: TextIO) -> dict[str, object]:
    ready, _, _ = select.select([stream], [], [], WORKER_TIMEOUT_SEC)
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


def _emit_stdout(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
