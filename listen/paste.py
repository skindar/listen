"""Insert text into the active field: clipboard + Cmd+V, then restore.

Two flavors:
  * paste(text)         — one-shot: write, Cmd+V, restore the user's clipboard
    after 0.5 s (used by the batch fallback path).
  * LivePaster          — for streaming dictation: save the clipboard once at
    begin(), paste each finalized utterance as it arrives, restore the original
    clipboard once at end(). Per-utterance restore would chain-clobber, so the
    restore is deferred to the end of the session.

The restore only happens if the pasteboard is unchanged since our last write —
if the user copied something during the window, their copy wins.
"""
from __future__ import annotations

import threading

import AppKit
import Quartz

_KVK_ANSI_V = 0x09


def paste(text: str) -> None:
    pb = AppKit.NSPasteboard.generalPasteboard()
    old = pb.stringForType_(AppKit.NSPasteboardTypeString)
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    ours = pb.changeCount()  # anything above this is someone else's write
    _send_cmd_v()
    # Paste is async; restore the user's clipboard shortly after.
    threading.Timer(0.5, _restore, args=(old, ours)).start()


def _restore(old: str | None, ours: int) -> None:
    pb = AppKit.NSPasteboard.generalPasteboard()
    if pb.changeCount() != ours:
        return  # user copied something else meanwhile — don't clobber it
    pb.clearContents()
    if old:
        pb.setString_forType_(old, AppKit.NSPasteboardTypeString)


class LivePaster:
    """Paste finalized utterances live during a streaming dictation.

    The clipboard is captured once at begin() and restored once at end(); in
    between, each utterance overwrites the clipboard and fires Cmd+V. Pasting
    is spaced by the caller (the App drains its queue ~0.1 s apart) so the
    target app consumes the clipboard before the next utterance overwrites it.
    """

    def __init__(self) -> None:
        self._old: str | None = None
        self._ours: int | None = None
        self._timer: threading.Timer | None = None

    def begin(self) -> None:
        # Cancel a pending restore from a previous session so it can't fire
        # and clobber this one's clipboard mid-dictation.
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        pb = AppKit.NSPasteboard.generalPasteboard()
        self._old = pb.stringForType_(AppKit.NSPasteboardTypeString)
        self._ours = None

    def paste(self, text: str) -> None:
        if not text:
            return
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
        self._ours = pb.changeCount()
        _send_cmd_v()

    def end(self, delay: float = 1.0) -> None:
        """Restore the original clipboard `delay` seconds after the last paste."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self._restore)
        self._timer.start()

    def _restore(self) -> None:
        pb = AppKit.NSPasteboard.generalPasteboard()
        if self._ours is not None and pb.changeCount() != self._ours:
            return  # user copied something during dictation — their copy wins
        pb.clearContents()
        if self._old:
            pb.setString_forType_(self._old, AppKit.NSPasteboardTypeString)


def _send_cmd_v() -> None:
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(src, _KVK_ANSI_V, True)
    Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    up = Quartz.CGEventCreateKeyboardEvent(src, _KVK_ANSI_V, False)
    Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
