"""Minimal LCM subscriber for Gazebo RealSense RGB-D image messages."""

from __future__ import annotations

import lcm

from robot_runtime.perception.lcm_protocol import (
    COLOR_IMAGE_CHANNEL,
    DECODE_OK,
    DEPTH_IMAGE_CHANNEL,
    decode_image_message,
)


def main() -> int:
    lc = lcm.LCM()
    lc.subscribe(COLOR_IMAGE_CHANNEL, _on_image)
    lc.subscribe(DEPTH_IMAGE_CHANNEL, _on_image)
    print("Listening for Gazebo RealSense image messages over LCM...")
    print(f"  color: {COLOR_IMAGE_CHANNEL}")
    print(f"  depth: {DEPTH_IMAGE_CHANNEL}")

    while True:
        lc.handle()


def _on_image(channel: str, payload: bytes) -> None:
    result = decode_image_message(payload)
    if result.state != DECODE_OK:
        print(f"[{channel}] invalid image payload: {result.state}")
        return

    assert result.header is not None
    assert result.image_bytes is not None
    print(
        f"[{channel}] "
        f"{result.header['width']}x{result.header['height']} "
        f"encoding={result.header['encoding']} "
        f"frame={result.header['frame_id']} "
        f"stamp={result.header['stamp_sec']}.{result.header['stamp_nanosec']:09d} "
        f"bytes={len(result.image_bytes)}"
    )

if __name__ == "__main__":
    raise SystemExit(main())
