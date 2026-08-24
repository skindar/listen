"""Insert text into the active field: clipboard + Cmd+V, then restore.

One class, two usage patterns:
  * one-shot   — paste(text): write, Cmd+V, restore the user's clipboard
    after 0.5 s (the batch fallback path).
  * streaming  — ClipboardPaster held across a dictation: begin() saves the
    clipboard once, paste() fires each finalized utterance as it arrives,
    end() restores the original clipboard once. Per-utterance restore would
    chain-clobber, so the restore is deferred to the end of the session.

The restore only happens if the pasteboard is unchanged since our last write —
if the user copied something during the window, their copy wins.
"""
from __future__ import annotations

import threading

import AppKit
import Quartz

_KVK_ANSI_V = 0x09


class ClipboardPaster:
    """Write text to the clipboard, fire Cmd+V, and restore the original.

    `restore_delay` is the default gap before the one-shot restore; end() can
    override it per call (the streaming path restores 1–1.5 s after the last
    utterance so the final Cmd+V lands before the clipboard is taken back).
    """

    def __init__(self, restore_delay: float = 0.5) -> None:
        self._restore_delay = restore_delay
        self._old: str | None = None
        self._ours: int | None = None  # changeCount of our last write
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

    def end(self, delay: float | None = None) -> None:
        """Restore the original clipboard `delay` seconds after the last paste
        (defaults to restore_delay)."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(
            delay if delay is not None else self._restore_delay, self._restore
        )
        self._timer.start()

    def _restore(self) -> None:
        pb = AppKit.NSPasteboard.generalPasteboard()
        if self._ours is not None and pb.changeCount() != self._ours:
            return  # user copied something during dictation — their copy wins
        pb.clearContents()
        if self._old:
            pb.setString_forType_(self._old, AppKit.NSPasteboardTypeString)


# The streaming dictation path holds one of these across the session.
LivePaster = ClipboardPaster


def paste(text: str) -> None:
    """One-shot: write, Cmd+V, restore the user's clipboard after 0.5 s."""
    p = ClipboardPaster(restore_delay=0.5)
    p.begin()
    p.paste(text)
    p.end()


def _send_cmd_v() -> None:
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(src, _KVK_ANSI_V, True)
    Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    up = Quartz.CGEventCreateKeyboardEvent(src, _KVK_ANSI_V, False)
    Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)