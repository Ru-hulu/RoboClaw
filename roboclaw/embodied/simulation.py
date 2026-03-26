"""Simulation stubs for offline/CI testing of the embodied pipeline.

Set ``ROBOCLAW_SIMULATE=1`` to activate.  All simulation helpers live here
so that callers only need a single ``is_simulating()`` check.
"""

from __future__ import annotations

import os


def is_simulating() -> bool:
    """Return True when the simulation environment variable is set."""
    return os.environ.get("ROBOCLAW_SIMULATE", "") == "1"


# ── Simulated hardware data ─────────────────────────────────────────


def simulated_ports() -> list[dict[str, str]]:
    """Return two fake serial ports for a leader/follower pair."""
    return [
        {
            "by_path": "/dev/serial/by-path/sim-pci-0:2.1",
            "by_id": "/dev/serial/by-id/usb-SIM_Serial_SIM001-if00",
            "dev": "/dev/ttyACM0",
        },
        {
            "by_path": "/dev/serial/by-path/sim-pci-0:2.2",
            "by_id": "/dev/serial/by-id/usb-SIM_Serial_SIM002-if00",
            "dev": "/dev/ttyACM1",
        },
    ]


def simulated_cameras() -> list[dict[str, str | int]]:
    """Return one fake camera."""
    return [
        {
            "by_path": "/dev/v4l/by-path/sim-cam0",
            "by_id": "usb-sim-cam0",
            "dev": "/dev/video0",
            "width": 640,
            "height": 480,
        },
    ]


def simulated_motor_ids() -> list[int]:
    """Motor IDs that a simulated probe would return."""
    return [1, 2, 3, 4, 5, 6]


def simulated_moved_port(ports: list[dict]) -> dict | None:
    """In simulation, always pick the first port as 'moved'."""
    return ports[0] if ports else None
