from __future__ import annotations

from pathlib import Path

import pytest

from roboclaw.agent.tools.registry import ToolRegistry
from roboclaw.embodied.intent import IntentClassifier
from roboclaw.embodied.onboarding import OnboardingController


def _classifier(llm_caller=None) -> IntentClassifier:
    robot_aliases = {
        "so101": ("so101", "so-101", "leader arm"),
        "demo_bot": ("demo bot", "demo arm"),
        "piperx": ("piperx", "piper x"),
    }
    return IntentClassifier(
        llm_caller=llm_caller,
        known_robots=tuple(robot_aliases),
        robot_aliases=robot_aliases,
    )


@pytest.mark.asyncio
async def test_keyword_fallback_without_llm() -> None:
    classifier = _classifier()

    intent = await classifier.classify("Please connect my so101 on /dev/ttyACM0")

    assert intent.wants_setup is True
    assert intent.robot_id == "so101"
    assert intent.serial_path == "/dev/ttyACM0"
    assert intent.is_embodied is True


@pytest.mark.asyncio
async def test_keyword_fallback_detects_simulation_requests_in_multiple_languages() -> None:
    classifier = _classifier()

    english = await classifier.classify("I have no robot, I want to try simulation")
    chinese = await classifier.classify("我没有机器人，想试试仿真")

    assert english.wants_simulation is True
    assert chinese.wants_simulation is True


@pytest.mark.asyncio
async def test_keyword_fallback_detects_robot_ids_from_aliases() -> None:
    classifier = _classifier()

    intent = await classifier.classify("please connect my demo arm")

    assert intent.robot_id == "demo_bot"
    assert intent.wants_setup is True


@pytest.mark.asyncio
async def test_keyword_fallback_detects_connection_status() -> None:
    classifier = _classifier()

    connected = await classifier.classify("Everything is connected")
    not_connected = await classifier.classify("机器人还没连")

    assert connected.connection_confirmed is True
    assert not_connected.connection_confirmed is False


@pytest.mark.asyncio
async def test_keyword_fallback_detects_calibration_requests() -> None:
    classifier = _classifier()

    english = await classifier.classify("help me calibrate the robot")
    chinese = await classifier.classify("帮我校准")

    assert english.wants_calibration is True
    assert chinese.wants_calibration is True


@pytest.mark.asyncio
async def test_llm_classifier_uses_structured_json_response() -> None:
    async def llm(system_prompt: str, user_message: str) -> str:
        assert "Available robots: so101, demo_bot, piperx" in system_prompt
        assert "User message: set up my SO-101 in simulation" == user_message
        return """```json
{"wants_setup": true, "wants_simulation": true, "robot_id": "SO-101", "is_embodied": true}
```"""

    classifier = _classifier(llm_caller=llm)

    intent = await classifier.classify("set up my SO-101 in simulation", context="initial")

    assert intent.wants_setup is True
    assert intent.wants_simulation is True
    assert intent.robot_id == "so101"
    assert intent.is_embodied is True


@pytest.mark.asyncio
async def test_llm_classifier_falls_back_on_malformed_response() -> None:
    async def llm(system_prompt: str, user_message: str) -> str:
        return "definitely not json"

    classifier = _classifier(llm_caller=llm)

    intent = await classifier.classify("I have no robot, I want to try simulation")

    assert intent.wants_simulation is True
    assert intent.wants_setup is True


@pytest.mark.asyncio
async def test_llm_classifier_falls_back_when_llm_raises() -> None:
    async def llm(system_prompt: str, user_message: str) -> str:
        raise RuntimeError("boom")

    classifier = _classifier(llm_caller=llm)

    intent = await classifier.classify("please connect my demo arm")

    assert intent.robot_id == "demo_bot"
    assert intent.wants_setup is True


@pytest.mark.asyncio
async def test_onboarding_controller_caches_intent_per_message(tmp_path: Path) -> None:
    controller = OnboardingController(tmp_path, ToolRegistry())
    calls = 0

    async def llm(system_prompt: str, user_message: str) -> str:
        nonlocal calls
        calls += 1
        return '{"wants_setup": true, "robot_id": "so101", "is_embodied": true}'

    controller.set_llm_caller(llm)

    first = await controller._classify("connect so101")
    second = await controller._classify("connect so101")

    assert first == second
    assert calls == 1
