"""Hand runtime action dispatch functions."""

from __future__ import annotations

import asyncio
from typing import Any


def _resolve_hand(setup: dict[str, Any], hand_name: str) -> dict:
    """Find hand in setup by alias. Raises ActionError if not found."""
    from roboclaw.embodied.setup import find_hand
    from roboclaw.embodied.tool import ActionError

    hands = setup.get("hands", [])
    if not hands:
        raise ActionError("No hand configured. Use set_hand to add one.")
    if not hand_name:
        return hands[0]
    hand = find_hand(hands, hand_name)
    if hand is None:
        raise ActionError(f"No hand named '{hand_name}' in setup.")
    return hand


def _run_hand_method(method_name: str, setup: dict[str, Any], kwargs: dict[str, Any], extra_args=()):
    """Resolve hand and call an InspireController method in a thread."""
    from roboclaw.embodied.embodiment.inspire import InspireController

    hand = _resolve_hand(setup, kwargs.get("hand_name", ""))
    method = getattr(InspireController(), method_name)
    return asyncio.to_thread(method, hand["port"], *extra_args)


async def _do_hand_open(setup: dict[str, Any], kwargs: dict[str, Any], tty_handoff: Any) -> str:
    return await _run_hand_method("open_hand", setup, kwargs)


async def _do_hand_close(setup: dict[str, Any], kwargs: dict[str, Any], tty_handoff: Any) -> str:
    return await _run_hand_method("close_hand", setup, kwargs)


async def _do_hand_pose(setup: dict[str, Any], kwargs: dict[str, Any], tty_handoff: Any) -> str:
    positions = kwargs.get("positions")
    if not positions:
        return "hand_pose requires positions (6 integers 0-1000)."
    return await _run_hand_method("set_pose", setup, kwargs, extra_args=(positions,))


async def _do_hand_status(setup: dict[str, Any], kwargs: dict[str, Any], tty_handoff: Any) -> str:
    return await _run_hand_method("get_status", setup, kwargs)
