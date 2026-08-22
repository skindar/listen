"""Settings persistence: defaults, roundtrip, corrupt-file safety."""
from listen.settings import Settings

RALT = 0x3D


def test_defaults_on_missing_file(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.hotkey == {"keycode": RALT, "modifiers": [], "is_modifier": True}
    assert s.language is None


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(path)
    s.set_hotkey({"keycode": 0x3C, "modifiers": [], "is_modifier": True})
    s.set_language("ru-RU")
    again = Settings(path)
    assert again.hotkey == {"keycode": 0x3C, "modifiers": [], "is_modifier": True}
    assert again.language == "ru-RU"


def test_roundtrip_combo(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(path)
    s.set_hotkey({"keycode": 0x31, "modifiers": ["ctrl", "alt"], "is_modifier": False})
    again = Settings(path)
    assert again.hotkey == {"keycode": 0x31, "modifiers": ["alt", "ctrl"],
                            "is_modifier": False}


def test_old_spec_without_modifiers_migrates(tmp_path):
    """A spec written by the previous version (no modifiers key) loads fine."""
    path = tmp_path / "settings.json"
    path.write_text('{"hotkey": {"keycode": 0x3D, "is_modifier": true}}',
                     encoding="utf-8")
    s = Settings(path)
    assert s.hotkey == {"keycode": 0x3D, "modifiers": [], "is_modifier": True}


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    s = Settings(path)  # must not raise
    assert s.hotkey["keycode"] == RALT
    assert s.language is None


def test_unknown_language_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"language": "xx-XX"}', encoding="utf-8")
    s = Settings(path)
    assert s.language is None


def test_malformed_hotkey_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"hotkey": "junk"}', encoding="utf-8")
    s = Settings(path)
    assert s.hotkey["keycode"] == RALT


def test_set_language_rejects_unknown(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.set_language("xx-XX")
    assert s.language is None