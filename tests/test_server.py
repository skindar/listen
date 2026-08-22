"""Server pieces that don't need a model: port picking and multipart body."""
import socket

from listen.server import Server, _free_port


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
