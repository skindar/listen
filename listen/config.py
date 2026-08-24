"""Listen configuration: constants, env overrides, resource/model resolution."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- engine / model ----------------------------------------------------------

MODEL_REPO = "nvidia/nemotron-3.5-asr-streaming-0.6b"
# The official HF repo ships this single Q8_0 GGUF (≈707 MB). The model
# auto-detects 40 language-locales, so there is no language setting.
MODEL_FILENAME = "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
MODEL_GLOBS = ("*q8_0*.gguf", "*.gguf")

DATA_DIR = Path.home() / ".listen"
MODEL_DIR = DATA_DIR / "models"
SETTINGS_PATH = DATA_DIR / "settings.json"
APP_LOCK = DATA_DIR / "app.lock"
SERVER_PIDFILE = DATA_DIR / "server.pid"
LOG_PATH = Path.home() / "Library" / "Logs" / "listen.log"
SERVER_LOG_PATH = Path.home() / "Library" / "Logs" / "listen-server.log"

# --- network / audio / hotkey ------------------------------------------------

HOST = "127.0.0.1"
# Debug-only fixed port override. Default: pick a free ephemeral loopback port
# at every server start, so Listen never collides with other local services.
FIXED_PORT = int(os.environ["LISTEN_PORT"]) if "LISTEN_PORT" in os.environ else None

SAMPLE_RATE = 16000
CHANNELS = 1
HOTKEY_KEYCODE = 0x3D  # kVK_RightOption (default; user-changeable in the menu)
MIN_RECORD_SECONDS = 0.3  # shorter taps are ignored as accidental
# Realtime ASR utterance endpointing: silence that finalizes a phrase during
# streaming, so finished phrases paste live on natural pauses. Low enough to
# fire on clause/sentence pauses, high enough not to split every word gap.
ENDPOINTING_MS = 450
# Liveness probe for the realtime WebSocket: send a PING every INTERVAL seconds;
# if the server has shown it keepalives (PONGs our PING or sends its own PING)
# but then stays silent past DEADLINE, the session is wedged and is closed.
REALTIME_PING_INTERVAL = 8.0
REALTIME_PING_DEADLINE = 20.0


# --- resource resolution (works inside .app bundle and in dev) ---------------

def _bundle_resources() -> Path | None:
    """Contents/Resources if running inside OUR py2app bundle, else None.

    Reliable across dev runs (where NSBundle.mainBundle() is the venv's
    Python.app, which also ends in .app): we check sys.executable's sibling
    Resources dir for our nemo-speech binary.
    """
    exe = Path(sys.executable).resolve()
    resources = exe.parent.parent / "Resources"  # Contents/MacOS -> Contents/Resources
    if (resources / "nemo-speech" / "bin" / "nemo-speech").is_file():
        return resources
    return None


def _pkg_resources() -> Path:
    """The resources/ dir inside the listen package (dev runs)."""
    return Path(__file__).resolve().parent / "resources"


def _resource_path(*parts: str) -> Path:
    """Resolve a path under nemo-speech/, preferring the bundle then the pkg.

    Works inside the .app bundle (Contents/Resources) and in dev (package
    resources/) — the one place the bundle/pkg fallback is decided.
    """
    base = _bundle_resources()
    if base is None:
        base = _pkg_resources()
    return base.joinpath("nemo-speech", *parts)


def nemo_binary() -> Path:
    """Path to the nemo-speech executable."""
    return _resource_path("bin", "nemo-speech")


def nemo_lib_dir() -> Path:
    """Directory holding nemo-speech dylibs (for DYLD_LIBRARY_PATH)."""
    return _resource_path("lib")


def nemo_share_dir() -> Path:
    """Directory holding nemo-speech share data (model-index.json with sha256s)."""
    return _resource_path("share", "nemo-speech")


# --- model -------------------------------------------------------------------

def model_url() -> str:
    return f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILENAME}"


def resolve_model_path() -> Path | None:
    """Locate the ASR GGUF in ~/.listen/models. None if not downloaded yet."""
    for glob in MODEL_GLOBS:
        matches = sorted(MODEL_DIR.rglob(glob))
        if matches:
            return matches[0]
    return None
