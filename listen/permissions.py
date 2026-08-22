"""macOS TCC permissions: Accessibility (hotkey + paste) and Microphone.

Two independent permissions; neither substitutes the other. Accessibility can
be queried at any time; the microphone can only be *probed* — opening an input
stream is the moment macOS shows its prompt, and a PortAudio failure means
"denied". That is why the app records first and reports MIC_DENIED on failure
instead of pre-checking.
"""
from __future__ import annotations

import logging
import subprocess

from . import config

log = logging.getLogger("listen")

# macOS 13+ deep links (System Settings → Privacy & Security). The older
# com.apple.systempreferences target silently lands on an unrelated pane.
AX_URL = (
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity"
    "?Privacy_Accessibility"
)
MIC_URL = (
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity"
    "?Privacy_Microphone"
)


def accessibility_trusted(prompt: bool = False) -> bool:
    """Is this process a trusted Accessibility client? Never raises.

    With prompt=True (unused by the app — the menu links are friendlier than
    the system alert) macOS also shows its own grant dialog when denied.
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        options = {kAXTrustedCheckOptionPrompt: prompt} if prompt else None
        return bool(AXIsProcessTrustedWithOptions(options))
    except Exception:
        pass

    try:
        import ctypes

        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        log.exception("AXIsProcessTrusted unavailable")
        return False


def open_accessibility_settings() -> None:
    """Deep-link to System Settings → Privacy & Security → Accessibility."""
    subprocess.Popen(["open", AX_URL])


def open_microphone_settings() -> None:
    """Deep-link to System Settings → Privacy & Security → Microphone."""
    subprocess.Popen(["open", MIC_URL])


def mic_available() -> bool:
    """Probe the microphone by opening a short input stream.

    This is the call that triggers the TCC prompt when the decision is still
    pending. Returns False when access is denied or no device is present.
    Never to be called on the main thread — opening a device can block.
    """
    try:
        import sounddevice as sd

        stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE, channels=config.CHANNELS, dtype="int16"
        )
        stream.start()
        stream.stop()
        stream.close()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("microphone probe failed: %s", exc)
        return False
