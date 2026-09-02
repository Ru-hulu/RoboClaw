"""One-shot ROS 2 node that segments a few frames from a camera topic."""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO
from uuid import uuid4

import numpy as np
from PIL import Image

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image as RosImage

from .errors import Sam3ErrorCode, Sam3RuntimeError


SUPPORTED_ENCODINGS = {
    "rgb8": 3,
    "bgr8": 3,
    "rgba8": 4,
    "bgra8": 4,
    "mono8": 1,
}
IDENTITY_MATRIX_4X4 = [
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]


class Sam3CurrentViewNode(Node):
    """Capture ROS image frames and ask one local SAM3 worker to segment them."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        super().__init__("sam3_current_view")
        self.arguments = arguments
        self.result_json_path = Path(arguments.result_json).expanduser().resolve()
        self.run_directory = self.result_json_path.parent
        self.frame_directory = self.run_directory / "frames"
        self.worker_stderr_path = self.run_directory / "worker_stderr.log"
        self.frames: list[dict[str, object]] = []
        self.error: Sam3RuntimeError | None = None
        self.worker: subprocess.Popen[str] | None = None
        self._worker_stderr_file: TextIO | None = None
        self.worker_pid: int | None = None
        self.model_load_duration_ms: float | None = None

        self.run_directory.mkdir(parents=True, exist_ok=True)
        self.frame_directory.mkdir(parents=True, exist_ok=True)
        self._start_worker()
        self.subscription = self.create_subscription(
            RosImage,
            arguments.image_topic,
            self._image_callback,
            10,
        )
        self.get_logger().info(
            f"SAM3 model ready; collecting {arguments.frame_count} frame(s) from "
            f"{arguments.image_topic}."
        )

    @property
    def finished(self) -> bool:
        return self.error is not None or len(self.frames) >= self.arguments.frame_count

    def _start_worker(self) -> None:
        worker_python = os.environ.get("ROBOCLAW_SAM3_PYTHON", sys.executable).strip()
        if not worker_python:
            raise Sam3RuntimeError(
                Sam3ErrorCode.MODEL_UNAVAILABLE,
                "ROBOCLAW_SAM3_PYTHON cannot be blank.",
            )
        worker_env = dict(os.environ)
        input_roots = [str(self.run_directory)]
        configured_roots = worker_env.get("ROBOCLAW_SAM3_INPUT_ROOTS", "").strip()
        if configured_roots:
            input_roots.extend(
                item for item in configured_roots.split(os.pathsep) if item
            )
        worker_env["ROBOCLAW_SAM3_INPUT_ROOTS"] = os.pathsep.join(input_roots)
        command = (
            worker_python,
            "-m",
            "robot_runtime.perception.sam3",
            "serve",
        )

        stderr_file = self.worker_stderr_path.open("w", encoding="utf-8")
        try:
            self._worker_stderr_file = stderr_file
            self.worker = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[3],
                env=worker_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                bufsize=1,
                start_new_session=(os.name != "nt"),
            )
        except OSError as error:
            self._worker_stderr_file = None
            stderr_file.close()
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker process could not be started.",
            ) from error

        try:
            assert self.worker.stdout is not None
            ready = _read_worker_message(
                self.worker.stdout,
                timeout_sec=self.arguments.worker_timeout_sec,
            )
            if ready.get("event") == "startup_error":
                raise _worker_error(ready)
            if ready.get("event") != "ready":
                raise Sam3RuntimeError(
                    Sam3ErrorCode.WORKER_EXITED,
                    "SAM3 worker did not emit the required ready event.",
                )
        except Sam3RuntimeError:
            self.stop_worker()
            raise
        worker_pid = ready.get("pid")
        load_duration = ready.get("load_duration_ms")
        if (
            isinstance(worker_pid, bool)
            or not isinstance(worker_pid, int)
            or worker_pid <= 0
        ):
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker ready event did not contain a valid pid.",
            )
        if (
            isinstance(load_duration, bool)
            or not isinstance(load_duration, (int, float))
            or not math.isfinite(float(load_duration))
            or float(load_duration) < 0.0
        ):
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker ready event did not contain a valid load duration.",
            )
        self.worker_pid = worker_pid
        self.model_load_duration_ms = float(load_duration)

    def _image_callback(self, message: RosImage) -> None:
        if self.finished:
            return
        frame_index = len(self.frames)
        try:
            image = _ros_image_to_pil(message)
            captured_image_path = self.frame_directory / f"frame_{frame_index:03d}.png"
            image.save(captured_image_path, format="PNG")
            result = self._infer_frame(captured_image_path)
            self.frames.append(
                {
                    "frame_index": frame_index,
                    "frame_id": message.header.frame_id,
                    "stamp_sec": int(message.header.stamp.sec),
                    "stamp_nanosec": int(message.header.stamp.nanosec),
                    "captured_image_path": str(captured_image_path),
                    "image_width": result["image_width"],
                    "image_height": result["image_height"],
                    "inference_duration_ms": result["inference_duration_ms"],
                    "instance_count": result["instance_count"],
                    "instances": result["instances"],
                    "result_json_path": result["result_json_path"],
                    "masks_npz_path": result["masks_npz_path"],
                    "overlay_path": result["overlay_path"],
                }
            )
        except Sam3RuntimeError as error:
            self.error = error
        except Exception as error:
            self.error = Sam3RuntimeError(
                Sam3ErrorCode.MODEL_UNAVAILABLE,
                f"SAM3 current-view frame processing failed: {error}",
            )

    def _infer_frame(self, image_path: Path) -> dict[str, object]:
        if self.worker is None or self.worker.stdin is None or self.worker.stdout is None:
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker is not connected.",
            )
        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "image_path": str(image_path),
            "text_prompt": self.arguments.prompt,
            "confidence_threshold": self.arguments.confidence,
        }
        # ROS 节点通过 stdin pipe 把当前帧路径和 prompt 发给 SAM3 worker；
        # worker.py 的 `for raw_line in input_stream` 会接住这行 JSON。
        self.worker.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.worker.stdin.flush()
        response = _read_worker_message(
            self.worker.stdout,
            timeout_sec=self.arguments.worker_timeout_sec,
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
        return result

    def build_result(self) -> dict[str, object]:
        if self.worker_pid is None or self.model_load_duration_ms is None:
            raise Sam3RuntimeError(
                Sam3ErrorCode.WORKER_EXITED,
                "SAM3 worker did not finish startup.",
            )
        best_frame_index, best_instance_index, best_score = _best_detection(self.frames)
        model_revision = ""
        checkpoint_sha256 = ""
        for frame in self.frames:
            frame_result_path = Path(str(frame["result_json_path"]))
            payload = json.loads(frame_result_path.read_text(encoding="utf-8"))
            model_revision = str(payload.get("model_revision", ""))
            checkpoint_sha256 = str(payload.get("checkpoint_sha256", ""))
            if model_revision and checkpoint_sha256:
                break
        return {
            "ok": True,
            "schema_version": 2,
            "request_id": self.arguments.request_id,
            "image_topic": self.arguments.image_topic,
            "depth_image_topic": self.arguments.depth_image_topic,
            "camera_calibration": self.arguments.camera_calibration,
            "text_prompt": self.arguments.prompt,
            "confidence_threshold": self.arguments.confidence,
            "requested_frame_count": self.arguments.frame_count,
            "processed_frame_count": len(self.frames),
            "node_pid": os.getpid(),
            "worker_pid": self.worker_pid,
            "model_load_duration_ms": self.model_load_duration_ms,
            "model_revision": model_revision,
            "checkpoint_sha256": checkpoint_sha256,
            "result_json_path": str(self.result_json_path),
            "frames": self.frames,
            "best_frame_index": best_frame_index,
            "best_instance_index": best_instance_index,
            "best_score": best_score,
            "target_object_pose_valid": False,
            "target_object_pose_matrix": list(IDENTITY_MATRIX_4X4),
            "message": (
                f"SAM3 segmented {len(self.frames)} frame(s) from "
                f"{self.arguments.image_topic}."
            ),
        }

    def stop_worker(self) -> None:
        worker = self.worker
        self.worker = None
        stderr_file = self._worker_stderr_file
        self._worker_stderr_file = None
        try:
            if worker is None or worker.poll() is not None:
                return
            try:
                if os.name != "nt":
                    os.killpg(worker.pid, signal.SIGTERM)
                else:
                    worker.terminate()
            except (OSError, ProcessLookupError):
                return
            try:
                worker.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(worker.pid, signal.SIGKILL)
                else:
                    worker.kill()
                worker.wait()
        finally:
            if stderr_file is not None:
                stderr_file.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    rclpy.init()
    node: Sam3CurrentViewNode | None = None
    try:
        node = Sam3CurrentViewNode(arguments)
        deadline = time.monotonic() + arguments.frame_timeout_sec
        while rclpy.ok() and not node.finished:
            if time.monotonic() >= deadline:
                raise Sam3RuntimeError(
                    Sam3ErrorCode.INFERENCE_TIMEOUT,
                    f"No complete SAM3 frame set arrived on {arguments.image_topic}.",
                )
            rclpy.spin_once(node, timeout_sec=0.1)
        if node.error is not None:
            raise node.error
        result = node.build_result()
        _write_json_atomic(node.result_json_path, result)
        _emit_stdout({"ok": True, "result_json_path": str(node.result_json_path)})
        return 0
    except Sam3RuntimeError as error:
        result_path = Path(arguments.result_json).expanduser().resolve()
        _write_json_atomic(result_path, _failure_payload(arguments, error))
        _emit_stdout({"ok": False, "result_json_path": str(result_path)})
        return 1
    finally:
        if node is not None:
            node.stop_worker()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-shot SAM3 current-view node")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--depth-image-topic", default="")
    parser.add_argument("--camera-calibration-json", default="")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--confidence", type=float, required=True)
    parser.add_argument("--frame-count", type=int, required=True)
    parser.add_argument("--frame-timeout-sec", type=float, required=True)
    parser.add_argument("--worker-timeout-sec", type=float, default=120.0)
    parser.add_argument("--result-json", required=True)
    arguments = parser.parse_args(argv)
    if not arguments.prompt.strip():
        parser.error("--prompt is required")
    if not arguments.image_topic.startswith("/"):
        parser.error("--image-topic must be an absolute ROS topic name")
    arguments.depth_image_topic = arguments.depth_image_topic.strip() or None
    if (
        arguments.depth_image_topic is not None
        and not arguments.depth_image_topic.startswith("/")
    ):
        parser.error("--depth-image-topic must be an absolute ROS topic name")
    arguments.camera_calibration = _parse_camera_calibration_json(
        arguments.camera_calibration_json,
        parser,
    )
    if arguments.frame_count <= 0:
        parser.error("--frame-count must be greater than zero")
    if not math.isfinite(arguments.confidence) or not 0.0 <= arguments.confidence <= 1.0:
        parser.error("--confidence must be between 0.0 and 1.0")
    if not math.isfinite(arguments.frame_timeout_sec) or arguments.frame_timeout_sec <= 0:
        parser.error("--frame-timeout-sec must be greater than zero")
    if not math.isfinite(arguments.worker_timeout_sec) or arguments.worker_timeout_sec <= 0:
        parser.error("--worker-timeout-sec must be greater than zero")
    return arguments


def _parse_camera_calibration_json(
    value: str,
    parser: argparse.ArgumentParser,
) -> dict[str, object] | None:
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        parser.error("--camera-calibration-json must be valid JSON")
    if not isinstance(payload, dict):
        parser.error("--camera-calibration-json must be a JSON object")
    return {
        "intrinsic_matrix": _read_matrix(payload, "intrinsic_matrix", 9, parser),
        "extrinsic_matrix": _read_matrix(payload, "extrinsic_matrix", 16, parser),
    }


def _read_matrix(
    payload: dict[str, object],
    key: str,
    expected_size: int,
    parser: argparse.ArgumentParser,
) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) != expected_size:
        parser.error(f"--camera-calibration-json {key} must contain {expected_size} values")
    matrix: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            parser.error(f"--camera-calibration-json {key} values must be numbers")
        number = float(item)
        if not math.isfinite(number):
            parser.error(f"--camera-calibration-json {key} values must be finite")
        matrix.append(number)
    return matrix


def _ros_image_to_pil(message: RosImage) -> Image.Image:
    encoding = message.encoding.lower()
    channels = SUPPORTED_ENCODINGS.get(encoding)
    if channels is None:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            f"Unsupported ROS image encoding: {message.encoding}",
        )
    if message.height <= 0 or message.width <= 0:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "ROS image has invalid dimensions.",
        )
    expected_row_bytes = message.width * channels
    if message.step < expected_row_bytes:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "ROS image step is smaller than the encoded row width.",
        )
    data = np.frombuffer(message.data, dtype=np.uint8)
    required_bytes = message.height * message.step
    if data.size < required_bytes:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "ROS image data is shorter than height * step.",
        )
    rows = data[:required_bytes].reshape((message.height, message.step))
    pixels = rows[:, :expected_row_bytes].reshape(
        (message.height, message.width, channels)
    )
    if encoding == "rgb8":
        return Image.fromarray(pixels.copy(), mode="RGB")
    if encoding == "bgr8":
        return Image.fromarray(pixels[:, :, ::-1].copy(), mode="RGB")
    if encoding == "rgba8":
        return Image.fromarray(pixels[:, :, :3].copy(), mode="RGB")
    if encoding == "bgra8":
        return Image.fromarray(pixels[:, :, 2::-1].copy(), mode="RGB")
    return Image.fromarray(pixels[:, :, 0].copy(), mode="L").convert("RGB")


def _read_worker_message(stream: TextIO, *, timeout_sec: float) -> dict[str, object]:
    ready, _, _ = select.select([stream], [], [], timeout_sec)
    if not ready:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INFERENCE_TIMEOUT,
            "SAM3 worker did not return a protocol message before timeout.",
        )
    line = stream.readline()
    if not line:
        raise Sam3RuntimeError(
            Sam3ErrorCode.WORKER_EXITED,
            "SAM3 worker exited without returning a protocol message.",
        )
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
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
        message = "SAM3 worker returned an error without a message."
    return Sam3RuntimeError(code, message)


def _best_detection(
    frames: list[dict[str, object]],
) -> tuple[int | None, int | None, float | None]:
    best_frame_index: int | None = None
    best_instance_index: int | None = None
    best_score: float | None = None
    for frame in frames:
        frame_index = int(frame["frame_index"])
        instances = frame.get("instances")
        if not isinstance(instances, list):
            continue
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            score = instance.get("score")
            index = instance.get("index")
            if isinstance(score, (int, float)) and isinstance(index, int):
                if best_score is None or float(score) > best_score:
                    best_frame_index = frame_index
                    best_instance_index = index
                    best_score = float(score)
    return best_frame_index, best_instance_index, best_score


def _failure_payload(
    arguments: argparse.Namespace,
    error: Sam3RuntimeError,
) -> dict[str, object]:
    return {
        "ok": False,
        "schema_version": 2,
        "request_id": arguments.request_id,
        "image_topic": arguments.image_topic,
        "depth_image_topic": arguments.depth_image_topic,
        "camera_calibration": arguments.camera_calibration,
        "text_prompt": arguments.prompt,
        "confidence_threshold": arguments.confidence,
        "requested_frame_count": arguments.frame_count,
        "processed_frame_count": 0,
        "result_json_path": str(Path(arguments.result_json).expanduser().resolve()),
        "target_object_pose_valid": False,
        "target_object_pose_matrix": list(IDENTITY_MATRIX_4X4),
        "error_code": error.code.value,
        "message": error.message,
    }


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _emit_stdout(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
