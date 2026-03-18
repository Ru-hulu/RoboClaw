from importlib import resources
from pathlib import Path

from roboclaw.utils.helpers import sync_workspace_templates


def test_sync_workspace_templates_skips_python_cache_files(monkeypatch, tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    templates_root = package_root / "templates"
    templates_root.mkdir(parents=True)
    (templates_root / "AGENTS.md").write_text("agent template", encoding="utf-8")

    pycache_dir = templates_root / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "__init__.cpython-311.pyc").write_bytes(b"\xa7\r\r\nbinary")

    monkeypatch.setattr(resources, "files", lambda _package: package_root)

    workspace = tmp_path / "workspace"
    added = sync_workspace_templates(workspace, silent=True)

    assert "AGENTS.md" in added
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "agent template"
    assert not (workspace / "__pycache__").exists()
