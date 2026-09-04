from __future__ import annotations

import sys
import types
import unittest

try:
    import lcm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["lcm"] = types.SimpleNamespace(LCM=object)

from robot_runtime.ipc.lcm_rpc import LcmRpcClient, LcmRpcServer


REQUEST_CHANNEL = "TEST_RPC_REQUEST"
RESPONSE_CHANNEL = "TEST_RPC_RESPONSE"


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


class LcmRpcTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = FakeLcmBus()
        self.client = LcmRpcClient(
            REQUEST_CHANNEL,
            RESPONSE_CHANNEL,
            self.bus,  # type: ignore[arg-type]
        )
        self.server = LcmRpcServer(
            REQUEST_CHANNEL,
            RESPONSE_CHANNEL,
            self.bus,  # type: ignore[arg-type]
        )

    def test_client_server_round_trip(self) -> None:
        response_from_server: dict[str, object] | None = None

        def run_server_once() -> None:
            nonlocal response_from_server
            request = self.server.poll(0)
            self.assertIsNotNone(request)
            assert request is not None
            response_from_server = request.payload
            self.server.respond(request.request_id, {"ok": True, "value": 42})

        original_publish = self.bus.publish

        def publish_and_serve(channel: str, payload: bytes) -> None:
            original_publish(channel, payload)
            if channel == REQUEST_CHANNEL:
                run_server_once()

        self.bus.publish = publish_and_serve  # type: ignore[method-assign]

        response = self.client.call({"method": "ping"}, timeout_sec=0.1)

        self.assertEqual(response["ok"], True)
        self.assertEqual(response["value"], 42)
        self.assertEqual(response_from_server["method"], "ping")
        self.assertIsInstance(response_from_server["request_id"], str)

    def test_client_ignores_unmatched_response(self) -> None:
        self.server.respond("other-request", {"ok": True})

        with self.assertRaises(TimeoutError):
            self.client.call({"method": "ping"}, timeout_sec=0.001)


if __name__ == "__main__":
    unittest.main()
