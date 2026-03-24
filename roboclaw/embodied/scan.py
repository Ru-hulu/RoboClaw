"""Hardware scanning — detect serial ports and cameras."""

from __future__ import annotations

import glob
import os
from pathlib import Path


def scan_serial_ports() -> list[dict[str, str]]:
    """Scan /dev/serial/by-id/ for connected serial devices."""
    by_id_dir = Path("/dev/serial/by-id")
    if not by_id_dir.exists():
        return []
    ports = []
    for entry in sorted(by_id_dir.iterdir()):
        if entry.is_symlink():
            target = os.path.realpath(str(entry))
            if not os.path.exists(target):
                continue
            ports.append({"id": entry.name, "path": str(entry), "target": target})
    return ports


def scan_cameras() -> list[dict[str, str | int]]:
    """Scan /dev/video* and probe with OpenCV to find real cameras."""
    try:
        import cv2
    except ImportError:
        return []

    # Suppress V4L2/obsensor stderr noise during probing
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        import re
        devices = sorted(glob.glob("/dev/video*"))
        cameras = []
        for dev in devices:
            m = re.match(r"/dev/video(\d+)$", dev)
            if not m:
                continue
            cap = cv2.VideoCapture(int(m.group(1)))
            try:
                if not cap.isOpened():
                    continue
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append({"id": dev, "width": w, "height": h})
            finally:
                cap.release()
        return cameras
    finally:
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)
