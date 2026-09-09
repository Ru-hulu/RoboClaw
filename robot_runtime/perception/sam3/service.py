"""

Long-running SAM3 service process managed by MCP lifecycle tools.
The service owns the model worker lifecycle and handles SAM3 segmentation RPC
requests.
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

import lcm

from robot_runtime.perception.lcm_protocol import DecodeImageResult

from .lcm_rgbd_receiver import LcmRgbdReceiver
from .position import estimate_position_from_mask_depth
from .rpc import Sam3RpcServer, Sam3SegmentRequest
from .worker_handle import Sam3WorkerHandle


LCM_POLL_TIMEOUT_MS = 100


def main() -> int:
    worker = Sam3WorkerHandle()
    try:
        worker.start()
        lc = lcm.LCM()
        receiver = LcmRgbdReceiver(lc)
        rpc_server = Sam3RpcServer(lc)
        _emit_stdout(
            {
                "ok": True,
                "message": (
                    "SAM3 model is loaded and the service is listening for "
                    "LCM RGB-D images and SAM3 RPC requests."
                ),
                "worker_pid": worker.pid,
            }
        )
        while worker.is_running:
            request = rpc_server.poll(LCM_POLL_TIMEOUT_MS)
            if request is None:
                continue
            _handle_segment_request(worker, receiver, rpc_server, request)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        _emit_stdout({"ok": False, "message": str(error)})
        return 1
    finally:
        worker.close()


def _handle_segment_request(
    worker: Sam3WorkerHandle,
    receiver: LcmRgbdReceiver,
    rpc_server: Sam3RpcServer,
    request: Sam3SegmentRequest,
) -> None:
    receiver.begin_capture()
    try:
        if not _wait_for_rgbd(receiver, worker, request.frame_timeout_sec):
            rpc_server.respond_error(
                request.request_id,
                "Timed out before receiving RGB-D images from LCM.",
            )
            return
        assert receiver.color is not None
        assert receiver.depth is not None
        result = worker.infer_frame(
            request.request_id,
            receiver.color,
            request.text_prompt,
            request.confidence_threshold,
        )
        result = dict(result)
        position = estimate_position_from_mask_depth(result, receiver.depth)
        result["position_valid"] = position is not None
        result["position"] = position
        rpc_server.respond_success(request.request_id, result)
    except Exception as error:
        rpc_server.respond_error(request.request_id, str(error))
    finally:
        receiver.cancel_capture()


def _wait_for_rgbd(
    receiver: LcmRgbdReceiver,
    worker: Sam3WorkerHandle,
    timeout_sec: float,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline and worker.is_running:
        if receiver.color is not None and receiver.depth is not None:
            return True
        receiver.poll(LCM_POLL_TIMEOUT_MS)
    return receiver.color is not None and receiver.depth is not None


def _emit_stdout(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
