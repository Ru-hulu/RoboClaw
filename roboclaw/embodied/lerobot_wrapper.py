"""Wrapper entrypoint that patches LeRobot before record/replay."""

from __future__ import annotations

import sys

from roboclaw.embodied.headless_patch import apply_headless_patch


def record(argv: list[str] | None = None) -> None:
    _run("record", argv)


def replay(argv: list[str] | None = None) -> None:
    _run("replay", argv)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("Usage: python -m roboclaw.embodied.lerobot_wrapper <record|replay> [args...]")
    action = args[0]
    if action not in {"record", "replay"}:
        raise SystemExit(f"Unsupported action: {action}")
    _run(action, args[1:])


def _run(action: str, argv: list[str] | None = None) -> None:
    args = list([] if argv is None else argv)
    apply_headless_patch()
    original_argv = sys.argv[:]
    try:
        sys.argv = [f"lerobot-{action}", *args]
        if action == "record":
            from lerobot.scripts import lerobot_record as module
        else:
            from lerobot.scripts import lerobot_replay as module
        module.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
