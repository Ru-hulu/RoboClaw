# SAM3 Image Runtime

This directory contains RoboClaw's inference adapter for text-prompted SAM3 image segmentation. It intentionally contains no SAM3 model source, training code, dataset code, or weights.

## Runtime model

The FastMCP server exposes only lifecycle controls for the SAM3 service:
`start_sam3_perception`, `get_sam3_perception_status`, and
`stop_sam3_perception`. Inference RPC clients will belong to separate business
Tools after the RPC interface is defined.

The current runtime service still contains the temporary LCM target-pose path.
That transport is intentionally outside the lifecycle manager and will be
reworked separately.

Depth-to-3D projection is not implemented yet. A successful segmentation
therefore returns `pose_valid=false`; the received depth frame is retained only
for the duration of that request. The RGB frame is written to a temporary PNG
because the existing worker accepts image paths, then deleted immediately after
the worker replies.

The external SAM3 checkout must use:

- Upstream: `https://github.com/facebookresearch/sam3.git`
- Revision: `6dbb02bd38288df755dfa1378000a861e65b84f6`
- License: the SAM License distributed by the upstream repository

The confirmed checkpoint is:

- Size: `3450062241` bytes
- SHA-256: `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`

Keep the checkout and checkpoint outside the RoboClaw repository.

## Verified RTX 4060 deployment

The pinned stack was exercised end to end on an 8,188 MiB RTX 4060 with
PyTorch 2.10.0+cu128 and torchvision 0.25.0+cu128. On an 1800x1200 test image
with prompt `truck` and threshold `0.3`, one worker load took 7.49 seconds;
the first and second inferences took 562 ms and 361 ms and reused the same
PID. Total GPU usage peaked at 6,043 MiB from a 571 MiB baseline, so the SAM3
increment was about 5,472 MiB. Explicit unload and idle eviction both returned
the card to the 571 MiB baseline.

These figures are deployment evidence, not fixed latency guarantees. A
threshold of `0.0` intentionally retains every candidate and can require much
more memory while full-resolution masks are interpolated. On an 8 GB GPU, use
the default threshold or a task-appropriate positive threshold unless every
candidate is genuinely required.

## Isolated worker environment

The pinned upstream revision expects Python 3.12 and a CUDA-capable PyTorch environment. Create an environment outside this repository, checkout the pinned revision, and install upstream SAM3 into that environment:

```bash
conda create -n sam3 python=3.12 -y
conda activate sam3
git clone https://github.com/facebookresearch/sam3.git /opt/sam3
git -C /opt/sam3 checkout --detach 6dbb02bd38288df755dfa1378000a861e65b84f6
python -m pip install torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cu128
python -m pip install 'setuptools<81' 'mcp>=1,<2' \
  einops pycocotools psutil
python -m pip install -e /opt/sam3
```

Do not run the training entry points. RoboClaw imports only `build_sam3_image_model` and `Sam3Processor` inside the isolated worker.

The extra runtime packages above are intentional. The pinned upstream revision
imports `pkg_resources`, `einops`, `pycocotools`, and `psutil` while constructing
the image model, but does not list all of them in its base dependencies.
`setuptools<81` retains the `pkg_resources` compatibility module required by
that revision. These packages do not install the SAM3 training extras.

The MCP server uses the repository's existing FastMCP 1.x API (`mcp.server.fastmcp`). Use `mcp>=1,<2` in the MCP environment until the repository is migrated to the MCP 2.x import layout.

## Configuration

