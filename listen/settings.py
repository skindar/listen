"""Persisted user settings: ~/.listen/settings.json (atomic writes).

Only two knobs exist — the hotkey and the transcription language. Autostart
is NOT stored here: its source of truth is the LaunchAgent itself
(autostart.is_on()), so the two can never disagree.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config, hotkey, languages

log = logging.getLogger("listen")

DEFAULT_HOTKEY = dict(hotkey.HotkeyLogic.DEFAULT_SPEC)


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config.SETTINGS_PATH
        self.hotkey: dict = dict(DEFAULT_HOTKEY)
        self.language: str | None = None  # None = auto-detect
        self.load()

    def load(self) -> None:
        """Read settings; any problem falls back to defaults (never raises)."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:
            log.exception("settings unreadable, using defaults: %s", self._path)
            return
        if not isinstance(data, dict):
            log.warning("settings malformed, using defaults: %s", self._path)
            return
        hk = data.get("hotkey")
        if isinstance(hk, dict) and isinstance(hk.get("keycode"), int):
            self.hotkey = hotkey.normalize_spec(hk)
        language = data.get("language")
        if language is None or languages.is_supported(language):
            self.language = language
        else:
            log.warning("ignoring unknown language %r", language)
            self.language = None

    def save(self) -> None:
        data = {"hotkey": self.hotkey, "language": self.language}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._path)  # atomic on the same directory
        except Exception:
            log.exception("failed to save settings to %s", self._path)

    def set_hotkey(self, spec: dict) -> None:
        self.hotkey = hotkey.normalize_spec(spec)
        self.save()

    def set_language(self, code: str | None) -> None:
        if code is not None and not languages.is_supported(code):
            return
        self.language = code
        self.save()