"""Request-gated receiver for RealSense RGB-D images carried over LCM."""

from __future__ import annotations

import lcm

from robot_runtime.perception.lcm_protocol import (
    COLOR_IMAGE_CHANNEL,
    DECODE_OK,
    DEPTH_IMAGE_CHANNEL,
    DecodeImageResult,
    decode_image_message,
)


class LcmRgbdReceiver:
    """Ignore images while idle and retain frames only during a capture window."""

    def __init__(self, lc: lcm.LCM | None = None) -> None:
        self._lcm = lc if lc is not None else lcm.LCM()
        self._capture_active = False
        self._color: DecodeImageResult | None = None
        self._depth: DecodeImageResult | None = None
        self._lcm.subscribe(COLOR_IMAGE_CHANNEL, self._on_color)
        self._lcm.subscribe(DEPTH_IMAGE_CHANNEL, self._on_depth)

    @property
    def capture_active(self) -> bool:
        return self._capture_active

    @property
    def color(self) -> DecodeImageResult | None:
        return self._color

    @property
    def depth(self) -> DecodeImageResult | None:
        return self._depth

    def begin_capture(self) -> None:
        self._capture_active = True
        self._color = None
        self._depth = None

    def cancel_capture(self) -> None:
        self._capture_active = False
        self._color = None
        self._depth = None

    def poll(self, timeout_ms: int = 100) -> int:
        """Handle at most one LCM message or wait until the timeout expires."""

        return self._lcm.handle_timeout(timeout_ms)

    def _on_color(self, channel: str, payload: bytes) -> None:
        del channel
        if not self._capture_active or self._color is not None:
            return
        result = decode_image_message(payload)
        if result.state == DECODE_OK:
            self._color = result

    def _on_depth(self, channel: str, payload: bytes) -> None:
        del channel
        if not self._capture_active or self._depth is not None:
            return
        result = decode_image_message(payload)
        if result.state == DECODE_OK:
            self._depth = result
