"""Minimal LCM subscriber for Gazebo RealSense RGB-D image messages."""

from __future__ import annotations

import json
import struct

import lcm


COLOR_LCM_CHANNEL = "ROBOCLAW_REALSENSE_COLOR_IMAGE"
DEPTH_LCM_CHANNEL = "ROBOCLAW_REALSENSE_DEPTH_IMAGE"
_HEADER_LENGTH = struct.Struct("<I")


def main() -> int:
    lc = lcm.LCM()
    lc.subscribe(COLOR_LCM_CHANNEL, _on_image)
    lc.subscribe(DEPTH_LCM_CHANNEL, _on_image)
    print("Listening for Gazebo RealSense image messages over LCM...")
    print(f"  color: {COLOR_LCM_CHANNEL}")
    print(f"  depth: {DEPTH_LCM_CHANNEL}")

    while True:
        lc.handle()


def _on_image(channel: str, payload: bytes) -> None:
    try:
        header, image_bytes = _decode_image_message(payload)
    except ValueError as error:
        print(f"[{channel}] invalid image payload: {error}")
        return

    print(
        f"[{channel}] "
        f"{header['width']}x{header['height']} "
        f"encoding={header['encoding']} "
        f"frame={header['frame_id']} "
        f"stamp={header['stamp_sec']}.{header['stamp_nanosec']:09d} "
        f"bytes={len(image_bytes)}"
    )


def _decode_image_message(payload: bytes) -> tuple[dict[str, object], bytes]:
    if len(payload) < _HEADER_LENGTH.size:
        raise ValueError("payload is too short to contain an image header")

    header_length = _HEADER_LENGTH.unpack_from(payload, 0)[0]
    header_start = _HEADER_LENGTH.size
    header_end = header_start + header_length
    if len(payload) < header_end:
        raise ValueError("payload is shorter than the declared header length")

    header = json.loads(payload[header_start:header_end].decode("utf-8"))
    image_bytes = payload[header_end:]
    if len(image_bytes) != header["data_size"]:
        raise ValueError("image data size mismatch") # LCM 依托UDP，所以无法保证数据的可靠性。用简单方式校验一下。
    if len(image_bytes) != header["height"] * header["step"]:
        raise ValueError("image layout size mismatch")
    return header, image_bytes


if __name__ == "__main__":
    raise SystemExit(main())
