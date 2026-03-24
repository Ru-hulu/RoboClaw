"""Hardware scanning — detect serial ports and cameras."""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path


def _read_symlink_map(directory: str) -> dict[str, str]:
    """Read a directory of symlinks, return {resolved_target: symlink_path}."""
    d = Path(directory)
    if not d.exists():
        return {}
    result = {}
    for entry in d.iterdir():
        if entry.is_symlink():
            target = os.path.realpath(str(entry))
            result[target] = str(entry)
    return result


def scan_serial_ports() -> list[dict[str, str]]:
    """Scan serial devices, return list with by_path, by_id, dev."""
    by_path = _read_symlink_map("/dev/serial/by-path")
    by_id = _read_symlink_map("/dev/serial/by-id")
    all_devs = set(by_path.keys()) | set(by_id.keys())
    ports = []
    for dev in sorted(all_devs):
        if not os.path.exists(dev):
            continue
        ports.append({
            "by_path": by_path.get(dev, ""),
            "by_id": by_id.get(dev, ""),
            "dev": dev,
        })
    return ports


def suppress_stderr() -> int:
    """Redirect stderr to /dev/null. Returns saved fd for restore_stderr."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    return saved


def restore_stderr(saved: int) -> None:
    """Restore stderr from saved fd."""
    os.dup2(saved, 2)
    os.close(saved)


def scan_cameras() -> list[dict[str, str | int]]:
    """Scan cameras, return list with by_path, by_id, dev, resolution."""
    try:
        import cv2
    except ImportError:
        return []

    saved = suppress_stderr()
    try:
        by_path = _read_symlink_map("/dev/v4l/by-path")
        by_id = _read_symlink_map("/dev/v4l/by-id")
        return _probe_cameras(cv2, by_path, by_id)
    finally:
        restore_stderr(saved)


def _probe_cameras(cv2, by_path: dict, by_id: dict) -> list[dict[str, str | int]]:
    """Try opening each /dev/videoN, return those that work."""
    cameras = []
    for dev in sorted(glob.glob("/dev/video*")):
        m = re.match(r"/dev/video(\d+)$", dev)
        if not m:
            continue
        info = _try_open_camera(cv2, int(m.group(1)), dev, by_path, by_id)
        if info:
            cameras.append(info)
    return cameras


def _try_open_camera(cv2, index: int, dev: str, by_path: dict, by_id: dict) -> dict[str, str | int] | None:
    """Open a single camera by index, return info dict or None."""
    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        real = os.path.realpath(dev)
        return {
            "by_path": by_path.get(real, ""),
            "by_id": by_id.get(real, ""),
            "dev": dev,
            "width": w,
            "height": h,
        }
    finally:
        cap.release()
