"""Calibration API routes — start calibration and post commands."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class StartRequest(BaseModel):
    arm_alias: str


class CommandRequest(BaseModel):
    command: str  # "confirm", "recalibrate", "stop"


def register_calibrate_routes(app: FastAPI, service: Any) -> None:

    @app.post("/api/calibration/start")
    async def calibration_start(body: StartRequest) -> dict:
        try:
            return await service.start_calibration(body.arm_alias)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/calibration/command")
    async def calibration_command(body: CommandRequest) -> dict:
        if body.command == "stop":
            await service.stop_calibration()
            return {"status": "ok", "command": "stop"}
        service.post_calibration_command(body.command)
        return {"status": "ok", "command": body.command}
