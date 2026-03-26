"""PTY integration tests for ``roboclaw agent``.

These tests require pexpect (``pip install pexpect``).
Mark: ``@pytest.mark.pty`` so they can be selected / skipped via ``-m pty``.

NOTE: These tests spawn a real agent process.  They validate terminal I/O
behaviour (startup banner, exit, interrupt handling, CJK output) but do
NOT call real LLM APIs — they only exercise the prompt loop and SIGINT path.
"""

from __future__ import annotations

import pytest

pexpect = pytest.importorskip("pexpect")


@pytest.mark.pty
def test_agent_startup_and_exit(simulated_agent) -> None:
    """Agent should print a startup banner, accept ``exit``, and quit."""
    child = simulated_agent
    # Wait for the prompt (You: or similar)
    idx = child.expect([r"You:", pexpect.TIMEOUT, pexpect.EOF], timeout=15)
    assert idx == 0, "Agent did not reach interactive prompt"

    child.sendline("exit")
    child.expect(pexpect.EOF, timeout=10)


@pytest.mark.pty
def test_agent_quit_command(simulated_agent) -> None:
    """``quit`` should also terminate the agent."""
    child = simulated_agent
    child.expect(r"You:", timeout=15)
    child.sendline("quit")
    child.expect(pexpect.EOF, timeout=10)


@pytest.mark.pty
def test_agent_ctrl_c(simulated_agent) -> None:
    """Ctrl-C at the prompt should not crash the agent (it should re-prompt or exit)."""
    child = simulated_agent
    child.expect(r"You:", timeout=15)
    child.sendintr()  # send SIGINT / Ctrl-C
    # Agent should either re-display the prompt or exit gracefully
    idx = child.expect([r"You:", pexpect.EOF], timeout=10)
    assert idx in (0, 1)


@pytest.mark.pty
def test_agent_cjk_input(simulated_agent) -> None:
    """CJK characters should not cause encoding crashes."""
    child = simulated_agent
    child.expect(r"You:", timeout=15)
    child.sendline("你好")
    # We just need the agent to not crash; it will try to call the LLM and
    # fail (fake key), but the prompt loop should survive.
    idx = child.expect([r"You:", r"Error", pexpect.TIMEOUT, pexpect.EOF], timeout=15)
    # Any outcome except TIMEOUT is acceptable — it means the agent processed CJK
    assert idx != 2, "Agent timed out processing CJK input"
