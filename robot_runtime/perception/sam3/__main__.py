"""Command-line entry point for the SAM3 worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import TextIO

from .engine.config import Sam3RuntimeConfig
from .engine.errors import Sam3RuntimeError
from .worker import EngineFactory, Sam3Worker


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
    env: dict[str, str] | None = None,
    engine_factory: EngineFactory | None = None,
) -> int:
    """Run the persistent in-memory frame worker."""

    parser = _build_parser()
    parser.parse_args(argv)
    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr
    try:
        config = Sam3RuntimeConfig.from_env(os.environ if env is None else env)
    except Sam3RuntimeError as error:
        _emit(
            stdout,
            {"event": "startup_error", "ok": False, "error": error.to_dict()},
        )
        return 1

    # Service 与 Worker 之间通过 stdin/stdout JSON Lines 传递内存帧和结果。
    return Sam3Worker(config, engine_factory).serve(stdin, stdout, stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RoboClaw SAM3 frame worker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Serve JSON Lines requests on stdin/stdout.")
    return parser


def _emit(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
