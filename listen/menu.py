"""Build the menu-bar menu — the entire UI of the app.

Rebuilt in place on every open (menuWillOpen:) so titles, checkmarks and the
transient ⚠ items are always current. Four entities, no Preferences windows:

    Hotkey: Right Option   ▸
    Language: Auto         ▸
    Auto-Replace…
    ✓ Start at Login
    ─────────────────────────
    Quit                    ⌘Q
"""
from __future__ import annotations

import AppKit

from . import hotkey, languages


def rebuild(menu, target, snap: dict) -> None:
    """Rebuild `menu` for the app snapshot. `target` receives all actions."""
    menu.removeAllItems()
    menu.setAutoenablesItems_(False)

    # Transient problems first — visible without opening any submenu.
    if snap["error_line"]:
        _item(menu, snap["error_line"], enabled=False)
        _item(menu, "Show Log", "openLog:", target)
    if not snap["ax_ok"]:
        _item(menu, "⚠ Grant Accessibility…", "grantAccessibility:", target)
    if snap["mic_denied"]:
        _item(menu, "⚠ Grant Microphone Access…", "grantMicrophone:", target)
    if menu.numberOfItems() > 0:
        _separator(menu)

    _hotkey_submenu(menu, target, snap)
    _language_submenu(menu, target, snap)
    _item(menu, "Auto-Replace…", "openCorrections:", target)
    _autostart_item(menu, target, snap)

    _separator(menu)
    _item(menu, "Quit Listen", "terminate:", key="q")


# -- sections -------------------------------------------------------------


def _hotkey_submenu(menu, target, snap: dict) -> None:
    sub = _submenu(menu, f"Hotkey: {snap['hotkey_name']}", enabled=snap["ax_ok"])
    _item(sub, "Change…", "changeHotkey:", target, enabled=snap["ax_ok"])
    if snap["hotkey"] != dict(hotkey.HotkeyLogic.DEFAULT_SPEC):
        _item(sub, "Reset to Default", "resetHotkey:", target)


def _language_submenu(menu, target, snap: dict) -> None:
    current = snap["language"]
    sub = _submenu(menu, f"Language: {languages.label(current)}")
    _item(
        sub, "Auto", "selectLanguage:", target,
        state=_mark(current is None), represented="auto",
    )
    _separator(sub)
    for code, name in languages.READY:
        _lang_item(sub, target, code, name, current)


def _lang_item(sub, target, code: str, name: str, current: str | None) -> None:
    _item(
        sub, name, "selectLanguage:", target,
        state=_mark(code == current), represented=code,
    )


def _autostart_item(menu, target, snap: dict) -> None:
    _item(
        menu, "Start at Login", "toggleLogin:", target,
        state=_mark(snap["autostart_on"]),
    )


# -- primitives --------------------------------------------------------------


def _mark(on: bool) -> int:
    return AppKit.NSControlStateValueOn if on else AppKit.NSControlStateValueOff


def _item(menu, title, action=None, target=None, key="", enabled=True,
          state=None, represented=None):
    item = menu.addItemWithTitle_action_keyEquivalent_(title, action or "", key)
    if target is not None and action:
        item.setTarget_(target)
    if represented is not None:
        item.setRepresentedObject_(represented)
    if state is not None:
        item.setState_(state)
    item.setEnabled_(enabled)
    return item


def _separator(menu) -> None:
    # A real hairline — an empty-title item renders as a selectable blank row.
    menu.addItem_(AppKit.NSMenuItem.separatorItem())


def _submenu(menu, title: str, enabled: bool = True):
    item = menu.addItemWithTitle_action_keyEquivalent_(title, "", "")
    item.setEnabled_(enabled)
    sub = AppKit.NSMenu.alloc().init()
    item.setSubmenu_(sub)
    return sub
