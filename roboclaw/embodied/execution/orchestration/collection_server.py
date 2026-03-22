"""Lightweight HTTP dashboard for data collection monitoring."""

from __future__ import annotations

import asyncio
import json
from html import escape
from typing import Any


class CollectionDashboard:
    """Lightweight HTTP server for data collection monitoring."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9876):
        self.host = host
        self.port = port
        self._state: dict[str, Any] = {
            "status": "idle",
            "current_episode": 0,
            "total_episodes": 0,
            "skill_name": "",
            "latest_joints": {},
            "latest_sensors": [],
            "progress_log": [],
        }
        self._server: asyncio.AbstractServer | None = None

    def update(self, **kwargs: Any) -> None:
        self._state.update(kwargs)

    def add_log(self, message: str) -> None:
        logs = [*self._state["progress_log"], message]
        self._state["progress_log"] = logs[-50:]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        if sockets := self._server.sockets:
            self.port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.readuntil(b"\r\n\r\n")
            try:
                _, path, _ = data.decode("utf-8", errors="ignore").split("\r\n", 1)[0].split(" ", 2)
            except ValueError:
                path = "/"
            path = path.split("?", 1)[0]
            if path == "/api/state":
                body = json.dumps(self._state).encode("utf-8")
                response = self._response("200 OK", "application/json; charset=utf-8", body)
            elif path == "/":
                response = self._response("200 OK", "text/html; charset=utf-8", self._html().encode("utf-8"))
            else:
                response = self._response("404 Not Found", "text/plain; charset=utf-8", b"not found")
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def _response(self, status: str, content_type: str, body: bytes) -> bytes:
        headers = [
            f"HTTP/1.1 {status}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        return "\r\n".join(headers).encode("utf-8") + body

    def _html(self) -> str:
        title = escape("RoboClaw Collection Dashboard")
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title><style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;background:#f6f7fb;color:#1d2433}}
.card{{background:#fff;border:1px solid #dde3ee;border-radius:10px;padding:16px;margin:12px 0;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:6px 8px;border-bottom:1px solid #eef2f8;text-align:left;font-size:14px}}
pre{{margin:0;max-height:260px;overflow:auto;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px}}
ul{{margin:0;padding-left:18px}}
</style></head><body>
<h1>{title}</h1>
<div class="card"><strong>Status:</strong> <span id="status">idle</span><br><strong>Episode:</strong> <span id="episode">0/0</span><br><strong>Skill:</strong> <span id="skill">-</span></div>
<div class="card"><h2>Joint States</h2><table><thead><tr><th>Joint</th><th>Position</th></tr></thead><tbody id="joints"><tr><td colspan="2">No data</td></tr></tbody></table></div>
<div class="card"><h2>Sensors</h2><ul id="sensors"><li>No captures yet</li></ul></div>
<div class="card"><h2>Progress Log</h2><pre id="log"></pre></div>
<script>
async function refresh(){{
const s=await fetch('/api/state').then(r=>r.json());
document.getElementById('status').textContent=s.status;
document.getElementById('episode').textContent=`${{s.current_episode}}/${{s.total_episodes}}`;
document.getElementById('skill').textContent=s.skill_name||'-';
const joints=Object.entries(s.latest_joints||{{}});document.getElementById('joints').innerHTML=joints.length?joints.map(([k,v])=>`<tr><td>${{k}}</td><td>${{v}}</td></tr>`).join(''):'<tr><td colspan="2">No data</td></tr>';
const sensors=s.latest_sensors||[];document.getElementById('sensors').innerHTML=sensors.length?sensors.map(x=>`<li>${{x.sensor_id}}: ${{x.captured?'captured':'missing'}}${{x.path_or_ref?' ('+x.path_or_ref+')':''}}</li>`).join(''):'<li>No captures yet</li>';
document.getElementById('log').textContent=(s.progress_log||[]).slice(-20).join('\\n');
}}
refresh();setInterval(refresh,1000);
</script></body></html>"""
