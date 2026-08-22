"""HotkeyLogic is pure (no Quartz) — decision table tests."""
from listen.hotkey import Hotkey, HotkeyLogic, format_hotkey

RALT, LALT, RSHIFT, LSHIFT, RCTRL, ESC, A_KEY, SPACE = (
    0x3D, 0x3A, 0x3C, 0x38, 0x3E, 0x35, 0x00, 0x31,
)


def test_dispatch_none_is_ignored():
    """Regression: the tap callback once unpacked feed()'s None and crashed
    on the very first (press) event."""
    calls = []
    hotkey = Hotkey(HotkeyLogic(), on_toggle=lambda: calls.append("toggle"))
    hotkey._dispatch(None)  # must not raise, must not call anything
    assert calls == []
    hotkey._dispatch(("toggle", None))
    assert calls == ["toggle"]


def press(logic, keycode):
    return logic.feed("flags_changed", keycode, True)


def release(logic, keycode):
    return logic.feed("flags_changed", keycode, False)


def key(logic, keycode):
    return logic.feed("key_down", keycode)


# -- default + bare-modifier toggle --------------------------------------

def test_default_spec_is_right_option():
    assert HotkeyLogic.DEFAULT_SPEC == {
        "keycode": RALT, "modifiers": [], "is_modifier": True,
    }


def test_solo_modifier_press_toggles():
    logic = HotkeyLogic()
    assert press(logic, RALT) is None
    assert release(logic, RALT) == ("toggle", None)


def test_modifier_repeats():
    logic = HotkeyLogic()
    press(logic, RALT); release(logic, RALT)
    assert release(logic, RALT) is None  # stray release ignored
    press(logic, RALT); release(logic, RALT)
    assert logic.feed("flags_changed", RALT, True) is None  # press alone: no toggle


def test_modifier_in_combo_does_not_toggle():
    logic = HotkeyLogic()
    press(logic, RALT)
    assert key(logic, A_KEY) is None   # other key while held → combo
    assert release(logic, RALT) is None  # release after combo: no toggle


def test_other_modifiers_ignored():
    logic = HotkeyLogic()
    assert press(logic, LALT) is None
    assert release(logic, LALT) is None
    assert press(logic, RSHIFT) is None
    assert release(logic, RSHIFT) is None


def test_spec_change_applies_live():
    logic = HotkeyLogic()
    logic.spec = {"keycode": LALT, "modifiers": [], "is_modifier": True}
    assert press(logic, RALT) is None
    assert release(logic, RALT) is None
    assert press(logic, LALT) is None
    assert release(logic, LALT) == ("toggle", None)


# -- plain-key (no modifiers) toggle -------------------------------------

def test_plain_key_spec_toggles_on_keydown():
    logic = HotkeyLogic()
    logic.spec = {"keycode": 0x05, "modifiers": [], "is_modifier": False}
    assert key(logic, 0x05) == ("toggle", None)
    assert key(logic, 0x05) == ("toggle", None)
    assert key(logic, 0x06) is None
    assert press(logic, RALT) is None  # modifiers tracked but irrelevant


# -- combo (modifier + key) toggle ---------------------------------------

def test_combo_toggles_when_modifiers_match():
    logic = HotkeyLogic()
    logic.spec = {"keycode": SPACE, "modifiers": ["ctrl", "alt"],
                  "is_modifier": False}
    press(logic, RCTRL); press(logic, RALT)
    assert key(logic, SPACE) == ("toggle", None)
    release(logic, RCTRL); release(logic, RALT)


def test_combo_does_not_toggle_when_modifiers_wrong():
    logic = HotkeyLogic()
    logic.spec = {"keycode": SPACE, "modifiers": ["ctrl", "alt"],
                  "is_modifier": False}
    press(logic, RCTRL)  # only ctrl held, not alt
    assert key(logic, SPACE) is None
    release(logic, RCTRL)


def test_combo_lr_modifiers_collapse():
    """Left and Right of the same modifier both satisfy a modifier name."""
    logic = HotkeyLogic()
    logic.spec = {"keycode": SPACE, "modifiers": ["shift"], "is_modifier": False}
    press(logic, LSHIFT)  # left shift satisfies "shift"
    assert key(logic, SPACE) == ("toggle", None)
    release(logic, LSHIFT)


