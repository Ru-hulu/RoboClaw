"""Command-line entry points for the SAM3 runtime and worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections.abc import Sequence
from typing import TextIO
from uuid import uuid4

from .config import Sam3RuntimeConfig
from .errors import Sam3ErrorCode, Sam3RuntimeError
from .models import Sam3Request
from .worker import EngineFactory, Sam3Worker, _default_engine


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
    env: dict[str, str] | None = None,
    engine_factory: EngineFactory | None = None,
) -> int:
    """Run the persistent worker or one-shot inference command."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr
    try:
        config = Sam3RuntimeConfig.from_env(os.environ if env is None else env)
    except Sam3RuntimeError as error:
        payload: dict[str, object] = {"ok": False, "error": error.to_dict()}
        if arguments.command == "serve":
            payload["event"] = "startup_error"
        _emit(stdout, payload)
        return 1

    if arguments.command == "serve":
        return Sam3Worker(config, engine_factory).serve(stdin, stdout, stderr)

    request_id = str(uuid4())
    try:
        request = Sam3Request.from_dict(
            {
                "request_id": request_id,
                "image_path": arguments.image,
                "text_prompt": arguments.prompt,
                "confidence_threshold": arguments.confidence,
            }
        )
        engine = (engine_factory or _default_engine)(config)
        result = engine.infer(request)
    except Sam3RuntimeError as error:
        _emit(
            stdout,
            {"ok": False, "request_id": request_id, "error": error.to_dict()},
        )
        return 1
    except Exception:
        traceback.print_exc(file=stderr)
        error = Sam3RuntimeError(
            Sam3ErrorCode.MODEL_UNAVAILABLE,
            "SAM3 one-shot inference failed unexpectedly.",
        )
        _emit(
            stdout,
            {"ok": False, "request_id": request_id, "error": error.to_dict()},
        )
        return 1

    _emit(
        stdout,
        {"ok": True, "request_id": request.request_id, "result": result.to_dict()},
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RoboClaw SAM3 image runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Serve JSON Lines requests on stdin/stdout.")
    infer = commands.add_parser("infer", help="Run one local-image inference.")
    infer.add_argument("--image", required=True, help="Local image path.")
    infer.add_argument("--prompt", required=True, help="Text prompt.")
    infer.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="Confidence threshold in [0.0, 1.0].",
    )
    return parser


def _emit(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
