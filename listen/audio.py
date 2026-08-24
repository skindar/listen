"""Microphone recording via sounddevice (16 kHz mono -> PCM16 bytes).

Two modes:
  * streaming — start(on_frame=cb): each captured chunk is handed to `cb` as
    little-endian PCM16 bytes for live streaming to the ASR server. Nothing is
    buffered, so an hour-long dictation costs ~no memory.
  * batch      — start(): frames accumulate in memory and stop() returns a WAV,
    the fallback path when the realtime session can't be opened.

start() raising is the normal "microphone denied" path — it is also the moment
macOS shows the TCC prompt.

Stability: the PortAudio callback runs on the audio thread — NOT under the app
run loop — so a Python exception escaping it becomes an uncaught ObjC exception
and aborts the app. The callback is wrapped to never raise. The stream is
closed on a worker thread with a timeout: AudioOutputUnitStop can deadlock
CoreAudio (the IO callback and the stop contend the unit lock) — closing on
the main thread froze the whole app, hotkey included.
"""
from __future__ import annotations

import io
import logging
import threading
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

from . import config

log = logging.getLogger("listen")


class Recorder:
    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._on_frame: Callable[[bytes], None] | None = None
        self._cb_logged = False  # log a callback error at most once
        self.close_hung = False  # last stop() timed out closing the stream

    def start(self, on_frame: Callable[[bytes], None] | None = None) -> None:
        """Open the input stream. Raises when the mic is denied/unavailable.

        With on_frame set, captured PCM16 bytes are streamed to it (streaming
        mode); otherwise frames are buffered for stop() (batch mode).
        """
        self._on_frame = on_frame
        self._cb_logged = False
        self.close_hung = False
        if on_frame is None:
            self._frames = []
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        # PortAudio audio thread. MUST NOT raise: an escaped exception is not
        # under the app run loop and aborts the process. Swallow + log once.
        try:
            if self._on_frame is not None:
                self._on_frame(indata.tobytes())  # PCM16 LE mono bytes
            else:
                self._frames.append(indata.copy())
        except Exception:
            if not self._cb_logged:
                self._cb_logged = True
                log.exception("error in audio callback (further errors suppressed)")

    def stop(self, timeout: float = 1.0) -> tuple[bytes, float]:
        """Close the stream. In batch mode return (wav_bytes, seconds); in
        streaming mode frames were not buffered, so returns (b"", 0.0).

        Defensive and idempotent: a None/double-stopped stream or a PortAudio
        error during close never raises. The actual close runs on a worker
        thread and this waits at most `timeout`: AudioOutputUnitStop can
        deadlock CoreAudio forever, and blocking the caller (historically the
        main thread) took the whole app down with it. If the timeout fires,
        `close_hung` is set — the caller decides on recovery; the stream is
        abandoned either way.
        """
        stream, self._stream = self._stream, None
        on_frame, self._on_frame = self._on_frame, None
        frames, self._frames = self._frames, []
        if stream is not None:
            done = threading.Event()

            def _close() -> None:
                try:
                    stream.abort()  # immediate — input has nothing to drain
                    stream.close()
                except Exception:
                    log.exception("error closing input stream (ignored)")
                finally:
                    done.set()

            threading.Thread(target=_close, daemon=True).start()
            if not done.wait(timeout):
                self.close_hung = True
                log.error(
                    "mic close did not finish in %.1fs (CoreAudio deadlock) — "
                    "stream abandoned", timeout,
                )
        if on_frame is not None:
            return b"", 0.0  # streaming — duration tracked by the client
        # Batch: concatenate the captured frames. These are all the same
        # int16 mono shape PortAudio handed us, so concatenate can't fail in
        # practice — let an unexpected error surface to the caller's recovery
        # instead of silently returning empty audio (a dropped transcript).
        audio = (
            np.concatenate(frames)
            if frames
            else np.zeros((0, config.CHANNELS), dtype="int16")
        )
        duration = len(audio) / config.SAMPLE_RATE
        return self._wav_bytes(audio), duration

    @staticmethod
    def _wav_bytes(audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(config.CHANNELS)
            w.setsampwidth(2)  # int16
            w.setframerate(config.SAMPLE_RATE)
            w.writeframes(audio.tobytes())
        return buf.getvalue()