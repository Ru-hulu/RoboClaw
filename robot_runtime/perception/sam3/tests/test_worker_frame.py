from __future__ import annotations

import base64
import io
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from robot_runtime.perception.lcm_protocol import DECODE_OK, DecodeImageResult
from robot_runtime.perception.sam3 import worker_client
from robot_runtime.perception.sam3.worker import Sam3Worker


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()


class FakeResult:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id

    def to_dict(self) -> dict[str, object]:
        return {"request_id": self.request_id}


class FakeEngine:
    def __init__(self) -> None:
        self.frame_pixel: tuple[int, int, int] | None = None

    def load(self) -> float:
        return 1.0

    def infer_frame(self, request, image, input_sha256):
        del input_sha256
        self.frame_pixel = image.getpixel((0, 0))
        return FakeResult(request.request_id)


class WorkerFrameTest(unittest.TestCase):
    def test_client_sends_lcm_frame_without_writing_an_input_file(self) -> None:
        request_id = str(uuid4())
        frame = DecodeImageResult(
            DECODE_OK,
            {
                "width": 1,
                "height": 1,
                "step": 3,
                "encoding": "rgb8",
            },
            b"\x01\x02\x03",
        )
        process = FakeProcess()
        client = worker_client.Sam3WorkerClient()
        client._process = process  # type: ignore[assignment]

        with patch.object(
            worker_client,
            "_read_worker_message",
            return_value={
                "ok": True,
                "request_id": request_id,
                "result": {"instance_count": 0},
            },
        ):
            result = client.infer_frame(request_id, frame, "cup")

        payload = json.loads(process.stdin.getvalue())
        encoded_frame = payload["image_frame"]
        self.assertNotIn("image_path", payload)
        self.assertEqual(
            base64.b64decode(encoded_frame["data_base64"]),
            b"\x01\x02\x03",
        )
        self.assertEqual(result, {"instance_count": 0})

    def test_worker_decodes_frame_and_calls_in_memory_engine_path(self) -> None:
        request_id = str(uuid4())
        engine = FakeEngine()
        worker = Sam3Worker(object(), lambda config: engine)  # type: ignore[arg-type]
        request = {
            "request_id": request_id,
            "image_frame": {
                "width": 1,
                "height": 1,
                "step": 3,
                "encoding": "bgr8",
                "data_base64": base64.b64encode(b"\x01\x02\x03").decode(),
            },
            "text_prompt": "cup",
            "confidence_threshold": 0.5,
        }
        output = io.StringIO()

        return_code = worker.serve(
            io.StringIO(json.dumps(request) + "\n"),
            output,
        )

        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(return_code, 0)
        self.assertEqual(messages[0]["event"], "ready")
        self.assertTrue(messages[1]["ok"])
        self.assertEqual(engine.frame_pixel, (3, 2, 1))


if __name__ == "__main__":
    unittest.main()
