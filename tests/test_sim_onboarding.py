from __future__ import annotations

from pathlib import Path

import pytest

from roboclaw.agent.tools.filesystem import WriteFileTool
from roboclaw.agent.tools.registry import ToolRegistry
from roboclaw.bus.events import InboundMessage
from roboclaw.embodied.builtins.model import BuiltinEmbodiment
from roboclaw.embodied.definition.components.robots import SO101_ROBOT
from roboclaw.embodied.onboarding import OnboardingController, SETUP_STATE_KEY
from roboclaw.embodied.onboarding.intent_engine import IntentEngine
from roboclaw.session.manager import Session


def _workspace(root: Path) -> ToolRegistry:
    for rel in ("embodied/intake", "embodied/assemblies", "embodied/deployments", "embodied/adapters"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=root))
    return tools


def test_looks_like_sim_request(tmp_path: Path) -> None:
    controller = OnboardingController(tmp_path, ToolRegistry())
    assert controller._looks_like_sim_request("I have no robot, I want to try simulation")
    assert controller._looks_like_sim_request("我没有机器人，想试试仿真")


@pytest.mark.asyncio
async def test_sim_onboarding_asks_viewer_then_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    controller = OnboardingController(tmp_path, _workspace(tmp_path))
    session = Session(key="cli:sim")
    monkeypatch.setattr(
        "roboclaw.embodied.onboarding.controller.list_builtin_embodiments",
        lambda: (BuiltinEmbodiment(id="so101", robot=SO101_ROBOT, sim_model_path="robots/so101.xml"),),
    )

    # Turn 1: triggers sim request -> viewer mode question
    response = await controller.handle_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="sim", content="I have no robot, let me try simulation"),
        session,
    )
    assert "web" in response.content.lower() or "查看" in response.content
    state = session.metadata[SETUP_STATE_KEY]
    assert state["stage"] != "handoff_ready"

    # Turn 2: answer viewer preference -> completes setup
    response = await controller.handle_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="sim", content="web"),
        session,
    )
    state = session.metadata[SETUP_STATE_KEY]
    assert state["stage"] == "handoff_ready"
    assert state["status"] == "ready"
    assert state["deployment_id"].endswith("_sim_local")
    assert state["detected_facts"]["sim_viewer_mode"] == "web"
    assert "标定" not in response.content and "calibration" not in response.content.lower()
    assert "simulation environment is ready" in response.content.lower()


def test_extract_viewer_mode() -> None:
    assert IntentEngine.extract_viewer_mode("网页版") == "web"
    assert IntentEngine.extract_viewer_mode("I want web") == "web"
    assert IntentEngine.extract_viewer_mode("native") == "native"
    assert IntentEngine.extract_viewer_mode("本地窗口") == "native"
    assert IntentEngine.extract_viewer_mode("auto") == "auto"
    assert IntentEngine.extract_viewer_mode("自动") == "auto"
    assert IntentEngine.extract_viewer_mode("hello world") is None
