"""Server pieces that don't need a model: port picking and multipart body."""
import socket

import pytest

from listen.server import FAILED, READY, Server, _free_port


def test_free_port_is_usable():
    port = _free_port()
    assert 1024 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # still free


def test_free_port_varies():
    # OS-assigned ports are extremely unlikely to repeat back to back.
    assert len({_free_port() for _ in range(5)}) > 1


def test_multipart_without_language():
    body = Server._multipart(b"AUDIO", "bnd", None)
    assert b'name="file"; filename="audio.wav"' in body
    assert b"Content-Type: audio/wav" in body
    assert b"AUDIO" in body
    assert b'name="language"' not in body
    assert body.endswith(b"--bnd--\r\n")


def test_multipart_with_language():
    body = Server._multipart(b"AUDIO", "bnd", "ru-RU")
    assert b'name="language"' in body
    assert b"ru-RU" in body


# -- ensure_ready waits on the readiness event, not a poll ---------------------


def _server_with(state, error=None):
    s = Server()
    s._state = state
    s._error = error
    return s


def test_ensure_ready_returns_when_ready():
    s = _server_with(READY)
    s._ready_event.set()
    s.ensure_ready(timeout=1.0)  # returns immediately, no raise


def test_ensure_ready_raises_on_failed():
    s = _server_with(FAILED, error="boom")
    s._ready_event.set()
    with pytest.raises(RuntimeError, match="boom"):
        s.ensure_ready(timeout=1.0)


def test_ensure_ready_times_out():
    s = _server_with("loading")
    # event never set — must time out, not spin forever
    with pytest.raises(TimeoutError):
        s.ensure_ready(timeout=0.05)


def test_state_callback_fires_on_notify():
    s = _server_with(READY)
    calls = []
    s.set_state_callback(lambda: calls.append(s.state))
    s._notify()
    assert calls == [READY]
