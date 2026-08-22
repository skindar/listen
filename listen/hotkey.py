"""Global hotkey via CGEventTap (requires Accessibility).

The decision logic (HotkeyLogic) is pure Python with no Quartz imports, so it
is unit-testable; the Hotkey class only bridges CGEvents into it.

A hotkey is one of:
  * a bare modifier  — press and release it alone (e.g. Right Option).
  * a key combo       — a plain key plus optional modifiers (e.g. ⌃⌥Space).

The spec dict is {"keycode": int, "modifiers": [name…], "is_modifier": bool}.
Old specs without "modifiers" are treated as modifiers=[] (back-compat).

Capture mode is two-step: key presses produce ("preview", spec) so the sheet
can show what would be assigned; the App confirms via take_pending() (the
"Assign" button) or cancels (Esc / Cancel button → ("cancelled", None)).
"""
from __future__ import annotations

import logging

import Quartz

log = logging.getLogger("listen")

# Plain keycode constants (kept Quartz-free so HotkeyLogic stays testable).
kVK_Escape = 0x35

# Human names for the menu (modifiers we allow as bare-modifier hotkeys).
KEY_NAMES = {
    0x3D: "Right Option",
    0x3A: "Left Option",
    0x36: "Right Command",
    0x37: "Left Command",
    0x3E: "Right Control",
    0x3B: "Left Control",
    0x3C: "Right Shift",
    0x38: "Left Shift",
    0x3F: "Fn",
}

# keycode -> canonical modifier name (L/R collapse to the same name).
MODIFIER_NAMES = {
    0x38: "shift", 0x3C: "shift",    # L/R Shift
    0x3B: "ctrl", 0x3E: "ctrl",      # L/R Control
    0x3A: "alt", 0x3D: "alt",        # L/R Option
    0x37: "cmd", 0x36: "cmd",        # L/R Command
    0x3F: "fn",                       # Fn
}

# Display order + glyph for each modifier name.
_MODIFIER_ORDER = ["ctrl", "alt", "shift", "cmd", "fn"]
MODIFIER_SYMBOLS = {
    "ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘", "fn": "Fn",
}

# Names for plain (non-modifier) keys, for display in the menu/sheet.
KEYCODE_NAMES = {
    0x00: "A", 0x01: "S", 0x02: "D", 0x03: "F", 0x04: "H", 0x05: "G",
    0x06: "Z", 0x07: "X", 0x08: "C", 0x09: "V", 0x0B: "B", 0x0C: "Q",
    0x0D: "W", 0x0E: "E", 0x0F: "R", 0x10: "Y", 0x11: "T", 0x12: "1",
    0x13: "2", 0x14: "3", 0x15: "4", 0x16: "6", 0x17: "5", 0x18: "=",
    0x19: "9", 0x1A: "7", 0x1B: "-", 0x1C: "8", 0x1D: "0", 0x1E: "]",
    0x1F: "O", 0x20: "U", 0x21: "[", 0x22: "I", 0x23: "P", 0x24: "Return",
    0x25: "L", 0x26: "J", 0x27: "'", 0x28: "K", 0x29: ";", 0x2A: "\\",
    0x2B: ",", 0x2C: "/", 0x2D: "N", 0x2E: "M", 0x2F: ".", 0x30: "Tab",
    0x31: "Space", 0x32: "`", 0x33: "Delete", 0x35: "Esc", 0x39: "Caps Lock",
    0x60: "F5", 0x61: "F6", 0x62: "F7", 0x63: "F3", 0x64: "F8", 0x65: "F9",
    0x67: "F10", 0x68: "F12", 0x69: "F13", 0x6A: "F14", 0x6B: "F15",
    0x6D: "F17", 0x6F: "F16", 0x71: "F18", 0x72: "F19", 0x73: "Home",
    0x74: "Page Up", 0x75: "Forward Delete", 0x76: "F4", 0x77: "End",
    0x78: "F2", 0x79: "Page Down", 0x7A: "F1", 0x7B: "←", 0x7C: "→",
    0x7D: "↓", 0x7E: "↑",
}

