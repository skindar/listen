"""Model sha256 verification logic (tiny fake files, monkeypatched hashes)."""
import hashlib

import pytest

from listen import model


def test_ensure_verified_ok_writes_marker(tmp_path, monkeypatch):
    dest = tmp_path / "m.gguf"
    dest.write_bytes(b"hello")
    monkeypatch.setattr(
        model, "expected_sha256", lambda: hashlib.sha256(b"hello").hexdigest()
    )
    model.ensure_verified(dest)
    assert model._marker(dest).is_file()
    # marker short-circuits: a changed expectation is not even consulted
    monkeypatch.setattr(model, "expected_sha256", lambda: "wrong")
    model.ensure_verified(dest)


def test_ensure_verified_mismatch_deletes_file(tmp_path, monkeypatch):
    dest = tmp_path / "m.gguf"
    dest.write_bytes(b"hello")
    monkeypatch.setattr(model, "expected_sha256", lambda: "deadbeef")
    with pytest.raises(RuntimeError):
        model.ensure_verified(dest)
    assert not dest.exists()
    assert not model._marker(dest).is_file()


def test_ensure_verified_no_expectation_skips(tmp_path, monkeypatch):
    dest = tmp_path / "m.gguf"
    dest.write_bytes(b"hello")
    monkeypatch.setattr(model, "expected_sha256", lambda: None)
    model.ensure_verified(dest)  # no-op, no marker
    assert dest.is_file()
    assert not model._marker(dest).is_file()
