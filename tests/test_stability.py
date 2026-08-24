"""Stability hardening: callbacks/stop/feed must never raise (an escaped
exception in the audio thread or an ObjC entry point aborts the app)."""
import numpy as np

from listen.audio import Recorder
from listen.realtime import RealtimeClient


def test_recorder_stop_idempotent_no_stream():
    """stop() with no stream and a double-stop never raises; duration 0."""
    r = Recorder()
    wav, dur = r.stop()
    assert dur == 0.0
    wav, dur = r.stop()  # second call is a no-op
    assert dur == 0.0


def test_recorder_stop_batch_from_buffer_no_stream():
    """stop() in batch mode concatenates buffered frames even with no live stream."""
    r = Recorder()
    r._frames = [np.zeros((100, 1), dtype="int16"), np.zeros((50, 1), dtype="int16")]
    wav, dur = r.stop()
    assert dur == 150 / 16000
    assert wav[:4] == b"RIFF"  # a real WAV


def test_audio_callback_swallows_on_frame_error():
    """An on_frame that raises must not escape the PortAudio callback."""
    r = Recorder()

    def bad(_b):
        raise RuntimeError("boom")

    r._on_frame = bad
    indata = np.zeros((1600, 1), dtype="int16")
    r._callback(indata, 1600, None, None)  # must not raise
    # a second error is suppressed (logged once), still no raise
    r._callback(indata, 1600, None, None)


def test_audio_callback_swallows_append_error():
    r = Recorder()
    r._frames = None  # sabotage: .append will raise

    def safe_iter():
        raise RuntimeError("boom")

    r._frames = None
    indata = np.zeros((1600, 1), dtype="int16")
    r._callback(indata, 1600, None, None)  # must not raise


def test_realtime_feed_after_close_no_raise():
    """feed() is called from the audio thread; after close it must be a no-op."""
    c = RealtimeClient("127.0.0.1", 9999)
    c.close()
    c.feed(b"\x00" * 3200)  # must not raise
    c.feed(b"\x00" * 3200)


def test_realtime_feed_before_connect_no_raise():
    c = RealtimeClient("127.0.0.1", 9999)
    c.feed(b"\x00" * 3200)  # queued, no connect needed; must not raise
    c.close()


def test_realtime_finalize_fast_when_dead():
    """finalize on a never-connected (dead) session returns at once, no hang."""
    c = RealtimeClient("127.0.0.1", 9999)
    c._error = "simulated"
    assert c.finalize(timeout=5) == ""
    c.close()


# -- mic close must never hang the caller (CoreAudio deadlock) -----------------


class _FakeStream:
    def __init__(self, hang: bool = False) -> None:
        self.hang = hang
        self.aborted = False
        self.closed = False

    def abort(self) -> None:
        self.aborted = True
        import threading
        if self.hang:  # simulate AudioOutputUnitStop deadlocking forever
            threading.Event().wait()

    def close(self) -> None:
        self.closed = True


def test_recorder_stop_returns_when_close_hangs():
    """A deadlocked PortAudio close must not block stop() — the caller is the
    main thread; hanging it froze the whole app (hotkey included)."""
    import time

    r = Recorder()
    r._stream = _FakeStream(hang=True)
    r._on_frame = lambda _b: None
    t0 = time.monotonic()
    wav, dur = r.stop(timeout=0.2)
    assert time.monotonic() - t0 < 1.0  # returned promptly, not blocked
    assert r.close_hung is True
    assert (wav, dur) == (b"", 0.0)  # streaming mode ignores buffers


def test_recorder_stop_closes_off_caller_thread():
    """The abort/close run on a worker thread; happy path reports no hang."""
    r = Recorder()
    fake = _FakeStream()
    r._stream = fake
    r._on_frame = lambda _b: None
    r.stop(timeout=2.0)
    assert fake.aborted and fake.closed
    assert r.close_hung is False


def test_recorder_stop_batch_snapshot_survives_late_frames():
    """The WAV is built from a snapshot: frames appended by a straggler
    callback (the close is async now) must not corrupt the result."""
    r = Recorder()
    r._stream = _FakeStream()
    r._frames = [np.zeros((100, 1), dtype="int16")]
    wav, dur = r.stop()
    assert dur == 100 / 16000
    assert wav[:4] == b"RIFF"
    # a late callback appends into the fresh list, not the snapshot
    r._callback(np.zeros((10, 1), dtype="int16"), 10, None, None)
    assert len(r._frames) == 1


def test_start_recording_structure():
    """The audio forwarder stays trivial (state setup never migrates into
    _on_audio_frame); the blocking I/O (rt.connect, recorder.start — the mic
    TCC prompt) runs on the start worker, not the main run loop (blocking main
    lets macOS disable the CGEventTap so the hotkey stops firing); and the
    UI/base state hops to the main-thread selector recordingStarted_."""
    import inspect

    from listen.app import App

    frame = inspect.getsource(App._on_audio_frame)
    assert len(frame.splitlines()) <= 8  # just the docstring + forward

    # ObjC selectors (python_selector) expose the raw function via .callable.
    def _src(method):
        return inspect.getsource(getattr(method, "callable", method))

    async_src = _src(App._start_recording_async)
    started_src = _src(App.recordingStarted_)
    toggle_src = _src(App.toggleRecording_)

    # Session/recording state and the blocking I/O live in the worker:
    assert "self._recording = True" in async_src
    assert "self._realtime = rt" in async_src
    assert "rt.connect" in async_src
    assert "recorder.start" in async_src

    # UI/base state lives on the main-thread hop, guarded against a stop that
    # already tore the recording down during the hop:
    assert "self._set_base(st.RECORDING)" in started_src
    assert "if not self._recording" in started_src
    assert "rt.connect" not in started_src and "recorder.start" not in started_src

    # The main toggle never does the blocking I/O — it spawns the worker:
    assert "rt.connect" not in toggle_src and "recorder.start" not in toggle_src
    assert "_start_recording_async" in toggle_src