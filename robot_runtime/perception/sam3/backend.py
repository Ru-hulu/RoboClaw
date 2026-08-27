"""Worker-local adapter for the pinned official SAM3 image model."""

from __future__ import annotations

import importlib
import hashlib
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from PIL import Image

from .config import EXPECTED_CHECKPOINT_SIZE, Sam3RuntimeConfig
from .engine import BackendOutput
from .errors import Sam3ErrorCode, Sam3RuntimeError


ModuleImporter = Callable[[str], Any]
RevisionReader = Callable[[Path], str]
FileSizeReader = Callable[[Path], int]
SourceStatusReader = Callable[[Path], str]
CheckpointDigestReader = Callable[[Path], str]


class OfficialSam3Backend:
    """Load and run the official SAM3 processor inside the GPU worker."""

    def __init__(
        self,
        config: Sam3RuntimeConfig,
        *,
        module_importer: ModuleImporter = importlib.import_module,
        revision_reader: RevisionReader | None = None,
        file_size_reader: FileSizeReader | None = None,
        source_status_reader: SourceStatusReader | None = None,
        checkpoint_digest_reader: CheckpointDigestReader | None = None,
    ) -> None:
        self._config = config
        self._module_importer = module_importer
        self._revision_reader = revision_reader or _read_git_revision
        self._file_size_reader = file_size_reader or _file_size
        self._source_status_reader = source_status_reader or _read_git_status
        self._checkpoint_digest_reader = (
            checkpoint_digest_reader or _sha256_file
        )
        self._processor: Any | None = None
        self._torch: ModuleType | Any | None = None
        self._load_duration_ms: float | None = None

    def load(self) -> float:
        """Validate deployment artifacts and load the model exactly once."""

        if self._load_duration_ms is not None:
            return self._load_duration_ms

        revision = self._revision_reader(self._config.source_path).strip()
        if revision != self._config.source_revision:
            raise Sam3RuntimeError(
                Sam3ErrorCode.SOURCE_REVISION_MISMATCH,
                "SAM3 source revision does not match the pinned RoboClaw revision.",
            )
        source_status = self._source_status_reader(self._config.source_path).strip()
        if source_status:
            raise Sam3RuntimeError(
                Sam3ErrorCode.SOURCE_REVISION_MISMATCH,
                "SAM3 source checkout is dirty; restore the pinned clean revision.",
            )
        checkpoint_size = self._file_size_reader(self._config.checkpoint_path)
        if checkpoint_size != EXPECTED_CHECKPOINT_SIZE:
            raise Sam3RuntimeError(
                Sam3ErrorCode.CHECKPOINT_MISMATCH,
                "SAM3 checkpoint size mismatch: expected "
                f"{EXPECTED_CHECKPOINT_SIZE} bytes, found {checkpoint_size} bytes.",
            )
        checkpoint_sha256 = self._checkpoint_digest_reader(
            self._config.checkpoint_path
        ).strip().lower()
        if checkpoint_sha256 != self._config.checkpoint_sha256:
            raise Sam3RuntimeError(
                Sam3ErrorCode.CHECKPOINT_MISMATCH,
                "SAM3 checkpoint SHA-256 does not match the configured digest.",
            )

        source_text = str(self._config.source_path)
        if not sys.path or sys.path[0] != source_text:
            sys.path.insert(0, source_text)

        started = time.perf_counter()
        try:
            torch = self._module_importer("torch")
            builder_module = self._module_importer("sam3.model_builder")
            processor_module = self._module_importer(
                "sam3.model.sam3_image_processor"
            )
            model = builder_module.build_sam3_image_model(
                device=self._config.device,
                checkpoint_path=str(self._config.checkpoint_path),
                load_from_HF=False,
            )
            processor = processor_module.Sam3Processor(
                model,
                device=self._config.device,
                confidence_threshold=0.0,
            )
        except Sam3RuntimeError:
            raise
        except Exception as error:
            raise _translate_backend_error(error, during="model load") from error

        self._torch = torch
        self._processor = processor
        self._load_duration_ms = (time.perf_counter() - started) * 1000.0
        return self._load_duration_ms

    def infer(
        self,
        image: Image.Image,
        text_prompt: str,
        confidence_threshold: float,
    ) -> tuple[BackendOutput, float]:
        """Run one text-grounded image inference and copy outputs to CPU."""

        self.load()
        assert self._torch is not None
        assert self._processor is not None
        torch = self._torch
        autocast_context = (
            torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            if self._config.device == "cuda"
            else nullcontext()
        )
        started = time.perf_counter()
        try:
            with torch.inference_mode(), autocast_context:
                self._processor.set_confidence_threshold(confidence_threshold)
                state = self._processor.set_image(image)
                output = self._processor.set_text_prompt(
                    state=state,
                    prompt=text_prompt,
                )
            masks = _tensor_to_numpy(output["masks"], torch.bfloat16)
            boxes = _tensor_to_numpy(output["boxes"], torch.bfloat16)
            scores = _tensor_to_numpy(output["scores"], torch.bfloat16)
        except Exception as error:
            raise _translate_backend_error(error, during="inference") from error
        duration_ms = (time.perf_counter() - started) * 1000.0
        return BackendOutput(masks=masks, boxes=boxes, scores=scores), duration_ms


def _tensor_to_numpy(tensor: Any, bfloat16_dtype: Any) -> np.ndarray:
    cpu_tensor = tensor.detach().cpu()
    if getattr(cpu_tensor, "dtype", None) == bfloat16_dtype:
        cpu_tensor = cpu_tensor.float()
    return np.asarray(cpu_tensor.numpy()).copy()


def _translate_backend_error(error: Exception, *, during: str) -> Sam3RuntimeError:
    error_text = str(error).lower()
    error_name = type(error).__name__.lower()
    if "out of memory" in error_text and "cuda" in error_text or (
        "outofmemory" in error_name
    ):
        return Sam3RuntimeError(
            Sam3ErrorCode.GPU_OOM,
            "SAM3 CUDA memory allocation failed. Unload competing GPU workloads and retry.",
        )
    return Sam3RuntimeError(
        Sam3ErrorCode.MODEL_UNAVAILABLE,
        f"SAM3 {during} failed. Inspect the worker stderr for operator details.",
    )


def _read_git_revision(source_path: Path) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(source_path), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.MODEL_UNAVAILABLE,
            "Cannot read the SAM3 source Git revision.",
        ) from error
    return completed.stdout.strip()


def _read_git_status(source_path: Path) -> str:
    try:
        completed = subprocess.run(
            (
                "git",
                "-C",
                str(source_path),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.MODEL_UNAVAILABLE,
            "Cannot inspect the SAM3 source checkout state.",
        ) from error
    return completed.stdout


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.MODEL_UNAVAILABLE,
            "Cannot read the SAM3 checkpoint metadata.",
        ) from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise Sam3RuntimeError(
            Sam3ErrorCode.MODEL_UNAVAILABLE,
            "Cannot read the SAM3 checkpoint for SHA-256 verification.",
        ) from error
    return digest.hexdigest()
