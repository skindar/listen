"""The "Change Hotkey" sheet — a small floating panel that shows the key the
user is capturing and offers Assign / Cancel.

The panel is a borderless-ish NSPanel (no miniaturize/zoom buttons) that stays
above other windows without stealing focus from the app under the cursor. It
asks the App (its delegate) for the current candidate on every state change.

Lifecycle (driven by App):
    open()            — build and show the panel, start capture
    on_preview(spec)  — a new candidate arrived; update the label, enable Assign
    close()           — tear the panel down (Assign or Cancel)

Stability: every ObjC-exposed method (actions, window delegate) wraps its body
in try/except — a Python exception escaping into ObjC shows the macOS
"unexpectedly quit" alert and aborts the app.
"""
from __future__ import annotations

import logging

import AppKit
import objc

from .safeaction import safe_action

log = logging.getLogger("listen")

# (PANEL_WIDTH / 2) - small offsets; tuned by eye for a compact dialog.
_PANEL_W = 360
_PANEL_H = 180


class HotkeySheet(AppKit.NSPanel):
    """A floating, non-activating panel for capturing a new hotkey."""

    def init(self):
        style = (
            AppKit.NSTitledWindowMask
            | AppKit.NSClosableWindowMask
            | AppKit.NSTexturedBackgroundWindowMask
        )
        self = objc.super(HotkeySheet, self).initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, _PANEL_W, _PANEL_H),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        if self is None:
            return None
        self.setLevel_(AppKit.NSFloatingWindowLevel)
        self.setHasShadow_(True)
        self.setHidesOnDeactivate_(False)
        self.setReleasedWhenClosed_(False)
        self.setTitle_("Change Hotkey")
        self.setDelegate_(self)  # close-box → windowWillClose → cancel
        self._build()
        self.center()
        return self

    @objc.python_method
    def _build(self) -> None:
        view = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _PANEL_W, _PANEL_H)
        )
        self.setContentView_(view)

        self.prompt = AppKit.NSTextField.labelWithString_(
            "Press a key, or hold a modifier alone."
        )
        self.prompt.setBezeled_(False)
        self.prompt.setDrawsBackground_(False)
        self.prompt.setEditable_(False)
        self.prompt.setSelectable_(False)
        self.prompt.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        self.prompt.setAlignment_(AppKit.NSCenterTextAlignment)
        self.prompt.setFrame_(AppKit.NSMakeRect(20, 120, _PANEL_W - 40, 20))
        view.addSubview_(self.prompt)

        self.captured = AppKit.NSTextField.labelWithString_("—")
        self.captured.setBezeled_(False)
        self.captured.setDrawsBackground_(False)
        self.captured.setEditable_(False)
        self.captured.setSelectable_(False)
        self.captured.setFont_(AppKit.NSFont.boldSystemFontOfSize_(20))
        self.captured.setAlignment_(AppKit.NSCenterTextAlignment)
        self.captured.setFrame_(AppKit.NSMakeRect(20, 70, _PANEL_W - 40, 32))
        view.addSubview_(self.captured)

        cancel = AppKit.NSButton.buttonWithTitle_target_action_(
            "Cancel", self, "cancelAction:"
        )
        cancel.setBezelStyle_(AppKit.NSBezelStyleRounded)
        cancel.setKeyEquivalent_("\x1b")  # Esc
        cancel.setFrame_(AppKit.NSMakeRect(_PANEL_W - 240, 16, 100, 28))
        view.addSubview_(cancel)

        self.assign = AppKit.NSButton.buttonWithTitle_target_action_(
            "Assign", self, "assignAction:"
        )
        self.assign.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.assign.setKeyEquivalent_("\r")  # Return
        self.assign.setEnabled_(False)
        self.assign.setFrame_(AppKit.NSMakeRect(_PANEL_W - 130, 16, 110, 28))
        view.addSubview_(self.assign)

    # -- wiring ------------------------------------------------------------

    @objc.python_method
    def set_app(self, app) -> None:
        """The App receives Assign/Cancel decisions."""
        self._app = app

    # -- state from HotkeyLogic preview ------------------------------------

    @objc.python_method
    def show_candidate(self, label: str) -> None:
        self.captured.setStringValue_(label)
        self.assign.setEnabled_(True)

    @objc.python_method
    def reset(self) -> None:
        self.captured.setStringValue_("—")
        self.assign.setEnabled_(False)

    # -- actions ------------------------------------------------------------

    @safe_action("hotkey sheet cancel")
    def cancelAction_(self, _sender) -> None:
        self._app.cancel_hotkey_capture()

    @safe_action("hotkey sheet assign")
    def assignAction_(self, _sender) -> None:
        self._app.confirm_hotkey_capture()

    # -- Esc anywhere in the panel also cancels ----------------------------

    @safe_action("hotkey sheet cancel")
    def cancelOperation_(self, _sender) -> None:
        self._app.cancel_hotkey_capture()

    @safe_action("hotkey sheet close")
    def windowWillClose_(self, _notification) -> None:
        # Close box clicked (and any other close path). Don't re-enter via
        # orderOut_: just tell the App to abandon the capture.
        self._app.cancel_hotkey_capture()