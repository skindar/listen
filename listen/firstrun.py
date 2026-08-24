"""One-time first-run model download window.

The only window Listen ever shows: appears once when the model is missing,
downloads it with a progress bar, then closes forever. No settings, no
accounts — just the one thing it needs to work offline.
"""
from __future__ import annotations

import logging
import threading

import AppKit
import objc

from . import config, model

log = logging.getLogger("listen")

WIDTH = 360.0
HEIGHT = 168.0

_HEADLINE = "Listen needs its speech model"
_SUBLINE = "A one-time 707 MB download. After this, Listen works fully offline —"
_SUBLINE2 = "no account, no payment, ever."


def _alert(title: str, message: str) -> None:
    """A simple one-button alert (the only non-download UI we ever show)."""
    alert = AppKit.NSAlert.alloc().init()
    alert.setAlertStyle_(AppKit.NSAlertStyleWarning)
    alert.addButtonWithTitle_("OK")
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.runModal()


class DownloadWindow(AppKit.NSObject):
    @objc.python_method
    def build(self) -> AppKit.NSWindow:
        self._cancel = threading.Event()
        self._ok = False
        self._error: str | None = None

        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0.0, 0.0), (WIDTH, HEIGHT)),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        win.setTitle_("Listen")
        win.center()
        win.setReleasedWhenClosed_(False)
        view = win.contentView()

        def label(text, frame, bold=False, size=12.0):
            lbl = AppKit.NSTextField.labelWithString_(text)
            lbl.setBezeled_(False)
            lbl.setDrawsBackground_(False)
            lbl.setEditable_(False)
            if bold:
                lbl.setFont_(AppKit.NSFont.boldSystemFontOfSize_(size))
            else:
                lbl.setFont_(AppKit.NSFont.systemFontOfSize_(size))
            lbl.setFrame_(frame)
            view.addSubview_(lbl)
            return lbl

        label(_HEADLINE, ((20.0, HEIGHT - 30.0), (WIDTH - 40.0, 20.0)), bold=True, size=13.0)
        label(_SUBLINE, ((20.0, HEIGHT - 52.0), (WIDTH - 40.0, 16.0)))
        label(_SUBLINE2, ((20.0, HEIGHT - 70.0), (WIDTH - 40.0, 16.0)))

        self._bar = AppKit.NSProgressIndicator.alloc().init()
        self._bar.setIndeterminate_(False)
        self._bar.setMinValue_(0.0)
        self._bar.setMaxValue_(100.0)
        self._bar.setDoubleValue_(0.0)
        self._bar.setFrame_(((20.0, HEIGHT - 104.0), (WIDTH - 40.0, 20.0)))
        view.addSubview_(self._bar)

        self._pct = label("0%", ((20.0, HEIGHT - 124.0), (WIDTH - 40.0, 14.0)))

        self._download_btn = AppKit.NSButton.buttonWithTitle_target_action_(
            "Download", self, "startDownload:"
        )
        self._download_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._download_btn.setKeyEquivalent_("\r")
        self._download_btn.setFrame_(((WIDTH - 200.0, 16.0), (90.0, 24.0)))
        view.addSubview_(self._download_btn)

        self._cancel_btn = AppKit.NSButton.buttonWithTitle_target_action_(
            "Cancel", self, "cancel:"
        )
        self._cancel_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._cancel_btn.setKeyEquivalent_("\x1b")
        self._cancel_btn.setFrame_(((WIDTH - 100.0, 16.0), (80.0, 24.0)))
        view.addSubview_(self._cancel_btn)

        self._win = win
        return win

    def startDownload_(self, sender) -> None:
        self._download_btn.setEnabled_(False)
        self._cancel.clear()
        threading.Thread(target=self._run, daemon=True).start()

    @objc.python_method
    def _run(self) -> None:
        try:
            model.download(progress=self._on_progress, cancel=self._cancel)
            self._ok = True
        except model.Cancelled:
            self._ok = False  # user-initiated — no alert
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            self._ok = False
        AppKit.NSApplication.sharedApplication().performSelectorOnMainThread_withObject_waitUntilDone_(
            "stopModal", None, False
        )

    def _on_progress(self, downloaded: int, total: int | None) -> None:
        if total:
            pct = downloaded * 100 // total
        else:
            pct = -1
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "updateProgress:", pct, False
        )

    def updateProgress_(self, pct: int) -> None:
        if pct < 0:
            self._bar.setIndeterminate_(True)
            self._bar.startAnimation_(None)
            self._pct.setStringValue_("Downloading…")
        else:
            self._bar.setIndeterminate_(False)
            self._bar.setDoubleValue_(float(pct))
            self._pct.setStringValue_(f"{pct}%")

    def cancel_(self, sender) -> None:
        self._cancel.set()  # signal the download thread to stop
        AppKit.NSApplication.sharedApplication().stopModalWithCode_(AppKit.NSCancelButton)

    @objc.python_method
    def run(self) -> bool:
        nsapp = AppKit.NSApplication.sharedApplication()
        nsapp.activateIgnoringOtherApps_(True)
        win = self.build()
        win.makeKeyAndOrderFront_(None)
        code = nsapp.runModalForWindow_(win)
        win.orderOut_(None)
        # NSCancelButton used for cancel; stopModal (download done) returns 0.
        if code == AppKit.NSCancelButton:
            return False
        if not self._ok and self._error:
            _alert("Download failed", self._error)
        return self._ok


def run_download() -> bool:
    """Show the one-time download window. True if the model is now present.

    An already-downloaded model is sha256-verified once (a marker file skips
    repeats); a corrupted file is deleted so the download window re-appears.
    """
    model_file = config.resolve_model_path()
    if model_file is not None:
        try:
            model.ensure_verified(model_file)
            return True
        except RuntimeError:
            log.warning("existing model failed verification; re-downloading")
    controller = DownloadWindow.alloc().init()
    return controller.run()