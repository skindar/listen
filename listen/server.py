"""Manage the nemo-speech serve subprocess and transcribe via HTTP.

The port is picked fresh at every start (free ephemeral loopback port), so
Listen never collides with other local services; LISTEN_PORT forces a fixed
port for debugging. A pidfile lets the next start reap a server orphaned by a
SIGKILLed app. The server is started in the background so the event loop never
blocks on model load; state transitions are observable so the UI can show ⏳
while the Metal model warms up and 🎙 once ready.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger("listen")

# Observable states.
NOT_STARTED = "not_started"
LOADING = "loading"
READY = "ready"
FAILED = "failed"


def _free_port() -> int:
    """A free ephemeral loopback port (OS-assigned)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((config.HOST, 0))
        return s.getsockname()[1]


class Server:
    """Wraps `nemo-speech serve` so the model is loaded once, not per request."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._state = NOT_STARTED
        self._lock = threading.Lock()
        self._error: str | None = None
        self._port: int | None = None
        self._log_file = None  # stderr of the server binary, for diagnosis

    # -- lifecycle ---------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def port(self) -> int | None:
        return self._port

    def start(self) -> None:
        """Start nemo-speech in a background thread; returns immediately."""
        with self._lock:
            if self._state in (LOADING, READY):
                return
            self._state = LOADING
            self._error = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            self._spawn_and_wait()
        except Exception as exc:  # noqa: BLE001
            log.exception("nemo-speech server failed to start")
            with self._lock:
                self._state = FAILED
                self._error = str(exc)

    def _spawn_and_wait(self) -> None:
        model = config.resolve_model_path()
        if model is None:
            raise RuntimeError(
                "ASR model not found in ~/.listen/models. Run `python -m listen pull` "
                "to download nvidia/nemotron-3.5-asr-streaming-0.6b (Q8_0, ~707 MB)."
            )
        binary = config.nemo_binary()
        if not binary.is_file():
            raise RuntimeError(f"nemo-speech binary not found at {binary}")

        # A fresh ephemeral port can, in a rare race, be taken between our
        # close() and the binary's bind() — retry a couple of times. A fixed
        # LISTEN_PORT is debug intent: fail loudly instead of substituting.
        attempts = 1 if config.FIXED_PORT is not None else 3
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._port = config.FIXED_PORT or _free_port()
            self._reap_orphan_server()
            self._spawn(model, binary)
            try:
                self._wait_ready(timeout=120.0)
            except RuntimeError as exc:  # exited early — likely the port race
                last_exc = exc
                log.warning(
                    "nemo-speech died early (attempt %d/%d): %s", attempt, attempts, exc
                )
                continue
            self._write_pidfile()
            return
        assert last_exc is not None
        raise last_exc

    def _spawn(self, model: Path, binary: Path) -> None:
        cmd = [
            str(binary), "serve",
            "--asr-model", str(model),
            "--host", config.HOST,
            "--port", str(self._port),
            "--no-ui",
            "--no-warmup",
        ]
        env = dict(os.environ)
        # Let the bundled binary find libggml/libnemo_speech dylibs.
        env["DYLD_LIBRARY_PATH"] = str(config.nemo_lib_dir())
        log.info("starting nemo-speech on port %s", self._port)
        # Capture stderr: when the server closes a realtime session (it did,
        # mid-recording, twice) its own log is the only place with the reason.
        try:
            self._close_log()
            self._log_file = open(config.SERVER_LOG_PATH, "wb")
        except Exception:
            log.exception("server log unavailable — stderr dropped")
            self._log_file = None
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=self._log_file if self._log_file is not None
            else subprocess.DEVNULL,
            env=env,
        )

    def _wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc is None:
                raise RuntimeError("server not started")
            if self._proc.poll() is not None:
                raise RuntimeError("nemo-speech server exited early")
            try:
                with urllib.request.urlopen(
                    self._url("/ready"), timeout=1
                ) as resp:
                    if json.load(resp).get("ready"):
                        with self._lock:
                            self._state = READY
                        log.info(
                            "nemo-speech ready on port %s", self._port
                        )
                        return
            except Exception:
                pass
            time.sleep(0.2)
        raise TimeoutError("nemo-speech server did not become ready")

    def _url(self, path: str) -> str:
        return f"http://{config.HOST}:{self._port}{path}"

    # -- orphan reaping / pidfile -------------------------------------------

    def _reap_orphan_server(self) -> None:
        """Kill nemo-speech servers left behind by dead app runs.

        Two sweeps: the process our pidfile names (exact, catches our own
        SIGKILLed runs), then any `nemo-speech serve` started with our exact
        `--no-ui --no-warmup` flags — the signature of a Listen-launched
        server from any copy/newer or older build. A manually started
        `nemo-speech serve` (with its UI) is never touched. Safe because the
        singleton lock guarantees no other Listen instance is alive.
        """
        pids = self._orphan_pids()
        for pid in pids:
            log.info("reaping orphaned nemo-speech server (pid %d)", pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            for _ in range(20):  # up to 2 s, then escalate
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        config.SERVER_PIDFILE.unlink(missing_ok=True)

    @staticmethod
    def _orphan_pids() -> list[int]:
        pids: list[int] = []
        # 1) the pidfile's process, if it is a nemo-speech server
        try:
            pid = int(config.SERVER_PIDFILE.read_text().strip())
        except (FileNotFoundError, ValueError):
            pass
        else:
            try:
                r = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True, text=True,
                )
                command = r.stdout.strip()
            except Exception:
                command = ""
            if "nemo-speech" in command and "serve" in command:
                pids.append(pid)
        # 2) any server carrying our exact launch signature
        try:
            r = subprocess.run(
                ["pgrep", "-f", r"nemo-speech serve .*--no-ui .*--no-warmup"],
                capture_output=True, text=True,
            )
            pids += [int(p) for p in r.stdout.split() if p.isdigit()]
        except Exception:
            pass
        return sorted(set(pids))

    def _write_pidfile(self) -> None:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            config.SERVER_PIDFILE.write_text(f"{self._proc.pid}\n")
        except Exception:
            log.exception("could not write server pidfile")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._close_log()
        config.SERVER_PIDFILE.unlink(missing_ok=True)

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def ensure_ready(self, timeout: float = 120.0) -> None:
        """Block (from a worker thread) until READY; raise if FAILED."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._state == READY:
                return
            if self._state == FAILED:
                raise RuntimeError(self._error or "server failed")
            time.sleep(0.1)
        raise TimeoutError("server did not become ready in time")

    # -- transcription -----------------------------------------------------

    def transcribe(self, wav: bytes, language: str | None = None) -> str:
        """POST WAV bytes (16 kHz mono) to the local server; return text."""
        self.ensure_ready()
        boundary = "----listen-boundary"
        body = self._multipart(wav, boundary, language)
        req = urllib.request.Request(
            self._url("/v1/audio/transcriptions"),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)["text"]

    @staticmethod
    def _multipart(wav: bytes, boundary: str, language: str | None) -> bytes:
        parts: list[bytes] = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            wav,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="response_format"\r\n\r\n',
            b"json\r\n",
        ]
        if language is not None:
            parts += [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="language"\r\n\r\n',
                f"{language}\r\n".encode(),
            ]
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)
