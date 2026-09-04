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

from .lcm_rgbd_receiver import LcmRgbdReceiver
from .worker_handle import Sam3WorkerHandle


LCM_POLL_TIMEOUT_MS = 100


def main() -> int:
    worker = Sam3WorkerHandle()
    try:
        worker.start()
        receiver = LcmRgbdReceiver()
        _emit_stdout(
            {
                "ok": True,
                "message": (
                    "SAM3 model is loaded and the service is listening for "
                    "LCM RGB-D images."
                ),
                "worker_pid": worker.pid,
            }
        )
        while worker.is_running:
            receiver.poll(LCM_POLL_TIMEOUT_MS)
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
