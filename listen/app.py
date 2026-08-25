"""Desktop app: a single menu-bar icon. Press the hotkey, talk, text lands at
the cursor. The menu (hotkey, language, Start at Login, Quit) is the entire
UI — no windows beyond the one-time model downloader.

AppState (state.py) is the single source of truth; icons.py renders it and
menu.py builds the menu from it. Missing permissions never crash the app:
it idles in NEEDS_AX / MIC_DENIED and picks a grant up without a restart.
"""
from __future__ import annotations

import atexit
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import AppKit
import objc

from . import audio, autostart, config, corrections, hotkey, languages, paste, permissions
from . import server
from . import state as st
from .corrections_window import CorrectionsWindow
from .hotkey_sheet import HotkeySheet
from .icons import Icons
from .menu import rebuild as rebuild_menu
from .realtime import RealtimeClient
from .settings import Settings
from .paste import LivePaster

log = logging.getLogger("listen")


def install_edit_menu() -> None:
    """Give the app a main menu with the standard Edit items.

    Menu-bar apps get Cmd-C/V/X/A/Z from their Edit menu; this accessory app
    shows no bar, and with no main menu at all those key equivalents are never
    dispatched — so nothing could be pasted into the Auto-Replace fields.
    The bar stays hidden under the accessory policy; the shortcuts still fire.
    Idempotent — an existing main menu is left alone.
    """
    if AppKit.NSApp.mainMenu() is not None:
        return
    main = AppKit.NSMenu.alloc().init()
    edit = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in (
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ):
        edit.addItem_(
            AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, action, key
            )
        )
    root = AppKit.NSMenuItem.alloc().init()
    root.setSubmenu_(edit)
    main.addItem_(root)
    AppKit.NSApp.setMainMenu_(main)


@dataclass
class LivePaste:
    """Live-paste bookkeeping for one streaming recording, all main-thread.

    These four fields share one lifecycle — created when a streaming session
    starts, reset on the next one — so they're grouped here instead of spread
    across the App. They deliberately outlive the realtime-session clear in
    _stop_recording (self._realtime = None): the final flush drains the buffer
    and LivePaster.end() restores the clipboard AFTER the session is gone,
    so they cannot live in a "session" object cleared at stop.

    `streamed` is the delta text since the last .completed, used to paste only
    the trailing suffix the finalize added (e.g. the final period)."""
    paster: LivePaster
    buffer: str = ""
    flush_pending: bool = False
    streamed: str = ""


