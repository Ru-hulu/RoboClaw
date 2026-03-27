"""BrainCo Revo2 dexterous hand controller via bc_stark_sdk (Modbus RS-485)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from roboclaw.embodied.embodiment.hand.modbus import probe_modbus_slave_ids

_FINGER_LABELS = ("thumb", "thumb_aux", "index", "middle", "ring", "pinky")
_OPEN_POSITIONS = [0, 0, 0, 0, 0, 0]
_CLOSE_POSITIONS = [400, 0, 1000, 1000, 1000, 1000]
_SPEEDS = [1000] * 6
_BAUDRATE = 460800
_DEFAULT_SLAVE_ID = 0x7E
_NUM_FINGERS = 6

_DEFAULT_CANDIDATES = list(range(1, 17)) + [0x7E, 0x7F]


def probe_slave_ids(port: str, candidates: list[int] | None = None) -> list[int]:
    """Probe port for responding Revo2 Modbus slave IDs."""
    return probe_modbus_slave_ids(
        port, _BAUDRATE, candidates or _DEFAULT_CANDIDATES, register=0, register_count=1,
    )


class Revo2Controller:
    """Controls BrainCo Revo2 dexterous hand via bc_stark_sdk.

    Each method opens a connection, performs the operation, then closes it.
    Finger positions: [thumb, thumb_aux, index, middle, ring, pinky], 0-1000.
    """

    async def open_hand(self, port: str, slave_id: int = _DEFAULT_SLAVE_ID) -> str:
        """Open all fingers."""
        async with self._session(port, slave_id) as client:
            await client.set_finger_positions_and_speeds(slave_id, _OPEN_POSITIONS, _SPEEDS)
        return "Hand opened."

    async def close_hand(self, port: str, slave_id: int = _DEFAULT_SLAVE_ID) -> str:
        """Close all fingers."""
        async with self._session(port, slave_id) as client:
            await client.set_finger_positions_and_speeds(slave_id, _CLOSE_POSITIONS, _SPEEDS)
        return "Hand closed."

    async def set_pose(self, port: str, positions: list[int], slave_id: int = _DEFAULT_SLAVE_ID) -> str:
        """Set individual finger positions (6 values, 0-1000)."""
        if len(positions) != _NUM_FINGERS:
            raise ValueError(f"Expected {_NUM_FINGERS} finger positions, got {len(positions)}.")
        if any(p < 0 or p > 1000 for p in positions):
            raise ValueError("Each finger position must be 0-1000.")
        async with self._session(port, slave_id) as client:
            await client.set_finger_positions_and_speeds(slave_id, positions, _SPEEDS)
        summary = ", ".join(f"{label}={val}" for label, val in zip(_FINGER_LABELS, positions))
        return f"Pose set: {summary}."

    async def get_status(self, port: str, slave_id: int = _DEFAULT_SLAVE_ID) -> str:
        """Read current finger positions, speeds, and currents."""
        async with self._session(port, slave_id) as client:
            status = await client.get_motor_status(slave_id)
        pos = dict(zip(_FINGER_LABELS, status.positions))
        spd = dict(zip(_FINGER_LABELS, status.speeds))
        cur = dict(zip(_FINGER_LABELS, status.currents))
        return f"positions={pos}\nspeeds={spd}\ncurrents={cur}"

    @staticmethod
    @asynccontextmanager
    async def _session(port: str, slave_id: int):
        """Open bc_stark_sdk connection, yield client, guarantee close."""
        from bc_stark_sdk import main_mod as libstark  # lazy import

        client = await libstark.modbus_open(port, libstark.Baudrate.Baud460800)
        if not client:
            raise RuntimeError("Failed to open hand serial connection.")
        info = await client.get_device_info(slave_id)
        if not info:
            libstark.modbus_close(client)
            raise RuntimeError("Hand not responding. Check connection and power.")
        await client.set_finger_unit_mode(slave_id, libstark.FingerUnitMode.Normalized)
        try:
            yield client
        finally:
            libstark.modbus_close(client)
