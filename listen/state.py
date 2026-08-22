"""AppState: the single source of truth for what the app is doing.

`app.py` derives the menu-bar icon, tooltip and menu from this one enum —
nothing else flips icons directly. NEEDS_AX is an *overlay*: while
Accessibility is missing, the app idles in NEEDS_AX regardless of the
underlying base state (which still tracks the server underneath).
"""
from __future__ import annotations

import enum


class AppState(enum.Enum):
    NEEDS_AX = "needs_ax"        # Accessibility not granted — hotkey disabled
    LOADING = "loading"          # server starting / model warming up
    READY = "ready"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    MIC_DENIED = "mic_denied"    # user refused the microphone TCC prompt
    ERROR = "error"              # server failed / transcription failed


# Convenience aliases so call sites read `state.READY` instead of
# `state.AppState.READY`.
NEEDS_AX = AppState.NEEDS_AX
LOADING = AppState.LOADING
READY = AppState.READY
RECORDING = AppState.RECORDING
TRANSCRIBING = AppState.TRANSCRIBING
MIC_DENIED = AppState.MIC_DENIED
ERROR = AppState.ERROR
