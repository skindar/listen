"""Autostart pure logic: whose program does the on-disk agent launch?"""
import plistlib

from listen import autostart


def _write_plist(tmp_path, program_args):
    plist = tmp_path / "agent.plist"
    plist.write_bytes(
        plistlib.dumps(
            {"Label": autostart.AGENT_LABEL, "ProgramArguments": program_args}
        )
    )
    return plist


def test_plist_program_joins_args(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "AGENT_PLIST", _write_plist(
        tmp_path, ["/some/python", "-m", "listen"]))
    assert autostart._plist_program() == "/some/python -m listen"


def test_plist_program_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "AGENT_PLIST", tmp_path / "nope.plist")
    assert autostart._plist_program() is None


def test_launches_current_matches_dev(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "AGENT_PLIST", _write_plist(
        tmp_path, ["/venv/bin/python", "-m", "listen"]))
    monkeypatch.setattr(autostart, "_app_executable",
                        lambda: "/venv/bin/python -m listen")
    assert autostart._launches_current(autostart._plist_program()) is True


def test_launches_current_rejects_other_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "AGENT_PLIST", _write_plist(
        tmp_path, ["/venv/bin/python", "-m", "listen"]))
    monkeypatch.setattr(
        autostart, "_app_executable",
        lambda: "/Applications/Listen.app/Contents/MacOS/run")
    assert autostart._launches_current(autostart._plist_program()) is False


def test_launches_current_none():
    assert autostart._launches_current(None) is False
