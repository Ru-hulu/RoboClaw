# Development Guide

## Prerequisites

- Python 3.11+
- Git

## Local Setup

```bash
# Clone & install in editable mode with dev extras
git clone https://github.com/MINT-SJTU/RoboClaw.git
cd RoboClaw
pip install -e ".[dev]"

# First-time setup (creates ~/.roboclaw/config.json & workspace)
roboclaw onboard
```

## Running Tests

```bash
# Unit tests (no hardware required)
python -m pytest tests/ -x -q

# Skip PTY integration tests (useful in minimal CI environments)
python -m pytest tests/ -x -q -m "not pty"

# Run only PTY integration tests
python -m pytest tests/integration/ -x -q -m pty
```

## Simulation Mode

Set `ROBOCLAW_SIMULATE=1` to replace real hardware calls with deterministic
stubs.  This allows the full embodied pipeline (scan, identify, calibrate,
teleoperate, record) to run on a laptop without any robot arms or cameras.

```bash
# Run the agent in simulation
ROBOCLAW_SIMULATE=1 roboclaw agent

# PTY integration tests use simulation automatically
python -m pytest tests/integration/ -x -q -m pty
```

What gets simulated:

| Component | Real behaviour | Simulated behaviour |
|---|---|---|
| `scan_serial_ports()` | reads `/dev/serial/by-*` | returns 2 fake ports |
| `scan_cameras()` | probes `/dev/video*` via OpenCV | returns 1 fake camera |
| `run_interactive()` | spawns a subprocess | returns exit-code 0 immediately |
| `_find_moved_port()` | reads motor positions | picks the first port |

All simulation logic lives in `roboclaw/embodied/simulation.py`.

## Workspace Reset

During development you may want to return to a clean state:

```bash
# Interactive (asks for confirmation)
roboclaw dev reset

# Non-interactive
roboclaw dev reset --yes

# Reset and configure a specific model
roboclaw dev reset --yes --model openai/gpt-4o --api-key sk-...
```

This deletes `~/.roboclaw/workspace` and `~/.roboclaw/config.json`, then
re-runs `roboclaw onboard` non-interactively.

## Environment Variables

| Variable | Purpose |
|---|---|
| `ROBOCLAW_HOME` | Override the base directory (default `~/.roboclaw`). Useful for tests and parallel instances. |
| `ROBOCLAW_SIMULATE` | Set to `1` to activate simulation mode. |

## Troubleshooting

### `ModuleNotFoundError: No module named 'lerobot'`

LeRobot is an optional dependency under the `research` extra:

```bash
pip install -e ".[research]"
```

### PTY tests fail with `ModuleNotFoundError: No module named 'pexpect'`

Install the dev extra:

```bash
pip install -e ".[dev]"
```

### Terminal messed up after Ctrl-C

Run `reset` in your shell to restore terminal settings.

### Tests fail with `roboclaw.config` import errors

Make sure you installed in editable mode:

```bash
pip install -e ".[dev]"
```
