"""Model sha256 verification logic (tiny fake files, monkeypatched hashes)."""
import hashlib
import urllib.request

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


class _FakeResp:
    def __init__(self, chunks, length):
        self._chunks = chunks
        self.length = length

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_progress_is_throttled(tmp_path, monkeypatch):
    """1000 1-MiB chunks would be ~1000 progress hops; throttled to ~1% it
    must be far fewer, with a final 100% call."""
    total = 1000
    chunks = [b"x" * (1 << 20) for _ in range(total)]
    monkeypatch.setattr(model, "model_path", lambda: tmp_path / "m.gguf")
    monkeypatch.setattr(model.config, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(model, "ensure_verified", lambda dest: None)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=60: _FakeResp(chunks, total << 20),
    )

    calls = []
    model.download(progress=lambda d, t: calls.append((d, t)))

    assert len(calls) < 200  # throttled from ~1000
    assert calls[-1] == (total << 20, total << 20)  # final 100%