# keycode -> CGEventFlags bit that is set while that modifier is held.
_MODIFIER_FLAG = {
    0x38: Quartz.kCGEventFlagMaskShift,        # Left Shift
    0x3C: Quartz.kCGEventFlagMaskShift,        # Right Shift
    0x3B: Quartz.kCGEventFlagMaskControl,      # Left Control
    0x3E: Quartz.kCGEventFlagMaskControl,      # Right Control
    0x3A: Quartz.kCGEventFlagMaskAlternate,    # Left Option
    0x3D: Quartz.kCGEventFlagMaskAlternate,    # Right Option
    0x37: Quartz.kCGEventFlagMaskCommand,      # Left Command
    0x36: Quartz.kCGEventFlagMaskCommand,      # Right Command
    0x3F: Quartz.kCGEventFlagMaskSecondaryFn,  # Fn
}


def key_name(keycode: int) -> str:
    """Name for a bare-modifier hotkey (kept for menu back-compat)."""
    return KEY_NAMES.get(keycode, f"Key {keycode}")


def _plain_key_name(keycode: int) -> str:
    return KEYCODE_NAMES.get(keycode, f"Key {keycode}")


def format_hotkey(spec: dict) -> str:
    """Human label for any spec: 'Right Option' or '⌃⌥Space'."""
    if spec.get("is_modifier"):
        return KEY_NAMES.get(spec["keycode"], f"Key {spec['keycode']}")
    mods = spec.get("modifiers", []) or []
    glyphs = [MODIFIER_SYMBOLS[m] for m in _MODIFIER_ORDER if m in mods]
    name = _plain_key_name(spec["keycode"])
    return "".join(glyphs) + name if glyphs else name


def _is_modifier_key(keycode: int) -> bool:
    return keycode in MODIFIER_NAMES


def normalize_spec(spec: dict) -> dict:
    """Fill in defaults so every spec has all three keys, sorted modifiers."""
    return {
        "keycode": int(spec["keycode"]),
        "modifiers": sorted(spec.get("modifiers", []) or []),
        "is_modifier": bool(spec.get("is_modifier", False)),
    }


class HotkeyLogic:
    """Decides what a keyboard event means. No I/O, no Quartz — testable.

    feed() returns None, or:
      ("toggle", None)          — the hotkey fired
      ("preview", spec)         — capture mode saw a candidate (not yet assigned)
      ("cancelled", None)       — capture mode was cancelled with Esc
    """

    DEFAULT_SPEC = {"keycode": 0x3D, "modifiers": [], "is_modifier": True}

    def __init__(self) -> None:
        self.spec: dict = dict(self.DEFAULT_SPEC)
        self.capture = False
        self.pending_spec: dict | None = None
        self._down = False           # bare-modifier: is the spec modifier down
        self._other_down = False     # bare-modifier: was another key pressed mid-stroke
        self._held: set[int] = set()           # modifier keycodes currently held
        self._solo: int | None = None          # the lone modifier held this stroke

    # -- capture mode (sheet: "Change Hotkey") -----------------------------

    def start_capture(self) -> None:
        self.capture = True
        self.pending_spec = None
        self._held.clear()
        self._solo = None

    def cancel_capture(self) -> None:
        self.capture = False
        self.pending_spec = None
        self._solo = None

    def take_pending(self) -> dict | None:
        """Confirm: hand the candidate to the caller and exit capture."""
        spec = self.pending_spec
        self.capture = False
        self.pending_spec = None
        self._solo = None
        return spec

    # -- the decision function ----------------------------------------------

    def feed(self, kind: str, keycode: int, pressed: bool = False):
        """Feed one event: kind "key_down"|"flags_changed"; `pressed` is the
        modifier's held state (only meaningful for flags_changed)."""
        # Track held modifiers in both modes (combo matching + capture).
        if kind == "flags_changed":
            if pressed and _is_modifier_key(keycode):
                self._held.add(keycode)
            elif not pressed and _is_modifier_key(keycode):
                self._held.discard(keycode)
        if self.capture:
            return self._feed_capture(kind, keycode, pressed)
        return self._feed_hotkey(kind, keycode, pressed)

    def _feed_capture(self, kind: str, keycode: int, pressed: bool):
        if kind == "key_down":
            if keycode == kVK_Escape:
                self.cancel_capture()
                return ("cancelled", None)
            if _is_modifier_key(keycode):
                return None  # modifiers arrive as flags_changed
            # A plain key + currently-held modifiers → a combo candidate.
            mods = sorted({MODIFIER_NAMES[k] for k in self._held})
            self.pending_spec = {
                "keycode": keycode, "modifiers": mods, "is_modifier": False,
            }
            self._solo = None
            return ("preview", dict(self.pending_spec))
        if kind == "flags_changed":
            if pressed and _is_modifier_key(keycode):
                if len(self._held) == 1:
                    self._solo = keycode  # lone modifier — tentative bare
                else:
                    self._solo = None
                return None
            if not pressed and _is_modifier_key(keycode):
                if self._solo == keycode and not self._held:
                    # Pressed and released alone → bare-modifier hotkey.
                    self.pending_spec = {
                        "keycode": keycode, "modifiers": [], "is_modifier": True,
                    }
                    self._solo = None
                    return ("preview", dict(self.pending_spec))
                self._solo = None
        return None

    def _feed_hotkey(self, kind: str, keycode: int, pressed: bool):
        spec = self.spec
        if spec.get("is_modifier"):
            if kind == "flags_changed" and keycode == spec["keycode"]:
                if pressed and not self._down:
                    self._down = True
                    self._other_down = False
                elif not pressed and self._down:
                    self._down = False
                    if not self._other_down:
                        return ("toggle", None)
            elif kind == "key_down" and self._down and keycode != spec["keycode"]:
                self._other_down = True  # part of a combo — not a solo press
        else:
            # Combo: key_down of the spec key with exactly the spec modifiers.
            if kind == "key_down" and keycode == spec["keycode"]:
                held = {MODIFIER_NAMES[k] for k in self._held}
                if held == set(spec.get("modifiers", [])):
                    return ("toggle", None)
        return None


