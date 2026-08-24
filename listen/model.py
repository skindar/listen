"""One-time model download from Hugging Face (streaming, dependency-free),
verified against the sha256 shipped in the bundled model-index.json."""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger("listen")


class Cancelled(Exception):
    """Raised by download() when its cancel event is set."""


def model_path() -> Path:
    return config.MODEL_DIR / config.MODEL_FILENAME


def expected_sha256() -> str | None:
    """The asr artifact hash from the bundled model-index.json, if readable."""
    index = config.nemo_share_dir() / "model-index.json"
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
        for entry in data.get("models", []):
            if entry.get("repo") != config.MODEL_REPO:
                continue
            for artifact in entry.get("artifacts", []):
                if artifact.get("role") == "asr" and artifact.get(
                    "filename"
                ) == config.MODEL_FILENAME:
                    return artifact.get("sha256")
    except Exception:
        log.exception("model-index.json unreadable; skipping sha256 check")
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _marker(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".ok")


def ensure_verified(dest: Path) -> None:
    """Check the model hash once (a marker file skips repeats).

    Raises RuntimeError (and deletes the bad file) on mismatch, so the next
    run re-downloads instead of failing deep inside the engine.
    """
    if _marker(dest).is_file():
        return
    expected = expected_sha256()
    if expected is None:
        return  # nothing to verify against
    actual = _sha256_file(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            "model file failed its sha256 check — deleted; "
            "re-launch to download again"
        )
    _marker(dest).write_text("verified\n")


def download(progress=None, cancel=None) -> Path:
    """Download the ASR model to ~/.listen/models.

    `progress(downloaded, total)` is called periodically (total may be None
    if the server omits Content-Length). Safe to call from any thread; the
    caller is responsible for marshalling progress onto the main thread.

    `cancel` is an optional threading.Event: if set mid-download, the partial
    file is deleted and Cancelled is raised, so a re-run starts fresh.
    """
    url = config.model_url()
    dest = model_path()
    part = dest.with_suffix(dest.suffix + ".part")
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Resume / reverify: if the final file already exists, verify once, keep it.
    if dest.is_file():
        try:
            ensure_verified(dest)
            log.info("model already present at %s", dest)
            if progress:
                progress(dest.stat().st_size, dest.stat().st_size)
            return dest
        except RuntimeError:
            log.warning("existing model failed verification; re-downloading")

    log.info("downloading %s -> %s", url, part)
    req = urllib.request.Request(url, headers={"User-Agent": "listen/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = resp.length  # may be None
            downloaded = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    except Cancelled:
        part.unlink(missing_ok=True)
        raise
    part.rename(dest)
    log.info("model downloaded: %s", dest)
    ensure_verified(dest)
    log.info("model sha256 verified")
    if progress:
        progress(dest.stat().st_size, dest.stat().st_size)
    return dest
