from types import SimpleNamespace

import pytest

from roboclaw.embodied.execution.integration.adapters.model import SensorCaptureResult
from roboclaw.embodied.execution.orchestration.skills import SkillSpec, SkillStep
from roboclaw.embodied.execution.orchestration.supervision import record_episode

class FakeExecutor:
    async def execute_move(self, context, *, primitive_name, primitive_args=None, on_progress=None):
        return SimpleNamespace(ok=True, details={"state_before": {}, "state_after": {}, "state_changed": True, "joints_moved": ["joint"]})

    async def capture_sensor(self, sensor_id: str, mode: str = "latest") -> SensorCaptureResult:
        return SensorCaptureResult(sensor_id=sensor_id, captured=True, media_type="image/jpeg", payload_ref="memory://frame.jpg")

@pytest.mark.asyncio
@pytest.mark.parametrize(("sensors", "expected"), [((SimpleNamespace(sensor_id="cam0"),), [{"sensor_id": "cam0", "captured": True, "media_type": "image/jpeg", "path_or_ref": "memory://frame.jpg"}]), ((), [])])
async def test_record_episode_sensors(tmp_path, sensors, expected) -> None:
    record = await record_episode(
        FakeExecutor(),
        SimpleNamespace(setup_id="demo", assembly=SimpleNamespace(sensors=sensors)),
        SkillSpec("pick", "Pick.", (SkillStep("go_named_pose"),)),
        1,
        output_dir=tmp_path,
    )
    assert record["steps"][0]["sensors"] == expected