class App(AppKit.NSObject):
    def init(self):
        self = objc.super(App, self).init()
        if self is None:
            return None
        self.settings = Settings()
        self.corrections = corrections.Corrections()
        self.server = server.Server()
        self.recorder = audio.Recorder()
        self.hotkey_logic = hotkey.HotkeyLogic()
        self.hotkey_logic.spec = dict(self.settings.hotkey)
        self.hotkey = hotkey.Hotkey(
            self.hotkey_logic,
            on_toggle=self._on_toggle,
            on_capture_preview=self._on_capture_preview,
            on_capture_cancel=self._on_capture_cancelled,
        )
        self.icons = Icons()
        self._recording = False
        self._rec_start: float = 0.0
        self._streaming = False
        self._realtime: RealtimeClient | None = None
        self._live: LivePaste | None = None  # set only in streaming mode
        self._ax_ok = False
        self._reconnects = 0           # realtime reconnects in this recording
        self._reconnect_rt = None      # candidate client from a worker thread
        self._starting = False          # a start worker is in flight (TCC prompt)
        self._cancel_requested = False  # stop pressed during the start worker
        self._last_ax_hint = 0.0        # throttle re-opening Accessibility settings
        self._base = st.LOADING
        self._error: str | None = None
        self._note: str | None = None  # transient tooltip note
        self._status_item = None
        self._menu = None
        self._last_ax_poll = 0.0
        self._hotkey_sheet: HotkeySheet | None = None
        self._corrections_window: CorrectionsWindow | None = None
        return self

    # -- lifecycle ---------------------------------------------------------

    @objc.python_method
    def run(self) -> None:
        self._setup_menu_bar()
        nsapp = AppKit.NSApplication.sharedApplication()
        # Menu-bar-only: no Dock icon, no Cmd+Tab presence.
        nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        # State changes arrive via the callback (event-driven, not polled).
        self.server.set_state_callback(self._on_server_state)
        self.server.start()
        atexit.register(self.server.stop)
        self._ax_ok = permissions.accessibility_trusted()
        if self._ax_ok:
            self._ax_ok = self._start_hotkey()
        self._apply()
        while True:  # manual loop so Python signal handlers can run
            try:
                event = nsapp.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    AppKit.NSEventMaskAny,
                    AppKit.NSDate.dateWithTimeIntervalSinceNow_(1.0),
                    AppKit.NSDefaultRunLoopMode,
                    True,
                )
                if event is not None:
                    nsapp.sendEvent_(event)
                    nsapp.updateWindows()
                self._poll_accessibility()  # 1 Hz-throttled AX grant/revoke pickup
                if self._ax_ok:
                    self.hotkey.ensure_enabled()
            except Exception:
                # An escaped exception here would leave the app via the py2app
                # stub's "Launch error" dialog — log and keep the loop alive.
                log.exception("error in run loop")

    # -- Accessibility (needed for hotkey + paste, in every case) ----------

    @objc.python_method
    def _start_hotkey(self) -> bool:
        try:
            self.hotkey.start()
            return True
        except Exception:
            log.exception("event tap unavailable (Accessibility not granted?)")
            return False

    @objc.python_method
    def _poll_accessibility(self) -> None:
        """Pick up an Accessibility grant OR revocation without a restart (1 Hz).

        Polling continues after a grant so a revocation is noticed too —
        otherwise the icon would stay "ready" while the system silently
        disables the event tap and the hotkey stops firing."""
        now = time.time()
        if now - self._last_ax_poll < 1.0:
            return
        self._last_ax_poll = now
        trusted = permissions.accessibility_trusted()
        if trusted and not self._ax_ok:
            if self._start_hotkey():
                log.info("Accessibility granted — hotkey active")
                self._ax_ok = True
                self._apply()
        elif not trusted and self._ax_ok:
            log.warning("Accessibility revoked — hotkey inactive")
            self._ax_ok = False
            self._apply()

    # -- state --------------------------------------------------------------

    @objc.python_method
    def _effective(self):
        return st.NEEDS_AX if not self._ax_ok else self._base

    @objc.python_method
    def _set_base(self, s) -> None:
        if s != self._base:
            self._base = s
            self._apply()

    def setBase_(self, s) -> None:  # main-thread hop from worker threads
        self._set_base(st.AppState(str(s)))

    @objc.python_method
    def _set_base_async(self, s) -> None:
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setBase:", s.value, False
        )

    @objc.python_method
    def _on_server_state(self) -> None:
        """Server state changed (called on the server's background thread).
        Re-read and apply it on the main thread — never touch UI off-thread."""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyServerState:", None, False
        )

    def applyServerState_(self, _sender) -> None:
        # Main-thread hop from the server callback. Recording/transcribing/
        # denied/error drive their own state — only LOADING/READY listen here.
        try:
            if self._base not in (st.LOADING, st.READY):
                return
            server_state = self.server.state
            if server_state == server.READY:
                self._set_base(st.READY)
            elif server_state == server.FAILED:
                self._error = self.server.error
                self._set_base(st.ERROR)
        except Exception:
            log.exception("error applying server state")

    @objc.python_method
    def _apply(self) -> None:
        eff = self._effective()
        self.icons.apply(eff)
        self.icons.set_tooltip(self._note or self._tooltip(eff))

    @objc.python_method
    def _tooltip(self, eff) -> str:
        key = hotkey.format_hotkey(self.settings.hotkey)
        if eff == st.NEEDS_AX:
            return "Listen needs Accessibility for the hotkey — click for details"
        if eff == st.LOADING:
            return "Loading speech model…"
        if eff == st.RECORDING:
            return f"Recording — text appears as you speak; press {key} to finish"
        if eff == st.TRANSCRIBING:
            return "Transcribing…"
        if eff == st.MIC_DENIED:
            return "Microphone access denied — click for details"
        if eff == st.ERROR:
            return f"Error: {(self._error or 'unknown')[:80]}"
        return f"Ready — press {key} to dictate"

    # -- record → transcribe → paste ----------------------------------------

    @objc.python_method
    def _on_toggle(self) -> None:
        # Runs inside the CGEventTap callback: defer the real work to a plain
        # run-loop turn. Opening the input stream can block on the microphone
        # TCC prompt for seconds — that must never happen inside the tap.
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "toggleRecording:", None, False
        )

    def toggleRecording_(self, _sender) -> None:
        try:
            if not self._ax_ok:
                self._ax_hint()  # not granted yet — tell the user, don't stay silent
                return
            if self.hotkey_logic.capture:
                return
            if self._recording:
                # ALWAYS allow stop — even if the server died mid-recording, the
                # mic must be released. (The ready-check below is start-only.)
                self._stop_recording()
                return
            if self._starting:
                # A start worker is mid-flight (likely the mic TCC prompt). Let
                # the user cancel it: the worker tears down if it hasn't started.
                self._cancel_requested = True
                return
            if self.server.state != server.READY:
                return  # not ready yet — ignore politely
            self._cancel_requested = False
            self._starting = True
            self._recording = True  # instant: red dot the moment the hotkey fires
            self._set_base(st.RECORDING)
            threading.Thread(target=self._start_recording_async, daemon=True).start()
        except Exception:
            log.exception("error in toggleRecording (recovered)")

    @objc.python_method
    def _ax_hint(self) -> None:
        """Hotkey pressed before Accessibility is granted — don't sit silent
        (a silent wait was mistaken for a stalled download). Open the right
        settings pane + a tooltip note; throttle re-opening the pane."""
        self._set_note("Grant Accessibility to use the hotkey")
        now = time.time()
        if now - self._last_ax_hint >= 5.0:
            self._last_ax_hint = now
            permissions.open_accessibility_settings()

    @objc.python_method
    def _start_recording_async(self) -> None:
        # Worker thread: open the mic FIRST so the macOS mic-permission dialog
        # appears the instant the hotkey is pressed (not after the realtime
        # session opens, which was the ~1 s delay). Then open the realtime
        # session. The audio callback drops frames until _realtime is set
        # (silence, usually — the user is still reading the dialog).
        try:
            self.recorder.start(on_frame=self._on_audio_frame)
        except Exception:
            log.exception("microphone unavailable")
            self.recorder.stop()  # idempotent — release any half-open stream
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "micDenied:", None, False
            )
            return
        if self._cancel_requested:
            # The user pressed stop during the TCC prompt — tear it down without
            # ever arming a recording.
            self.recorder.stop()
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "startCancelled:", None, False
            )
            return
        rt: RealtimeClient | None = None
        streaming = False
        try:
            rt = RealtimeClient(
                config.HOST, self.server.port,
                language=self.settings.language,
                on_delta=self._on_realtime_delta,
                on_final=self._on_realtime_final,
                on_dead=self._on_realtime_dead,
                endpointing_ms=config.ENDPOINTING_MS,
            )
            rt.connect(timeout=3)
            # on_dead can fire during connect; treat a session that's already
            # gone as a connect failure (fall back to batch) instead of arming
            # a recording into a dead client.
            if not rt.is_alive:
                rt.close()
                rt = None
            else:
                streaming = True
        except Exception:
            log.warning("realtime session unavailable — batch fallback", exc_info=True)
            if rt is not None:
                rt.close()
            rt = None
            streaming = False
        if not streaming:
            # The realtime WS session won't open — the server is cold-starting
            # (it reports HTTP /ready but the realtime WS needs a moment to warm
            # up). Stop and tell the user to press again; the server warms
            # during this attempt and the second one works.
            self.recorder.stop()
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "startFailed:", None, False
            )
            return
        # Order matters: set the session fields before _recording flips True so a
        # reader that sees _recording also sees the rest (GIL barrier).
        self._realtime = rt
        self._streaming = streaming
        self._rec_start = time.time()
        self._reconnects = 0
        self._recording = True
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "recordingStarted:", None, False
        )

    def recordingStarted_(self, _sender) -> None:
        # Main-thread hop from the start worker: clipboard + icon/menu only.
        try:
            if not self._recording:
                return  # stop-during-start already tore it down
            self._starting = False
            if self._streaming:
                self._live = LivePaste(paster=LivePaster())
                self._live.paster.begin()
            self._set_base(st.RECORDING)
        except Exception:
            log.exception("error in recordingStarted (recovered)")

    def micDenied_(self, _sender) -> None:
        try:
            self._starting = False
            self._error = "Microphone access denied"
            self._set_base(st.MIC_DENIED)
        except Exception:
            log.exception("error in micDenied (recovered)")

    def startCancelled_(self, _sender) -> None:
        try:
            self._starting = False
            self._set_base(st.READY)
        except Exception:
            log.exception("error in startCancelled (recovered)")

    def startFailed_(self, _sender) -> None:
        """The realtime WS session won't open — the server is cold-starting.
        Stop and tell the user to press again; the server warms during this
        attempt and the second one works."""
        try:
            if not self._recording:
                return  # stop already tore it down
            self._starting = False
            self._recording = False
            self._set_note("Server warming up — press the hotkey again")
            self._set_base(st.READY)
        except Exception:
            log.exception("error in startFailed (recovered)")

    @objc.python_method
    def _on_audio_frame(self, pcm: bytes) -> None:
        """Audio thread: forward a captured chunk to the CURRENT session."""
        rt = self._realtime
        if rt is not None:
            rt.feed(pcm)

    @objc.python_method
    def _stop_recording(self) -> None:
        # Idempotent + never raises: a double-stop or any error must still
        # release the mic and return the app to a usable state.
        if not self._recording:
            return
        self._recording = False
        rt = self._realtime
        streaming = self._streaming
        self._realtime = None
        self._streaming = False
        self._cancel_pause_flush()  # don't let a late pause flush fire after teardown
        try:
            # Closing the mic is the one thing that must always happen first,
            # so the system mic indicator clears even if transcription fails.
            wav, duration = self.recorder.stop()  # batch→(wav,dur); stream→(b"",0)
            self._maybe_recover_mic()  # exits the app if the close deadlocked
            if streaming and rt is not None:
                seconds = rt.seconds
                # Flush any delta text buffered so far right now; the commit
                # emits the tail deltas (pasted via the debounced flush), and
                # we restore the clipboard after that has time to land.
                self._flush_live(final=False)
                if self._live is not None:
                    self._live.paster.end(1.5)
                if seconds < config.MIN_RECORD_SECONDS:
                    rt.close()
                    self._set_base(st.READY)  # too short — ignore
                    return
                self._set_base(st.TRANSCRIBING)
                threading.Thread(
                    target=self._stream_finalize, args=(rt,), daemon=True
                ).start()
            else:
                if duration < config.MIN_RECORD_SECONDS:
                    self._set_base(st.READY)
                    return
                self._set_base(st.TRANSCRIBING)
                threading.Thread(
                    target=self._transcribe_and_paste, args=(wav,), daemon=True
                ).start()
        except Exception:
            log.exception("error stopping recording — recovering to READY")
            if rt is not None:
                try:
                    rt.close()
                except Exception:
                    pass
            self._set_base(st.READY)

    @objc.python_method
    def _stream_finalize(self, rt: RealtimeClient) -> None:
        # With live paste, finalized utterances were already typed into the
        # cursor as they arrived. finalize() just commits the in-progress
        # utterance (its tail .completed is pasted via _on_realtime_final) and
        # waits for the server's ack — so this is near-instant.
        t0 = time.time()
        try:
            rt.finalize(timeout=10)
            rt.close()
            log.info("stream session finalized in %.2fs", time.time() - t0)
            self._error = None
            self._set_base_async(st.READY)
        except Exception:
            log.exception("stream finalize failed")
            rt.close()
            self._error = "transcription failed"
            self._set_base_async(st.ERROR)

    # -- live paste (streaming mode) ---------------------------------------

    @objc.python_method
    def _on_realtime_delta(self, fragment: str) -> None:
        """An incremental text fragment arrived (receiver thread). Hop to the
        main thread to append it to the live buffer."""
        if not fragment:
            return
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "liveDelta:", fragment, False
        )

    @objc.python_method
    def _on_realtime_final(self, text: str) -> None:
        """A `.completed` arrived (receiver thread). The body is already in the
        field from the deltas; paste any trailing suffix the finalize added
        (e.g. the final period) and flush."""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "liveFinalize:", text, False
        )

    @objc.python_method
    def _on_realtime_dead(self) -> None:
        """The realtime session died unexpectedly (worker thread). Recover on
        the main thread so the mic is released and the user can retry instead
        of being stuck in a recording that can no longer transcribe."""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "realtimeDied:", None, False
        )

    def realtimeDied_(self, _sender) -> None:
        try:
            if not self._recording or not self._streaming:
                return
            rt = self._realtime
            self._realtime = None  # frames drop until a reconnect lands
            if rt is not None:
                rt.close()
            self._reconnects += 1
            if self._reconnects <= 2:
                # The mic keeps running — a server blip must not end the
                # user's dictation. A second or two of speech may be lost.
                log.warning("realtime session died mid-recording — reconnecting "
                            "(attempt %d)", self._reconnects)
                threading.Thread(target=self._try_reconnect, daemon=True).start()
            else:
                log.error("realtime died again after reconnects — ending recording")
                self._abort_recording(
                    "Transcription stream was lost — press the hotkey to try again"
                )
        except Exception:
            log.exception("realtimeDied failed (recovered)")
            self._abort_recording("Transcription stream was lost")

    @objc.python_method
    def _try_reconnect(self) -> None:
        """Worker thread: open a fresh session (connect can block for seconds
        — it must never run on the main thread)."""
        try:
            rt = RealtimeClient(
                config.HOST, self.server.port,
                language=self.settings.language,
                on_delta=self._on_realtime_delta,
                on_final=self._on_realtime_final,
                on_dead=self._on_realtime_dead,
                endpointing_ms=config.ENDPOINTING_MS,
            )
            rt.connect(timeout=5)
        except Exception:
            log.exception("realtime reconnect failed")
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "realtimeReconnectFailed:", None, False
            )
            return
        # performSelector needs an ObjC object — pass the client via attribute.
        self._reconnect_rt = rt
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "realtimeReconnected:", None, False
        )

    def realtimeReconnected_(self, _sender) -> None:
        try:
            rt = self._reconnect_rt
            self._reconnect_rt = None
            if rt is None:
                return
            if not (self._recording and self._streaming):
                rt.close()  # recording ended meanwhile — don't leak the session
                return
            self._realtime = rt
            log.info("realtime reconnected mid-recording")
            self._set_note("Stream hiccup — reconnected, keep talking")
        except Exception:
            log.exception("realtimeReconnected failed (recovered)")
            self._abort_recording("Transcription stream was lost")

    def realtimeReconnectFailed_(self, _sender) -> None:
        try:
            self._abort_recording(
                "Transcription stream was lost — press the hotkey to try again"
            )
        except Exception:
            log.exception("realtimeReconnectFailed failed (recovered)")

    @objc.python_method
    def _abort_recording(self, message: str) -> None:
        """Give up on the current recording: release the mic (never raises),
        flush anything buffered for the live paste, and surface the error."""
        self._recording = False
        rt = self._realtime
        self._realtime = None
        self._streaming = False
        self._cancel_pause_flush()
        try:
            self.recorder.stop()
            self._maybe_recover_mic()
        except Exception:
            log.exception("mic close on recovery failed")
        if rt is not None:
            try:
                rt.close()
            except Exception:
                pass
        self._flush_live(final=True)  # keep any buffered words before teardown
        if self._live is not None:
            self._live.paster.end(1.0)
        self._error = message
        self._set_base(st.ERROR)

    @objc.python_method
    def _maybe_recover_mic(self) -> None:
        """A PortAudio close that deadlocked CoreAudio cannot be undone
        in-process (the audio unit is stuck holding the mic). Relaunch the
        app: the orphaned server is reaped on the next start, so the user
        only sees a brief restart instead of a zombie with the mic on."""
        if not getattr(self.recorder, "close_hung", False):
            return
        log.error("mic close hung (CoreAudio deadlock) — relaunching the app")
        app_path = None
        try:
            exe = Path(sys.executable).resolve()
            if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
                app_path = exe.parents[2]  # .../Listen.app
        except Exception:
            pass
        if app_path is None:
            log.error("dev run — no .app bundle to relaunch; exiting")
            os._exit(1)
        try:
            subprocess.Popen(
                ["/bin/sh", "-c",
                 f"sleep 1.5; open {shlex.quote(str(app_path))}"],
                start_new_session=True,
            )
        except Exception:
            log.exception("could not schedule relaunch")
        os._exit(0)

    def liveDelta_(self, fragment) -> None:
        """Accumulate a delta fragment; schedule a debounced flush (main thread).

        Also arm a pause flush: if no delta arrives for the endpointing
        window, the user has paused — paste the words held back so far
        (the server only finalizes on commit, not on a mid-dictation pause,
        so without this the last words only appear when the user stops)."""
        try:
            live = self._live
            if live is None:
                return
            frag = str(fragment)
            live.buffer += frag
            live.streamed += frag
            if not live.flush_pending:
                live.flush_pending = True
                # ~4 pastes/sec — fast enough to look live, slow enough that the
                # target app consumes each clipboard write before the next.
                self.performSelector_withObject_afterDelay_("flushLive:", None, 0.25)
            # A pause (no delta for the endpointing window) → paste the held
            # words. Reset the timer on each delta so it fires after the LAST.
            self._cancel_pause_flush()
            self.performSelector_withObject_afterDelay_(
                "pauseFlush:", None, config.ENDPOINTING_MS / 1000.0
            )
        except Exception:
            log.exception("liveDelta failed (recovered)")

    def pauseFlush_(self, _sender) -> None:
        """Fired ENDPOINTING_MS after the last delta: the user paused — paste
        the words held back so far (without stopping the mic)."""
        try:
            self._flush_live(final=True)
        except Exception:
            log.exception("pauseFlush failed (recovered)")

    @objc.python_method
    def _cancel_pause_flush(self) -> None:
        AppKit.NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "pauseFlush:", None
        )

    def liveFinalize_(self, text) -> None:
        """A `.completed` arrived: paste any trailing suffix the finalize added
        beyond what the deltas already streamed (e.g. the final period), then
        flush. Resets the per-utterance streamed tracker."""
        try:
            live = self._live
            if live is None:
                return
            final = str(text)
            streamed = live.streamed
            live.streamed = ""
            if streamed and final.startswith(streamed):
                suffix = final[len(streamed):]
                if suffix:
                    live.buffer += suffix
            self._flush_live(final=True)
        except Exception:
            log.exception("liveFinalize failed (recovered)")

    def flushLive_(self, _sender) -> None:
        """Debounced flush (run-loop timer): paste the buffered deltas."""
        self._flush_live(final=False)

    @objc.python_method
    def _flush_live(self, final: bool) -> None:
        """Paste buffered delta text, auto-replace applied.

        Between deltas only complete words go out — a torn trailing word is
        held back until more text arrives — so auto-replace always sees whole
        words (and no half word is ever pasted). A final flush (utterance
        completed / session died) pastes the remainder too.
        """
        live = self._live
        if live is None:
            return
        live.flush_pending = False
        buf = live.buffer
        if not buf:
            return
        if final:
            out, live.buffer = buf, ""
        else:
            cut = buf.rfind(" ") + 1
            out, live.buffer = buf[:cut], buf[cut:]
            if not out:
                return  # nothing complete yet — keep accumulating
        try:
            live.paster.paste(self.corrections.apply(out))
        except Exception:
            log.exception("live paste failed")

    @objc.python_method
    def _transcribe_and_paste(self, wav: bytes) -> None:
        t0 = time.time()
        try:
            text = self.corrections.apply(
                self.server.transcribe(wav, language=self.settings.language)
            )
            log.info("transcribed in %.2fs: %r", time.time() - t0, text)
            if text.strip():
                self._paste_on_main(text)
            self._error = None
            self._set_base_async(st.READY)
        except Exception:
            log.exception("transcription failed")
            self._error = "transcription failed"
            self._set_base_async(st.ERROR)

    @objc.python_method
    def _paste_on_main(self, text: str) -> None:
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "pasteText:", text, False
        )

    def pasteText_(self, text) -> None:
        try:
            paste.paste(str(text))
        except Exception:
            log.exception("paste failed (recovered)")

    # -- hotkey capture -----------------------------------------------------

    @objc.python_method
    def _on_capture_preview(self, spec: dict) -> None:
        """A capture candidate arrived — show it in the sheet (if open)."""
        label = hotkey.format_hotkey(spec)
        if self._hotkey_sheet is not None:
            self._hotkey_sheet.show_candidate(label)

    @objc.python_method
    def _on_capture_cancelled(self) -> None:
        self._close_hotkey_sheet()
        self._set_note(None)

    @objc.python_method
    def _open_hotkey_sheet(self) -> None:
        """Build (or reuse) the sheet and start capturing. Main-thread only."""
        if self._hotkey_sheet is None:
            self._hotkey_sheet = HotkeySheet.alloc().init()
            self._hotkey_sheet.set_app(self)
        self._hotkey_sheet.reset()
        self.hotkey_logic.start_capture()
        self._hotkey_sheet.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _close_hotkey_sheet(self) -> None:
        if self._hotkey_sheet is not None:
            self._hotkey_sheet.orderOut_(None)
            self._hotkey_sheet = None

    # Called by the sheet's Assign button (and Return).
    def confirm_hotkey_capture(self) -> None:
        spec = self.hotkey_logic.take_pending()
        if spec is None:
            return  # nothing captured yet — ignore
        self.settings.set_hotkey(spec)
        self.hotkey_logic.spec = dict(spec)
        self._close_hotkey_sheet()
        label = hotkey.format_hotkey(spec)
        log.info("hotkey set to %s", label)
        self._set_note(f"Hotkey set to {label}")

    # Called by the sheet's Cancel button, Esc, and the close box.
    def cancel_hotkey_capture(self) -> None:
        self.hotkey_logic.cancel_capture()
        self._close_hotkey_sheet()
        self._set_note(None)

    @objc.python_method
    def _set_note(self, text: str | None) -> None:
        """A transient tooltip note; cleared after a few seconds."""
        self._note = text
        self._apply()
        if text:
            self.performSelector_withObject_afterDelay_("clearNote:", None, 4.0)

    def clearNote_(self, _sender) -> None:
        self._note = None
        self._apply()

    # -- menu bar ------------------------------------------------------------

    @objc.python_method
    def _setup_menu_bar(self) -> None:
        self._status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSSquareStatusItemLength
        )
        btn = self._status_item.button()
        btn.setImagePosition_(AppKit.NSImageOnly)
        self.icons.attach(btn)
        self._menu = AppKit.NSMenu.alloc().init()
        self._menu.setDelegate_(self)
        self._menu.setAutoenablesItems_(False)
        self._status_item.setMenu_(self._menu)
        install_edit_menu()

    def menuWillOpen_(self, notification) -> None:
        try:
            rebuild_menu(self._menu, self, self._snapshot())
        except Exception:
            log.exception("menu rebuild failed")

    @objc.python_method
    def _snapshot(self) -> dict:
        return {
            "ax_ok": self._ax_ok,
            "mic_denied": self._base == st.MIC_DENIED,
            "error_line": (
                f"⚠ {(self._error or 'error')[:60]}"
                if self._base == st.ERROR and self._error
                else None
            ),
            "hotkey": dict(self.settings.hotkey),
            "hotkey_name": hotkey.format_hotkey(self.settings.hotkey),
            "language": self.settings.language,
            "autostart_on": autostart.is_on(),
        }

    # -- menu actions -------------------------------------------------------

    def toggleLogin_(self, sender) -> None:
        try:
            if autostart.is_on():
                autostart.disable()
                sender.setState_(AppKit.NSControlStateValueOff)
            else:
                autostart.enable()
                sender.setState_(AppKit.NSControlStateValueOn)
                # The launchd-started copy may need its own Accessibility
                # grant — walk the user to the right pane while it is missing.
                if not permissions.accessibility_trusted():
                    permissions.open_accessibility_settings()
        except Exception:
            log.exception("toggle login item failed")

    def changeHotkey_(self, sender) -> None:
        try:
            if not self._ax_ok:
                return
            if self._base in (st.RECORDING, st.TRANSCRIBING):
                return  # don't interrupt an active dictation
            # Defer to the next run-loop turn so the menu has closed first;
            # opening a window synchronously from a menu item re-enters NSMenu.
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "openHotkeySheet:", None, False
            )
        except Exception:
            log.exception("changeHotkey failed (recovered)")

    def openHotkeySheet_(self, _sender) -> None:
        try:
            self._open_hotkey_sheet()
        except Exception:
            log.exception("openHotkeySheet failed (recovered)")

    def openCorrections_(self, _sender) -> None:
        try:
            # Defer like changeHotkey: opening a window synchronously from a
            # menu item re-enters NSMenu.
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "showCorrections:", None, False
            )
        except Exception:
            log.exception("openCorrections failed (recovered)")

    def showCorrections_(self, _sender) -> None:
        try:
            if self._corrections_window is None:
                self._corrections_window = CorrectionsWindow.alloc().init()
                self._corrections_window.set_corrections(self.corrections)
            self._corrections_window.reload()
            self._corrections_window.makeKeyAndOrderFront_(None)
            # The app is an accessory (menu-bar-only) process — it must become
            # active for the table to accept keyboard edits.
            AppKit.NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            log.exception("showCorrections failed (recovered)")

    def resetHotkey_(self, sender) -> None:
        try:
            spec = dict(hotkey.HotkeyLogic.DEFAULT_SPEC)
            self.settings.set_hotkey(spec)
            self.hotkey_logic.spec = spec
            self._set_note(f"Hotkey reset to {hotkey.format_hotkey(spec)}")
        except Exception:
            log.exception("resetHotkey failed (recovered)")

    def selectLanguage_(self, sender) -> None:
        try:
            code = sender.representedObject()
            code = None if str(code) == "auto" else str(code)
            self.settings.set_language(code)
            self._set_note(f"Language: {languages.label(code)}")
        except Exception:
            log.exception("selectLanguage failed (recovered)")

    def grantAccessibility_(self, sender) -> None:
        permissions.open_accessibility_settings()

    def grantMicrophone_(self, sender) -> None:
        permissions.open_microphone_settings()

    def openLog_(self, sender) -> None:
        subprocess.Popen(["open", "-t", str(config.LOG_PATH)])

    def aboutAction_(self, _sender) -> None:
        try:
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_(f"Listen {config.APP_VERSION}")
            alert.setInformativeText_(
                "Free, offline speech-to-text — no account, no payment, ever.\n\n"
                "If it's useful, support development:\n"
                + config.COFFEE_URL.replace("https://", "")
            )
            alert.addButtonWithTitle_("Buy me a coffee ☕")
            alert.addButtonWithTitle_("Close")
            if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
                subprocess.Popen(["open", config.COFFEE_URL])
        except Exception:
            log.exception("about failed (recovered)")