Set these variables in the process that launches `roboclaw_next.tools.mcp_server`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ROBOCLAW_SAM3_PYTHON` | service process Python | Python executable in the isolated SAM3 worker environment |
| `ROBOCLAW_SAM3_SOURCE` | required | External pinned SAM3 checkout |
| `ROBOCLAW_SAM3_CHECKPOINT` | required | External `sam3.pt` checkpoint |
| `ROBOCLAW_SAM3_CHECKPOINT_SHA256` | confirmed digest | Digest recorded in results |
| `ROBOCLAW_SAM3_DEVICE` | `cuda` | `cuda` or `cpu` |
| `ROBOCLAW_SAM3_INPUT_ROOTS` | repository root | Allowed local input roots separated by the platform path separator |
| `ROBOCLAW_SAM3_OUTPUT_ROOT` | `runtime_data/sam3` | Result directory root |
| `ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC` | `120` | Model-start and inference timeout |
| `ROBOCLAW_SAM3_SERVICE_PYTHON` | MCP process Python | Python executable with `lcm` and `Pillow` used to start the LCM service |
| `ROBOCLAW_SAM3_CAPTURE_ROOT` | `runtime_data/sam3/lcm` | Parent directory for request-scoped temporary RGB files |

Example with deployment-neutral paths:

```bash
export ROBOCLAW_SAM3_PYTHON=/opt/conda/envs/sam3/bin/python
export ROBOCLAW_SAM3_SOURCE=/opt/sam3
export ROBOCLAW_SAM3_CHECKPOINT=/models/sam3.pt
export ROBOCLAW_SAM3_INPUT_ROOTS=/data/robot_images
export ROBOCLAW_SAM3_OUTPUT_ROOT=/var/lib/roboclaw/sam3-results
export ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC=120
export ROBOCLAW_SAM3_SERVICE_PYTHON=/opt/roboclaw-agent-venv/bin/python
export ROBOCLAW_SAM3_CAPTURE_ROOT=/var/lib/roboclaw/sam3-capture
```

Verify deployment artifacts before the first inference:

```bash
git -C "$ROBOCLAW_SAM3_SOURCE" rev-parse HEAD
stat -c '%s' "$ROBOCLAW_SAM3_CHECKPOINT"
sha256sum "$ROBOCLAW_SAM3_CHECKPOINT"
```

The worker repeats these checks before loading the model: it requires the exact
pinned Git revision, rejects a dirty checkout, checks the checkpoint byte size,
and computes and compares the complete checkpoint SHA-256. A malformed optional
SAM3 manager setting is reported by the SAM3 inference tool as
`MODEL_UNAVAILABLE`; it does not prevent the MCP server or unrelated robot tools
from starting.

## CLI

Run one inference without MCP:

```bash
python -m robot_runtime.perception.sam3 infer \
  --image /data/robot_images/frame.png \
  --prompt "red cup" \
  --confidence 0.5
```

Run the JSON Lines worker manually:

```bash
python -m robot_runtime.perception.sam3 serve
```

Run the LCM perception service without MCP:

```bash
python -m robot_runtime.perception.sam3.lcm_service
```

The worker writes protocol JSON only to stdout and operator logs to stderr.
Each protocol message is limited to 4 MiB; an oversized or unreadable message
stops the worker and returns `WORKER_EXITED` instead of leaking a pipe error.

## FastMCP tools

- `start_sam3_perception()` starts the long-running SAM3 perception service.
- `get_sam3_perception_status()` reads the managed service process state and
  reports whether its startup handshake confirmed that the model was loaded.
- `stop_sam3_perception()` stops the managed service process.

These Tools do not accept prompts or perform inference. Future business Tools
will call the SAM3 service through a separately defined RPC client.

## Result files

Each successful request keeps the existing SAM3 worker artifacts:

```text
runtime_data/sam3/<request-id>/result.json
runtime_data/sam3/<request-id>/masks.npz
runtime_data/sam3/<request-id>/mask_000.png
runtime_data/sam3/<request-id>/overlay.png
```

`masks.npz` contains a boolean array named `masks` with shape `(N, H, W)`.
Every mask PNG is single-channel with values 0 and 255. A no-detection request
contains an empty `(0, H, W)` mask array and an overlay of the input image. The
temporary RGB input is not retained.

Artifacts are written to a hidden temporary sibling directory and renamed only after every file is complete. Existing request directories are never overwritten.

## Error codes

| Code | Meaning |
| --- | --- |
| `INVALID_INPUT` | Invalid request, path, image, prompt, threshold, or model output shape |
| `MODEL_UNAVAILABLE` | Missing environment, import, source, checkpoint, or CUDA capability |
| `SOURCE_REVISION_MISMATCH` | External checkout differs from the pinned revision or is dirty |
| `CHECKPOINT_MISMATCH` | Checkpoint size or measured SHA-256 is wrong |
| `GPU_OOM` | CUDA allocation failed; unload competing GPU workloads before retrying |
| `INFERENCE_TIMEOUT` | Startup or inference exceeded the configured deadline |
| `WORKER_EXITED` | Worker stopped or violated the JSON Lines protocol |
| `OUTPUT_EXISTS` | The request ID already has a completed directory |
| `OUTPUT_WRITE_FAILED` | Result files could not be written atomically |

Runtime errors are returned as structured tool results. They do not terminate the MCP stdio server.

## Validation

Run lightweight source and CLI checks without importing the SAM3 model:

```bash
python -m compileall -q robot_runtime/perception/sam3
python -m compileall -q roboclaw_next/tools/builtin/sam3_segmentation
python -m robot_runtime.perception.sam3 --help
```

Real deployment acceptance additionally requires a successful RTX 4060 inference below 6144 MiB SAM3 peak reserved VRAM, a second request that reuses the worker, and evidence that explicit unload and idle eviction return GPU memory close to baseline.
