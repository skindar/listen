"""Streaming ASR over the nemo-speech /v1/realtime WebSocket.

Instead of recording the whole utterance and transcribing it in one batch at
the end (slow for long dictation), audio is streamed to the server as it is
captured. The server holds the RNNT streaming cache across chunks and emits
finalized utterances as it goes, so by the time the user presses stop almost
everything is already transcribed — finalize() just collects the tail.

Lifecycle:
    connect()       open WS, configure the session, start sender/receiver
    feed(pcm16)     enqueue a chunk (called from the PortAudio thread)
    finalize()      commit, wait for the final ack, return the joined text
    close()         tear down threads + socket

The WS transport is injected (defaults to a real ws.WS) so the decision logic
is unit-testable with a fake transport.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

from . import config
from .ws import WS, OP_CLOSE, OP_TEXT

log = logging.getLogger("listen")

_SAMPLE_RATE = config.SAMPLE_RATE  # 16000
_BYTES_PER_SEC = _SAMPLE_RATE * 2  # int16 mono


class RealtimeClient:
    def __init__(self, host: str, port: int, language: str | None = None,
                 transport: WS | None = None, on_delta=None, on_final=None,
                 on_dead=None, endpointing_ms: int | None = None) -> None:
        self._host = host
        self._port = port
        self._language = language
        self._endpointing_ms = endpointing_ms
        self._ws = transport or WS()
        self._on_delta = on_delta  # per incremental text fragment (receiver thread)
        self._on_final = on_final  # per finalized utterance (receiver thread)
        self._on_dead = on_dead    # session died unexpectedly (worker thread)
        self._send_q: queue.Queue = queue.Queue()
        self._finals: list[str] = []
        self._lock = threading.Lock()
        self._committed = threading.Event()
        self._closed = threading.Event()
        self._dead_announced = False
        self._error: str | None = None
        self._fed_bytes = 0
        self._sender: threading.Thread | None = None
        self._receiver: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        """Open the WS, configure the session, start the worker threads."""
        self._ws.connect(self._host, self._port, "/v1/realtime", timeout)
        # The handshake left the socket blocking (no timeout). Use a bounded
        # timeout only for the two startup events so a broken server fails
        # fast instead of blocking forever; then go back to blocking for the
        # long-lived receiver loop.
        self._ws.set_timeout(timeout)
        op, payload = self._ws.recv()
        if op != OP_TEXT or json.loads(payload).get("type") != "session.created":
            raise RuntimeError(f"expected session.created, got {payload[:80]!r}")
        session = {"sample_rate": _SAMPLE_RATE, "automatic_punctuation": True}
        if self._language:
            session["language"] = self._language
        if self._endpointing_ms is not None:
            # A shorter silence threshold so the server finalizes utterances
            # on natural pauses DURING recording (not only on commit) — each
            # finalized phrase is then pasted live by on_final.
            session["endpointing_ms"] = self._endpointing_ms
        self._ws.send_text(json.dumps({"type": "session.update", "session": session}))
        op, payload = self._ws.recv()  # session.updated
        if op != OP_TEXT or json.loads(payload).get("type") != "session.updated":
            raise RuntimeError(f"expected session.updated, got {payload[:80]!r}")
        self._ws.set_timeout(None)  # block indefinitely — a quiet server is fine
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._receiver = threading.Thread(target=self._recv_loop, daemon=True)
        self._sender.start()
        self._receiver.start()
        # A wedged server (TCP up, no frames) is otherwise indistinguishable
        # from a quiet one; probe it. Self-disables if the server doesn't
        # keepalive, so this can't false-positive on a long dictation pause.
        self._ws.start_keepalive(
            config.REALTIME_PING_INTERVAL, config.REALTIME_PING_DEADLINE
        )

    def feed(self, pcm16: bytes) -> None:
        """Enqueue a PCM16 chunk for streaming. Non-blocking (PortAudio cb).

        Never raises: called from the audio thread, where an escaped exception
        would abort the app. Closed session / None queue → silent no-op.
        """
        try:
            if self._closed.is_set() or self._send_q is None:
                return
            self._fed_bytes += len(pcm16)
            self._send_q.put(pcm16)
        except Exception:
            log.exception("realtime feed failed (ignored)")

    def finalize(self, timeout: float = 8.0) -> str:
        """Commit the buffer and return the full transcript. Most of it is
        already transcribed, so this normally returns within milliseconds of
        the server's final ack. If the session already died, returns at once."""
        if self._error is not None:
            return ""  # session is dead — nothing to finalize
        try:
            self._ws.send_text(json.dumps({"type": "input_audio_buffer.commit"}))
        except Exception:
            log.exception("realtime commit failed")
        if not self._committed.wait(timeout):
            log.warning("realtime finalize timed out waiting for committed")
        # A trailing .completed for the in-progress utterance may arrive just
        # after the commit ack; give the receiver a brief grace to absorb it.
        time.sleep(0.15)
        with self._lock:
            return " ".join(self._finals)

    def close(self) -> None:
        self._closed.set()
        self._send_q.put(None)  # release the sender
        try:
            self._ws.close()
        except Exception:
            pass

    def _announce_dead(self) -> None:
        """Fire on_dead once, only for an unexpected death (not a normal close)."""
        if self._closed.is_set() or self._dead_announced:
            return
        self._dead_announced = True
        self._emit(self._on_dead)

    def _emit(self, cb, *args) -> None:
        """Invoke a user callback (receiver/worker thread) without letting an
        exception escape — a callback raising here would kill the worker."""
        if cb is None:
            return
        try:
            cb(*args)
        except Exception:
            log.exception("realtime callback failed")

    # -- introspection -----------------------------------------------------

    @property
    def seconds(self) -> float:
        return self._fed_bytes / _BYTES_PER_SEC

    @property
    def error(self) -> str | None:
        return self._error

    # -- worker threads ----------------------------------------------------

    def _send_loop(self) -> None:
        while not self._closed.is_set():
            # Blocks until a chunk arrives or close() enqueues the None sentinel
            # — no poll timeout, so frames ship with no wake-up latency.
            chunk = self._send_q.get()
            if chunk is None:
                break
            try:
                self._ws.send_binary(chunk)
            except Exception:
                log.exception("realtime send failed")
                self._error = "stream send failed"
                break
        self._announce_dead()

    def _recv_loop(self) -> None:
        while not self._closed.is_set():
            try:
                op, payload = self._ws.recv()
            except TimeoutError:
                continue  # server is quiet (silence/pause) — keep waiting
            except Exception:
                if not self._closed.is_set():
                    log.exception("realtime recv failed")
                    self._error = self._error or "stream closed"
                break
            if op == OP_CLOSE:
                break
            if op != OP_TEXT:
                continue
            try:
                evt = json.loads(payload)
            except Exception:
                continue
            self._handle_event(evt)
        self._announce_dead()

    def _handle_event(self, evt: dict) -> None:
        t = evt.get("type", "")
        if t == "conversation.item.input_audio_transcription.delta":
            frag = evt.get("delta") or ""
            if frag:
                self._emit(self._on_delta, frag)
        elif t == "conversation.item.input_audio_transcription.completed":
            txt = evt.get("transcript") or ""
            if txt:
                with self._lock:
                    self._finals.append(txt)
                # The completed carries the full final text, but with live
                # delta pasting the text is already in the field — on_final is
                # used only as a "flush any buffered fragments" signal.
                self._emit(self._on_final, txt)
        elif t == "input_audio_buffer.committed":
            self._committed.set()
        elif t == "error":
            self._error = (evt.get("error") or {}).get("message") or "realtime error"
            log.warning("realtime error event: %s", self._error)
            # An error ends the session — release finalize() waiters so they
            # don't block for the full timeout on a session that won't commit.
            self._committed.set()