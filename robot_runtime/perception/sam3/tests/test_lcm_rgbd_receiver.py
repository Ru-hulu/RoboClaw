from __future__ import annotations

import sys
import types
import unittest

try:
    import lcm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["lcm"] = types.SimpleNamespace(LCM=object)

from robot_runtime.perception.lcm_protocol import (
    COLOR_IMAGE_CHANNEL,
    DEPTH_IMAGE_CHANNEL,
    encode_image_message,
)
from robot_runtime.perception.sam3.lcm_rgbd_receiver import LcmRgbdReceiver


class FakeLcm:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}

    def subscribe(self, channel: str, callback: object) -> None:
        self.callbacks[channel] = callback

    def handle_timeout(self, timeout_ms: int) -> int:
        return timeout_ms

    def emit(self, channel: str, payload: bytes) -> None:
        callback = self.callbacks[channel]
        callback(channel, payload)  # type: ignore[operator]


def image_payload(kind: str, value: int) -> bytes:
    return encode_image_message(
        kind,
        {
            "frame_id": "camera",
            "stamp_sec": 1,
            "stamp_nanosec": value,
            "height": 1,
            "width": 1,
            "encoding": "mono8",
            "is_bigendian": 0,
            "step": 1,
        },
        bytes([value]),
    )


class LcmRgbdReceiverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lc = FakeLcm()
        self.receiver = LcmRgbdReceiver(self.lc)  # type: ignore[arg-type]

    def test_ignores_images_until_capture_begins(self) -> None:
        self.lc.emit(COLOR_IMAGE_CHANNEL, image_payload("color", 1))
        self.lc.emit(DEPTH_IMAGE_CHANNEL, image_payload("depth", 2))

        self.assertIsNone(self.receiver.color)
        self.assertIsNone(self.receiver.depth)

    def test_keeps_first_valid_images_during_capture(self) -> None:
        self.receiver.begin_capture()
        self.lc.emit(COLOR_IMAGE_CHANNEL, image_payload("color", 1))
        self.lc.emit(COLOR_IMAGE_CHANNEL, image_payload("color", 3))
        self.lc.emit(DEPTH_IMAGE_CHANNEL, image_payload("depth", 2))

        self.assertTrue(self.receiver.capture_active)
        self.assertEqual(self.receiver.color.image_bytes, b"\x01")
        self.assertEqual(self.receiver.depth.image_bytes, b"\x02")

    def test_cancel_discards_captured_images(self) -> None:
        self.receiver.begin_capture()
        self.lc.emit(COLOR_IMAGE_CHANNEL, image_payload("color", 1))

        self.receiver.cancel_capture()

        self.assertFalse(self.receiver.capture_active)
        self.assertIsNone(self.receiver.color)
        self.assertIsNone(self.receiver.depth)


if __name__ == "__main__":
    unittest.main()
