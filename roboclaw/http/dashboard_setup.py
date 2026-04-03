"""Setup wizard REST API routes — thin HTTP shell over EmbodiedService."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from roboclaw.embodied.setup import (
    load_setup,
    remove_arm,
    remove_camera,
    rename_arm,
    set_arm,
    set_camera,
)


# Request models


class AddArmRequest(BaseModel):
    alias: str
    arm_type: str
    port_id: str


class AddCameraRequest(BaseModel):
    alias: str
    camera_index: int


class RenameRequest(BaseModel):
    new_alias: str


def _map_service_errors(app: FastAPI) -> None:
    """Map service-layer exceptions to HTTP status codes.

    EmbodimentBusyError  → 409 Conflict  (lock already held)
    RuntimeError         → 400 Bad Request (precondition / state errors)
    PermissionError      → 403 Forbidden
    """
    from fastapi.requests import Request
    from fastapi.responses import JSONResponse

    from roboclaw.embodied.service import EmbodimentBusyError

    @app.exception_handler(EmbodimentBusyError)
    async def _busy_error(request: Request, exc: EmbodimentBusyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def _runtime_error(request: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(PermissionError)
    async def _permission_error(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})


def register_setup_routes(app: FastAPI, service: Any) -> None:
    """Register setup wizard API endpoints.

    Lock management lives in ScanningService — routes are thin adapters.
    Service-layer RuntimeError/PermissionError are mapped to HTTP codes
    by _map_service_errors().
    """
    _map_service_errors(app)

    @app.post("/api/dashboard/setup/scan")
    async def setup_scan() -> dict[str, Any]:
        return await asyncio.to_thread(service.scanning.run_full_scan)

    @app.post("/api/dashboard/setup/camera-previews")
    async def setup_camera_previews() -> list[dict]:
        output_dir = str(Path("/tmp/roboclaw-camera-previews"))
        return await asyncio.to_thread(
            service.scanning.capture_previews, output_dir,
        )

    @app.get("/api/dashboard/setup/camera-preview/{index}")
    async def setup_camera_preview_image(index: int):
        from fastapi.responses import FileResponse

        preview_dir = Path("/tmp/roboclaw-camera-previews")
        for f in preview_dir.glob(f"{index:02d}_*.jpg"):
            return FileResponse(str(f), media_type="image/jpeg")
        raise HTTPException(404, f"Preview not found for camera index {index}")

    @app.post("/api/dashboard/setup/motion/start")
    async def motion_start() -> dict[str, Any]:
        port_count = await asyncio.to_thread(
            service.scanning.start_motion_detection,
        )
        return {"status": "watching", "port_count": port_count}

    @app.get("/api/dashboard/setup/motion/poll")
    async def motion_poll() -> dict[str, Any]:
        results = await asyncio.to_thread(service.scanning.poll_motion)
        return {"ports": results}

    @app.post("/api/dashboard/setup/motion/stop")
    async def motion_stop() -> dict[str, str]:
        await asyncio.to_thread(service.scanning.stop_motion_detection)
        return {"status": "stopped"}

    @app.post("/api/dashboard/setup/arm")
    async def setup_add_arm(body: AddArmRequest) -> dict[str, Any]:
        await asyncio.to_thread(set_arm, body.alias, body.arm_type, body.port_id)
        return {"status": "added", "alias": body.alias}

    @app.delete("/api/dashboard/setup/arm/{alias}")
    async def setup_remove_arm(alias: str) -> dict[str, str]:
        await asyncio.to_thread(remove_arm, alias)
        return {"status": "removed", "alias": alias}

    @app.patch("/api/dashboard/setup/arm/{alias}/rename")
    async def setup_rename_arm(alias: str, body: RenameRequest) -> dict[str, str]:
        await asyncio.to_thread(rename_arm, alias, body.new_alias)
        return {"status": "renamed", "old": alias, "new": body.new_alias}

    @app.post("/api/dashboard/setup/camera")
    async def setup_add_camera(body: AddCameraRequest) -> dict[str, Any]:
        await asyncio.to_thread(set_camera, body.alias, body.camera_index)
        return {"status": "added", "alias": body.alias}

    @app.delete("/api/dashboard/setup/camera/{alias}")
    async def setup_remove_camera(alias: str) -> dict[str, str]:
        await asyncio.to_thread(remove_camera, alias)
        return {"status": "removed", "alias": alias}

    @app.get("/api/dashboard/setup/current")
    async def setup_current() -> dict[str, Any]:
        setup = load_setup()
        return {
            "arms": setup.get("arms", []),
            "cameras": setup.get("cameras", []),
            "hands": setup.get("hands", []),
        }
