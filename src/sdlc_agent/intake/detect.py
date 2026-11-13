"""Detect what kind of input arrived."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..state.models import InputType, RawInput

DOC_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
APP_STORE_HOSTS = {"apps.apple.com", "play.google.com"}


def detect_input_type(raw: RawInput) -> InputType:
    if raw.kind == "url":
        host = urlparse(raw.value).netloc.lower()
        return InputType.APP_STORE_URL if host in APP_STORE_HOSTS else InputType.URL
    if raw.kind == "file":
        ext = Path(raw.value).suffix.lower()
        if ext in IMG_EXT:
            return InputType.IMAGE
        if ext in DOC_EXT:
            return InputType.DOCUMENT
        raise ValueError(f"Unsupported file type '{ext}'. Supported: {sorted(DOC_EXT | IMG_EXT)}")
    text = raw.value.strip()
    if "\n" not in text and len(text) <= 200:
        return InputType.ONE_LINE
    return InputType.NOTES


def overall_input_type(inputs: list[RawInput]) -> InputType:
    kinds = {r.detected_type or detect_input_type(r) for r in inputs}
    if not kinds:
        raise ValueError("No input provided")
    return kinds.pop() if len(kinds) == 1 else InputType.MIXED