def test_combo_extra_modifier_blocks():
    logic = HotkeyLogic()
    logic.spec = {"keycode": SPACE, "modifiers": ["ctrl"], "is_modifier": False}
    press(logic, RCTRL); press(logic, RALT)  # extra alt held
    assert key(logic, SPACE) is None
    release(logic, RCTRL); release(logic, RALT)


# -- capture mode: two-step preview → take_pending ----------------------

def test_capture_plain_key_previews():
    logic = HotkeyLogic()
    logic.start_capture()
    assert key(logic, 0x22) == ("preview", {
        "keycode": 0x22, "modifiers": [], "is_modifier": False,
    })
    assert logic.capture is True  # still capturing until Assign/Cancel
    assert logic.pending_spec["keycode"] == 0x22


def test_capture_combo_previews_with_held_modifiers():
    logic = HotkeyLogic()
    logic.start_capture()
    press(logic, RCTRL); press(logic, RALT)
    r = key(logic, SPACE)
    assert r == ("preview", {
        "keycode": SPACE, "modifiers": ["alt", "ctrl"], "is_modifier": False,
    })
    release(logic, RCTRL); release(logic, RALT)


def test_capture_bare_modifier_previews_on_solo_release():
    logic = HotkeyLogic()
    logic.start_capture()
    assert press(logic, RSHIFT) is None      # no preview on press
    assert release(logic, RSHIFT) == ("preview", {
        "keycode": RSHIFT, "modifiers": [], "is_modifier": True,
    })


def test_capture_modifier_in_combo_is_not_bare():
    logic = HotkeyLogic()
    logic.start_capture()
    press(logic, RCTRL); press(logic, RSHIFT)  # two modifiers held
    assert release(logic, RSHIFT) is None     # not solo → no bare preview
    assert release(logic, RCTRL) is None
    # then a plain key with the held modifiers — but they're released now
    assert key(logic, SPACE) == ("preview", {
        "keycode": SPACE, "modifiers": [], "is_modifier": False,
    })


def test_capture_repeated_key_updates_preview():
    logic = HotkeyLogic()
    logic.start_capture()
    assert key(logic, A_KEY) == ("preview", {
        "keycode": A_KEY, "modifiers": [], "is_modifier": False,
    })
    assert key(logic, SPACE) == ("preview", {
        "keycode": SPACE, "modifiers": [], "is_modifier": False,
    })


def test_take_pending_confirms_and_exits():
    logic = HotkeyLogic()
    logic.start_capture()
    key(logic, 0x22)
    spec = logic.take_pending()
    assert spec == {"keycode": 0x22, "modifiers": [], "is_modifier": False}
    assert logic.capture is False
    assert logic.pending_spec is None


def test_take_pending_none_when_no_press():
    logic = HotkeyLogic()
    logic.start_capture()
    assert logic.take_pending() is None
    assert logic.capture is False


def test_capture_esc_cancels():
    logic = HotkeyLogic()
    logic.start_capture()
    assert key(logic, ESC) == ("cancelled", None)
    assert logic.capture is False


def test_cancel_capture_clears_pending():
    logic = HotkeyLogic()
    logic.start_capture()
    key(logic, 0x22)
    logic.cancel_capture()
    assert logic.capture is False
    assert logic.pending_spec is None


def test_no_toggle_from_new_hotkey_release_after_capture():
    logic = HotkeyLogic()
    logic.start_capture()
    assert press(logic, RSHIFT) is None
    assert release(logic, RSHIFT) == ("preview", {
        "keycode": RSHIFT, "modifiers": [], "is_modifier": True,
    })
    # releasing the just-captured key must not count as a solo press after
    # capture is confirmed.
    logic.take_pending()
    assert release(logic, RSHIFT) is None


# -- format_hotkey -------------------------------------------------------

def test_format_bare_modifier():
    assert format_hotkey(
        {"keycode": RALT, "modifiers": [], "is_modifier": True}
    ) == "Right Option"


def test_format_combo():
    spec = {"keycode": SPACE, "modifiers": ["ctrl", "alt"], "is_modifier": False}
    assert format_hotkey(spec) == "⌃⌥Space"


def test_format_plain_key_no_mods():
    spec = {"keycode": SPACE, "modifiers": [], "is_modifier": False}
    assert format_hotkey(spec) == "Space"


def test_format_modifier_order_canonical():
    spec = {"keycode": A_KEY, "modifiers": ["cmd", "shift", "alt", "ctrl"],
            "is_modifier": False}
    assert format_hotkey(spec) == "⌃⌥⇧⌘A"