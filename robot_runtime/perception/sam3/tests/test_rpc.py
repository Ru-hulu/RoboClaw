from __future__ import annotations

import sys
import types
import unittest

try:
    import lcm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["lcm"] = types.SimpleNamespace(LCM=object)

from robot_runtime.perception.sam3.rpc import (
    SAM3_RPC_REQUEST_CHANNEL,
    SAM3_RPC_RESPONSE_CHANNEL,
    Sam3RpcClient,
    Sam3RpcServer,
)


class FakeLcmBus:
    def __init__(self) -> None:
        self.callbacks: dict[str, list[object]] = {}

    def subscribe(self, channel: str, callback: object) -> None:
        self.callbacks.setdefault(channel, []).append(callback)

    def publish(self, channel: str, payload: bytes) -> None:
        for callback in self.callbacks.get(channel, []):
            callback(channel, payload)  # type: ignore[operator]

    def handle_timeout(self, timeout_ms: int) -> int:
        del timeout_ms
        return 0


class Sam3RpcTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = FakeLcmBus()
        self.client = Sam3RpcClient(self.bus)  # type: ignore[arg-type]
        self.server = Sam3RpcServer(self.bus)  # type: ignore[arg-type]

    def test_segment_request_and_response(self) -> None:
        def serve_once(channel: str, payload: bytes) -> None:
            original_publish(channel, payload)
            if channel != SAM3_RPC_REQUEST_CHANNEL:
                return
            request = self.server.poll(0)
            self.assertIsNotNone(request)
            assert request is not None
            self.assertEqual(request.text_prompt, "cube")
            self.assertEqual(request.confidence_threshold, 0.7)
            self.assertEqual(request.frame_timeout_sec, 2.0)
            self.server.respond_success(
                request.request_id,
                {
                    "instance_count": 1,
                    "instances": [],
                },
            )

        original_publish = self.bus.publish
        self.bus.publish = serve_once  # type: ignore[method-assign]

        result = self.client.segment(
            "cube",
            confidence_threshold=0.7,
            frame_timeout_sec=2.0,
            timeout_sec=0.1,
        )

        self.assertEqual(result["instance_count"], 1)
        self.assertEqual(result["position_valid"], False)
        self.assertIsNone(result["position"])

    def test_client_raises_on_error_response(self) -> None:
        def serve_error(channel: str, payload: bytes) -> None:
            original_publish(channel, payload)
            if channel == SAM3_RPC_REQUEST_CHANNEL:
                request = self.server.poll(0)
                assert request is not None
                self.server.respond_error(request.request_id, "camera timeout")

        original_publish = self.bus.publish
        self.bus.publish = serve_error  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "camera timeout"):
            self.client.segment("cube", timeout_sec=0.1)

    def test_server_replies_to_invalid_request_without_returning_work(self) -> None:
        responses: list[bytes] = []

        def record_response(channel: str, payload: bytes) -> None:
            if channel == SAM3_RPC_RESPONSE_CHANNEL:
                responses.append(payload)
            original_publish(channel, payload)

        original_publish = self.bus.publish
        self.bus.publish = record_response  # type: ignore[method-assign]

        original_publish(
            SAM3_RPC_REQUEST_CHANNEL,
            b'{"request_id":"bad-request","method":"unknown"}',
        )

        request = self.server.poll(0)

        self.assertIsNone(request)
        self.assertIn(b'"ok":false', responses[0])
        self.assertIn(b"unsupported SAM3 RPC method", responses[0])

    def test_request_and_response_channels_are_distinct(self) -> None:
        self.assertNotEqual(SAM3_RPC_REQUEST_CHANNEL, SAM3_RPC_RESPONSE_CHANNEL)


if __name__ == "__main__":
    unittest.main()
