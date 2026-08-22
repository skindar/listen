# Listen — stability checklist

The app crashed (Abort trap 6) via the classic PyObjC path: a Python exception
escaped an ObjC entry point → became an uncaught ObjC exception → macOS
"unexpectedly quit" alert (`NSRunAlertPanel`) → `abort`. The fix pattern: no
Python exception may escape an ObjC-invoked method (action, delegate, callback)
or a non-main thread. Wrap, log, swallow.

## Rules (must always hold)

1. **Every ObjC-exposed method** (selectors ending in `_`, delegate methods like
   `menuWillOpen_`/`windowWillClose_`, the CGEventTap callback, the PortAudio
   callback) wraps its body in `try/except Exception: log.exception(...); return`.
   A Python exception crossing into ObjC aborts the app.
2. **PortAudio callback** runs on the audio thread — not under the run loop. It
   must never raise. Wrap it; swallow errors (logging once, not per-frame).
3. **`recorder.stop()` is defensive and idempotent**: a double-stop or a stream
   in a bad state must not raise; the mic is always released.
4. **Worker threads** never let exceptions escape: each has its own
   `try/except`, and a global `threading.excepthook` logs any that slip through
   instead of dying silently.
5. **The run loop** keeps its `try/except Exception` around the whole body so a
   bad event/sendEvent doesn't escape to the py2app stub's abort handler.
6. **`RealtimeClient.feed`** (called from the PortAudio thread) is non-blocking
   and never raises: guarded against closed state / None queue.
7. **State stays consistent on failure**: if a recording can't be stopped the
   normal way, `_recording` is cleared and the mic closed in a `finally`-style
   guard; the app returns to a usable state, never "stuck recording".
8. **PortAudio `abort`/`close` never run on the calling thread**
   (`Recorder.stop`): `AudioOutputUnitStop` can deadlock CoreAudio forever
   (the IO callback and the stop contend the unit lock) — on the main thread
   that froze the app, hotkey included. Close on a worker with a timeout;
   if it hangs, set `close_hung` and the app relaunches itself (the deadlock
   is not recoverable in-process — the audio unit keeps the mic).
9. **A dead realtime session must not end the dictation**: `realtimeDied_`
   reconnects (up to 2 attempts, worker thread — `connect` blocks) and keeps
   the mic running; only repeated failures abort the recording. The recorder
   feeds `app._on_audio_frame` (an indirection), so the swapped-in session
   starts receiving frames without touching the stream.

## Hardened blocks (this pass)

- `listen/audio.py` — `_callback` wrapped; `stop()` guards None/double-stop,
  closes off-thread with a timeout (`close_hung` for the unrecoverable case).
- `listen/app.py` — `recorder.stop()` wrapped in `_stop_recording` +
  `_abort_recording`; `realtimeDied_` reconnects instead of stopping the mic;
  `toggleRecording_`/`pasteText_`/`selectLanguage_`/sheet-action/live-paste
  selectors wrapped; `_stop_recording` idempotent; `_maybe_recover_mic`
  relaunches the app if a close deadlocked; `_warmup_probe` absorbs the
  cold-server first-session death.
- `listen/hotkey_sheet.py`, `listen/corrections_window.py` — window actions +
  `windowWillClose_` wrapped.
- `listen/realtime.py` — `feed` guarded against closed/None.
- `listen/server.py` — server stderr captured to
  `~/Library/Logs/listen-server.log` for post-mortems.
- `listen/__main__.py` — global `sys.excepthook` + `threading.excepthook` log
  uncaught exceptions (main + worker threads) instead of aborting silently.

## How to verify

- `python -m pytest -q` — all green (no regressions).
- `python setup_app.py py2app` — build; smoke-launch stays alive.
- Manual stress: start/stop recording rapidly several times; toggle packs while
  recording; quit mid-recording; unplug mic mid-recording. No abort; the app
  returns to Ready and the mic indicator always clears.
- Watch `~/Library/Logs/listen.log` for `error in ...` entries — they should be
  logged and recovered, never fatal.
- Check `~/Library/Logs/DiagnosticReports/` for new `run-*.ips` — there should
  be none after this pass.