class Hotkey:
    """Bridges CGEvents into HotkeyLogic on the main run loop thread."""

    def __init__(self, logic: HotkeyLogic, on_toggle, on_capture=None,
                 on_capture_preview=None, on_capture_cancel=None) -> None:
        self.logic = logic
        self._on_toggle = on_toggle
        self._on_capture = on_capture
        self._on_capture_preview = on_capture_preview
        self._on_capture_cancel = on_capture_cancel
        self._tap = None

    def start(self) -> None:
        mask = (1 << Quartz.kCGEventFlagsChanged) | (1 << Quartz.kCGEventKeyDown)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if not self._tap:
            raise RuntimeError(
                "Failed to create event tap — grant Accessibility permission "
                "to Listen (System Settings → Privacy & Security → Accessibility)."
            )
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(self._tap, True)

    def _callback(self, proxy, type_, event, refcon):
        # An exception escaping a CGEventTap callback is fatal: PyObjC turns
        # it into an ObjC exception that unwinds through CFRunLoop and aborts
        # the app. Log and swallow — the event still passes through.
        try:
            self._handle(proxy, type_, event, refcon)
        except Exception:
            log.exception("error in hotkey callback")
        return event

    def is_enabled(self) -> bool:
        """True if the event tap is live and the system hasn't disabled it."""
        return bool(
            self._tap is not None
            and Quartz.CGEventTapIsEnabled(self._tap)
        )

    def ensure_enabled(self) -> None:
        """Re-enable the tap if macOS disabled it (event-tap timeout).

        macOS will silently disable a CGEventTap whose run-loop source isn't
        serviced promptly (under load, after a long idle, etc.). Once that
        happens the hotkey stops firing — the symptom is a recording that
        can't be stopped and a mic indicator that never clears. Polling this
        from the run loop and re-enabling keeps the hotkey alive.
        """
        if self._tap is not None and not Quartz.CGEventTapIsEnabled(self._tap):
            log.warning("event tap was disabled by the system — re-enabling")
            Quartz.CGEventTapEnable(self._tap, True)

    def _handle(self, proxy, type_, event, refcon):
        keycode = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )
        if type_ == Quartz.kCGEventKeyDown:
            result = self.logic.feed("key_down", keycode)
        elif type_ == Quartz.kCGEventFlagsChanged:
            flag = _MODIFIER_FLAG.get(keycode, 0)
            pressed = bool(Quartz.CGEventGetFlags(event) & flag) if flag else False
            result = self.logic.feed("flags_changed", keycode, pressed)
        else:
            return
        self._dispatch(result)

    def _dispatch(self, result) -> None:
        """Route one feed() result; None (event ignored) is not an error."""
        if result is None:
            return
        action, value = result
        if action == "toggle" and self._on_toggle is not None:
            self._on_toggle()
        elif action == "preview" and self._on_capture_preview is not None:
            self._on_capture_preview(value)
        elif action == "captured" and self._on_capture is not None:
            self._on_capture(value)
        elif action == "cancelled" and self._on_capture_cancel is not None:
            self._on_capture_cancel()