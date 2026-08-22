"""Language-locales the ASR model supports (transcription-ready only).

`None` everywhere means auto-detect — the model's default.
"""
from __future__ import annotations

# Transcription-ready.
READY: list[tuple[str, str]] = [
    ("ar-AR", "Arabic"),
    ("nl-NL", "Dutch"),
    ("en-GB", "English (UK)"),
    ("en-US", "English (US)"),
    ("fr-FR", "French"),
    ("fr-CA", "French (Canada)"),
    ("de-DE", "German"),
    ("hi-IN", "Hindi"),
    ("it-IT", "Italian"),
    ("ja-JP", "Japanese"),
    ("ko-KR", "Korean"),
    ("pt-PT", "Portuguese"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("ru-RU", "Russian"),
    ("es-ES", "Spanish (Spain)"),
    ("es-US", "Spanish (US)"),
    ("tr-TR", "Turkish"),
    ("uk-UA", "Ukrainian"),
    ("vi-VN", "Vietnamese"),
]

_ALL = dict(READY)


def is_supported(code: str | None) -> bool:
    return code is not None and code in _ALL


def label(code: str | None) -> str:
    """Human name for the menu; None → "Auto"."""
    return "Auto" if code is None else _ALL.get(code, code)