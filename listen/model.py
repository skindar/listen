"""One-time model download from Hugging Face (streaming, dependency-free),
verified against the sha256 shipped in the bundled model-index.json."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger("listen")


class Cancelled(Exception):
    """Raised by download() when its cancel event is set."""


def model_path() -> Path:
    return config.MODEL_DIR / config.MODEL_FILENAME


def expected_sha256() -> str | None:
    """The asr artifact hash from the bundled model-index.json.

    Returns None if the index is well-formed but lists no hash for this
    artifact (verification is then skipped). An unreadable or unparseable
    index — a broken bundle — is logged loudly and also returns None: the
    model file may still be valid, so we skip verification rather than block
    the app from launching. The catch is narrowed so a genuine programming
    error isn't swallowed.
    """
    index = config.nemo_share_dir() / "model-index.json"
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("model-index.json unreadable (%s); skipping sha256 check", exc)
        return None
    for entry in data.get("models", []):
        if entry.get("repo") != config.MODEL_REPO:
            continue
        for artifact in entry.get("artifacts", []):
            if artifact.get("role") == "asr" and artifact.get(
                "filename"
            ) == config.MODEL_FILENAME:
                return artifact.get("sha256")
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


def download(progress=None, cancel=None, max_retries: int = 5) -> Path:
    """Download the ASR model to ~/.listen/models.

    `progress(downloaded, total)` is called periodically (total may be None
    if the server omits Content-Length). Safe to call from any thread; the
    caller is responsible for marshalling progress onto the main thread.

    `cancel` is an optional threading.Event: if set mid-download, the partial
    file is deleted and Cancelled is raised, so a re-run starts fresh.

    Resumes an interrupted download: a leftover `.part` is continued via an
    HTTP Range request. A dropped connection is retried (resuming from the
    partial) up to `max_retries` times with backoff, so a flaky network on a
    707 MB download doesn't restart from zero.
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
                sz = dest.stat().st_size
                progress(sz, sz)
            return dest
        except RuntimeError:
            log.warning("existing model failed verification; re-downloading")

    attempt = 0
    while True:
        have = part.stat().st_size if part.is_file() else 0
        headers = {"User-Agent": "listen/0.2"}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, \
                    open(part, "ab" if (have and resp.getcode() == 206) else "wb") as out:
                status = resp.getcode()
                if have and status == 206:
                    # Server honors Range: append, total = already-have + remaining.
                    remaining = resp.length
                    total = (have + remaining) if remaining is not None else None
                    downloaded = have
                    log.info("resuming download from %d bytes", have)
                else:
                    # 200 (server ignored Range, or a fresh start): from scratch.
                    total = resp.length
                    downloaded = 0
                    if have:
                        log.info("server ignored Range; restarting download")
                    else:
                        log.info("downloading %s -> %s", url, part)
                # Report at ~1% granularity (every 4 MiB when total is unknown).
                next_report = 0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    chunk = resp.read(1 << 20)  # 1 MiB
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress and downloaded >= next_report:
                        progress(downloaded, total)
                        if total:
                            next_report = (downloaded * 100 // total + 1) * total // 100
                        else:
                            next_report = downloaded + (4 << 20)
            break  # completed
        except Cancelled:
            part.unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have > 0:
                # Range unsatisfiable → the .part already has the full file
                # (a prior run finished but crashed before rename). Finish.
                log.info("download already complete (416); finishing")
                break
            raise RuntimeError(f"model download failed: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            attempt += 1
            if attempt > max_retries:
                raise RuntimeError(
                    f"model download failed after {max_retries} retries: {exc}"
                ) from exc
            backoff = min(2 ** (attempt - 1), 10)
            log.warning(
                "download interrupted (%s); retry %d/%d in %ds",
                exc, attempt, max_retries, backoff,
            )
            time.sleep(backoff)
            continue
    part.rename(dest)
    log.info("model downloaded: %s", dest)
    ensure_verified(dest)
    log.info("model sha256 verified")
    if progress:
        sz = dest.stat().st_size
        progress(sz, sz)
    return dest
