from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import patch

try:
    import lcm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["lcm"] = types.SimpleNamespace(LCM=object)

from robot_runtime.perception.sam3 import service


class FakeWorker:
    def __init__(self) -> None:
        self.pid = 123
        self.started = False
        self.closed = False
        self._running_checks = 0

    def start(self) -> None:
        self.started = True

    @property
    def is_running(self) -> bool:
        self._running_checks += 1
        return self._running_checks <= 2

    def close(self) -> None:
        self.closed = True


class FakeReceiver:
    def __init__(self) -> None:
        self.poll_timeouts: list[int] = []

    def poll(self, timeout_ms: int) -> int:
        self.poll_timeouts.append(timeout_ms)
        return 0


class Sam3ServiceTest(unittest.TestCase):
    def test_polls_lcm_while_worker_is_running(self) -> None:
        worker = FakeWorker()
        receiver = FakeReceiver()
        stdout = io.StringIO()

        with (
            patch.object(service, "Sam3WorkerClient", return_value=worker),
            patch.object(service, "LcmRgbdReceiver", return_value=receiver),
            contextlib.redirect_stdout(stdout),
        ):
            return_code = service.main()

        ready = json.loads(stdout.getvalue().splitlines()[0])
        self.assertTrue(worker.started)
        self.assertTrue(worker.closed)
        self.assertEqual(receiver.poll_timeouts, [100, 100])
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["worker_pid"], 123)
        self.assertEqual(return_code, 1)


if __name__ == "__main__":
    unittest.main()
