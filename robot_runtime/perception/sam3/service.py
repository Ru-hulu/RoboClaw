"""

Long-running SAM3 service process managed by MCP lifecycle tools.
The service owns the model worker lifecycle. Its inference RPC interface will be
added separately.
MCP Server 进程
  └─ Service 进程
       └─ Worker 进程
MCP Server → Service
        主要读取 Service stdout 的启动结果
        生命周期控制依靠进程句柄和 Unix 信号

Service ⇄ Worker
        使用 stdin/stdout JSON Lines 双向通信

"""

from __future__ import annotations

import json
import time

from .worker_client import Sam3WorkerClient


WORKER_POLL_INTERVAL_SEC = 0.25


def main() -> int:
    worker = Sam3WorkerClient()
    try:
        worker.start()
        _emit_stdout(
            {
                "ok": True,
                "message": "SAM3 model is loaded and the service is ready.",
                "worker_pid": worker.pid,
            }
        )
        while worker.is_running:
            time.sleep(WORKER_POLL_INTERVAL_SEC)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        _emit_stdout({"ok": False, "message": str(error)})
        return 1
    finally:
        worker.close()


def _emit_stdout(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
