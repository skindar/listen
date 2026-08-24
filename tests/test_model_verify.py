"""Model sha256 verification logic (tiny fake files, monkeypatched hashes)."""
import hashlib
import time
import urllib.error
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
    def __init__(self, chunks, length, status=200):
        self._chunks = chunks
        self.length = length
        self._status = status

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def getcode(self):
        return self._status

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


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "model_path", lambda: tmp_path / "m.gguf")
    monkeypatch.setattr(model.config, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(model, "ensure_verified", lambda dest: None)
    monkeypatch.setattr(model.time, "sleep", lambda _s: None)  # no backoff wait


def test_download_resumes_from_partial(tmp_path, monkeypatch):
    """A leftover .part is continued via Range (206): the server sends only the
    remaining bytes and the file is appended, not restarted from zero."""
    _patch_paths(tmp_path, monkeypatch)
    have = 2 << 20
    (tmp_path / "m.gguf.part").write_bytes(b"A" * have)
    remaining = [b"B" * (1 << 20) for _ in range(3)]
    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["range"] = req.headers.get("Range")
        return _FakeResp(remaining, length=3 << 20, status=206)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    model.download()
    assert captured["range"] == f"bytes={have}-"
    assert (tmp_path / "m.gguf").read_bytes() == b"A" * have + b"B" * (3 << 20)


def test_download_retries_on_network_error(tmp_path, monkeypatch):
    """A dropped connection (URLError) is retried; the download still completes."""
    _patch_paths(tmp_path, monkeypatch)
    good = _FakeResp([b"X" * (1 << 20), b"Y" * (1 << 20)], length=2 << 20)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=60):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise urllib.error.URLError("conn dropped")
        return good

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    model.download()
    assert (tmp_path / "m.gguf").read_bytes() == b"X" * (1 << 20) + b"Y" * (1 << 20)
    assert calls["n"] == 3  # two failures, then success


def test_download_raises_after_max_retries(tmp_path, monkeypatch):
    """A persistently failing connection gives up with RuntimeError, not a loop."""
    _patch_paths(tmp_path, monkeypatch)

    def fake_urlopen(req, timeout=60):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="retries"):
        model.download()
