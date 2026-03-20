"""Small embodied localization helpers."""

from __future__ import annotations

import re

SUPPORTED_LANGUAGES = {"en", "zh"}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def normalize_language(value: str | None) -> str | None:
    """Map arbitrary language tags onto the supported set."""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("zh") or raw in {"cn", "中文", "chinese"}:
        return "zh"
    if raw.startswith("en") or raw in {"english"}:
        return "en"
    return None


def infer_language(text: str | None) -> str:
    """Infer a coarse preferred response language from user text."""
    if _CJK_RE.search(text or ""):
        return "zh"
    return "en"


def choose_language(*values: str | None) -> str:
    """Pick the first supported language, falling back to English."""
    for value in values:
        normalized = normalize_language(value)
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
    return "en"


def localize_text(language: str | None, *, en: str, zh: str) -> str:
    """Select the user-visible string for the preferred language."""
    return zh if choose_language(language) == "zh" else en
