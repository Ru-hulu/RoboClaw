from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import patch

try:
    import lcm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["lcm"] = types.SimpleNamespace(LCM=object)

from robot_runtime.perception.lcm_protocol import DECODE_OK, DecodeImageResult
from robot_runtime.perception.sam3 import service
from robot_runtime.perception.sam3.rpc import Sam3SegmentRequest


class FakeWorker:
    def __init__(self) -> None:
        self.pid = 123
        self.started = False
        self.closed = False
        self.running = True
        self._running_checks = 0
        self.infer_requests: list[tuple[str, str, float]] = []

    def start(self) -> None:
        self.started = True

    @property
    def is_running(self) -> bool:
        self._running_checks += 1
        return self.running and self._running_checks <= 3

    def infer_frame(
        self,
        request_id: str,
        frame: DecodeImageResult,
        prompt: str,
        confidence_threshold: float,
    ) -> dict[str, object]:
        self.infer_requests.append((request_id, prompt, confidence_threshold))
        self.running = False
        return {
            "request_id": request_id,
            "instance_count": 1,
            "image_size": len(frame.image_bytes or b""),
        }

    def close(self) -> None:
        self.closed = True


class FakeReceiver:
    def __init__(self) -> None:
        self.poll_timeouts: list[int] = []
        self.capture_started = False
        self.capture_cancelled = False
        self.color: DecodeImageResult | None = None
        self.depth: DecodeImageResult | None = None

    def begin_capture(self) -> None:
        self.capture_started = True

    def poll(self, timeout_ms: int) -> int:
        self.poll_timeouts.append(timeout_ms)
        if self.capture_started:
            self.color = DecodeImageResult(
                DECODE_OK,
                {"width": 1, "height": 1, "step": 1, "encoding": "mono8"},
                b"c",
            )
            self.depth = DecodeImageResult(
                DECODE_OK,
                {
                    "width": 1,
                    "height": 1,
                    "step": 1,
                    "encoding": "16UC1",
                    "frame_id": "camera_depth_optical_frame",
                },
                b"d",
            )
        return 0

    def cancel_capture(self) -> None:
        self.capture_cancelled = True


class FakeRpcServer:
    def __init__(self, request: Sam3SegmentRequest | None = None) -> None:
        self.request = request
        self.poll_timeouts: list[int] = []
        self.success_responses: list[tuple[str, dict[str, object]]] = []
        self.error_responses: list[tuple[str, str]] = []

    def poll(self, timeout_ms: int) -> Sam3SegmentRequest | None:
        self.poll_timeouts.append(timeout_ms)
        request = self.request
        self.request = None
        return request

    def respond_success(
        self,
        request_id: str,
        sam3_result: dict[str, object],
    ) -> None:
        self.success_responses.append((request_id, sam3_result))

    def respond_error(self, request_id: str, error: str) -> None:
        self.error_responses.append((request_id, error))


class Sam3ServiceTest(unittest.TestCase):
    def test_polls_rpc_while_worker_is_running(self) -> None:
        worker = FakeWorker()
        receiver = FakeReceiver()
        rpc_server = FakeRpcServer()
        stdout = io.StringIO()

        with (
            patch.object(service, "Sam3WorkerHandle", return_value=worker),
            patch.object(service, "LcmRgbdReceiver", return_value=receiver),
            patch.object(service, "Sam3RpcServer", return_value=rpc_server),
            patch.object(service.lcm, "LCM", return_value=object()),
            contextlib.redirect_stdout(stdout),
        ):
            return_code = service.main()

        ready = json.loads(stdout.getvalue().splitlines()[0])
        self.assertTrue(worker.started)
        self.assertTrue(worker.closed)
        self.assertEqual(rpc_server.poll_timeouts, [100, 100, 100])
        self.assertEqual(receiver.poll_timeouts, [])
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["worker_pid"], 123)
        self.assertEqual(return_code, 1)

    def test_segment_rpc_captures_rgbd_and_calls_worker(self) -> None:
        worker = FakeWorker()
        receiver = FakeReceiver()
        request = Sam3SegmentRequest(
            request_id="request-1",
            text_prompt="cube",
            confidence_threshold=0.6,
            frame_timeout_sec=1.0,
        )
        rpc_server = FakeRpcServer(request)
        stdout = io.StringIO()

        with (
            patch.object(service, "Sam3WorkerHandle", return_value=worker),
            patch.object(service, "LcmRgbdReceiver", return_value=receiver),
            patch.object(service, "Sam3RpcServer", return_value=rpc_server),
            patch.object(service.lcm, "LCM", return_value=object()),
            contextlib.redirect_stdout(stdout),
        ):
            return_code = service.main()

        self.assertEqual(return_code, 1)
        self.assertTrue(receiver.capture_started)
        self.assertTrue(receiver.capture_cancelled)
        self.assertEqual(receiver.poll_timeouts, [100])
        self.assertEqual(worker.infer_requests, [("request-1", "cube", 0.6)])
        self.assertEqual(
            rpc_server.success_responses,
            [
                (
                    "request-1",
                    {
                        "request_id": "request-1",
                        "instance_count": 1,
                        "image_size": 1,
                        "position_valid": False,
                        "position": None,
                    },
                )
            ],
        )
        self.assertEqual(rpc_server.error_responses, [])


if __name__ == "__main__":
    unittest.main()
