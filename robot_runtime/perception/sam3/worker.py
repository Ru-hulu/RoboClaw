"""Newline-delimited JSON worker that owns the SAM3 model process."""

from __future__ import annotations

import json
import os
import sys
import traceback
from collections.abc import Callable, Mapping
from typing import TextIO

from .backend import OfficialSam3Backend
from .config import Sam3RuntimeConfig
from .engine import Sam3Engine
from .errors import Sam3ErrorCode, Sam3RuntimeError
from .models import Sam3Request


EngineFactory = Callable[[Sam3RuntimeConfig], Sam3Engine]


class Sam3Worker:
    """Serve sequential inference requests over stdin and stdout."""

    def __init__(
        self,
        config: Sam3RuntimeConfig,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self._config = config
        self._engine_factory = engine_factory or _default_engine

    def serve(
        self,
        input_stream: TextIO,
        output_stream: TextIO,
        error_stream: TextIO | None = None,
    ) -> int:
        """Load once, process each JSON line, and keep request errors isolated."""

        operator_stream = error_stream or sys.stderr
        engine = self._engine_factory(self._config)
        try:
            load_duration_ms = engine.load()
        except Sam3RuntimeError as error:
            _write_json(
                output_stream,
                {"event": "startup_error", "ok": False, "error": error.to_dict()},
            )
            return 1
        except Exception as error:
            traceback.print_exc(file=operator_stream)
            public_error = _unexpected_error("SAM3 worker model startup failed.")
            _write_json(
                output_stream,
                {
                    "event": "startup_error",
                    "ok": False,
                    "error": public_error.to_dict(),
                },
            )
            return 1

        _write_json(
            output_stream,
            {
                "event": "ready",
                "pid": os.getpid(),
                "load_duration_ms": float(load_duration_ms),
            },
        )

        for raw_line in input_stream:
            request_id: str | None = None
            try:
                payload = _decode_request_line(raw_line)
                candidate_id = payload.get("request_id")
                if isinstance(candidate_id, str):
                    request_id = candidate_id
                request = Sam3Request.from_dict(payload)
                request_id = request.request_id
                result = engine.infer(request)
                response: dict[str, object] = {
                    "ok": True,
                    "request_id": request_id,
                    "result": result.to_dict(),
                }
            except Sam3RuntimeError as error:
                response = {
                    "ok": False,
                    "request_id": request_id,
                    "error": error.to_dict(),
                }
            except Exception:
                traceback.print_exc(file=operator_stream)
                response = {
                    "ok": False,
                    "request_id": request_id,
                    "error": _unexpected_error(
                        "SAM3 inference failed unexpectedly."
                    ).to_dict(),
                }
            _write_json(output_stream, response)
        return 0


def _decode_request_line(raw_line: str) -> Mapping[str, object]:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "SAM3 worker request must be one valid JSON object per line.",
        ) from error
    if not isinstance(payload, dict):
        raise Sam3RuntimeError(
            Sam3ErrorCode.INVALID_INPUT,
            "SAM3 worker request must be a JSON object.",
        )
    return payload


def _write_json(stream: TextIO, payload: Mapping[str, object]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


def _unexpected_error(message: str) -> Sam3RuntimeError:
    return Sam3RuntimeError(Sam3ErrorCode.MODEL_UNAVAILABLE, message)


def _default_engine(config: Sam3RuntimeConfig) -> Sam3Engine:
    return Sam3Engine(config, OfficialSam3Backend(config))
