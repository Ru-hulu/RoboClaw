"""Fixtures for PTY-based integration tests.

These tests spawn ``roboclaw agent`` in a pseudo-terminal via pexpect so
that we can exercise the full interactive flow (spinners, Ctrl-C, CJK
rendering) without real hardware.  The ``ROBOCLAW_SIMULATE=1`` env var
tells the embodied layer to return fake data.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")


@pytest.fixture()
def simulated_home(tmp_path: Path) -> Path:
    """Return a temporary ROBOCLAW_HOME directory with a seeded config."""
    home = tmp_path / ".roboclaw"
    home.mkdir()

    # Minimal config.json so the agent can start
    config = {
        "agents": {"defaults": {"model": "openai/gpt-4o-mini"}},
        "providers": {"openai": {"apiKey": "sk-test-fake-key"}},
    }
    import json

    (home / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return home


@pytest.fixture()
def simulated_agent(simulated_home: Path):
    """Spawn ``roboclaw agent`` inside a pexpect PTY with simulation enabled.

    Yields a *pexpect.spawn* child.  The process is killed on cleanup.
    """
    config_path = str(simulated_home / "config.json")
    env = os.environ.copy()
    env["ROBOCLAW_HOME"] = str(simulated_home)
    env["ROBOCLAW_SIMULATE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Disable prompt_toolkit colour detection issues in CI
    env["NO_COLOR"] = "1"

    child = pexpect.spawn(
        sys.executable,
        ["-m", "roboclaw.cli.commands", "agent", "--config", config_path],
        env=env,
        encoding="utf-8",
        timeout=30,
    )
    yield child

    if child.isalive():
        child.terminate(force=True)
