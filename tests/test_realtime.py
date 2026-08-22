"""Tests for the minimal WebSocket client and the realtime streaming session.

ws.py is exercised against a real loopback TCP server doing the RFC 6455
handshake; realtime.py is driven by a fake transport so the decision logic
(connect → feed → finalize) is deterministic."""
import base64
import hashlib
import json
import socket
import threading
import time

from listen.realtime import RealtimeClient
from listen.ws import WS, OP_BINARY, OP_TEXT

_GUID = "258EA5-E914-47DA-95CA-C5AB0DC85B11"


def _accept_key(client_key: str) -> str:
    return base64.b64encode(
        hashlib.sha1((client_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()


def _read_client_frame(sock) -> tuple[int, bytes]:
    b0, b1 = sock.recv(1)[0], sock.recv(1)[0]
    opcode = b0 & 0x0F
    plen = b1 & 0x7F
    if plen == 126:
        plen = int.from_bytes(sock.recv(2), "big")
    elif plen == 127:
        plen = int.from_bytes(sock.recv(8), "big")
    mask = sock.recv(4)
    payload = b""
    while len(payload) < plen:
        payload += sock.recv(plen - len(payload))
    payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    return opcode, payload


def _send_server_frame(sock, payload: bytes, opcode: int = OP_TEXT) -> None:
    out = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        out.append(n)
    elif n < 65536:
        out.append(126); out += n.to_bytes(2, "big")
    else:
        out.append(127); out += n.to_bytes(8, "big")
    out += payload
    sock.sendall(bytes(out))


# -- ws.py: real loopback handshake + framing ----------------------------

def test_ws_handshake_and_roundtrip():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def server():
        conn, _ = srv.accept()
        # Read the HTTP upgrade request.
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        key = None
        for line in data.split(b"\r\n"):
            if line.lower().startswith(b"sec-websocket-key:"):
                key = line.split(b":", 1)[1].strip().decode()
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {_accept_key(key)}\r\n\r\n"
        )
        conn.sendall(resp.encode())
        # Read one binary frame from the client, echo it back as text.
        op, payload = _read_client_frame(conn)
        assert op == OP_BINARY
        _send_server_frame(conn, b"echo:" + payload, opcode=OP_TEXT)
        # Read the commit text frame, then a close.
        op2, payload2 = _read_client_frame(conn)
        conn.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()

    ws = WS()
    ws.connect("127.0.0.1", port, "/v1/realtime", timeout=5)
    ws.send_binary(b"audio-bytes")
    op, payload = ws.recv()
    assert op == OP_TEXT
    assert payload == b"echo:audio-bytes"
    ws.close()
    t.join(timeout=3)


def test_ws_large_payload_uses_16bit_length():
    """A >125-byte payload must use the 126 (16-bit) length encoding."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def server():
        conn, _ = srv.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: x\r\n\r\n")
        op, payload = _read_client_frame(conn)
        assert len(payload) == 500
        conn.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    ws = WS()
    # The server doesn't validate the accept key, so connect succeeds.
    ws.connect("127.0.0.1", port, "/v1/realtime", timeout=5)
    ws.send_binary(b"x" * 500)
    ws.close()
    t.join(timeout=3)


# -- realtime.py: fake transport -----------------------------------------

class FakeWS:
    """Scripted transport for RealtimeClient.

    `empty_exc` chooses what recv() raises once the script is exhausted:
    ConnectionError (default — a real death, fires on_dead) or TimeoutError
    (a quiet server — the receiver keeps waiting, session stays alive)."""
    def __init__(self, events, empty_exc=ConnectionError):
        self._events = list(events)
        self._empty_exc = empty_exc
        self.sent: list[tuple[str, object]] = []
        self.closed = False

    def connect(self, h, p, path, timeout):
        pass

    def set_timeout(self, seconds):
        pass

    def send_text(self, text):
        self.sent.append(("text", text))

    def send_binary(self, blob):
        self.sent.append(("binary", blob))

    def recv(self):
        if self._events:
            return self._events.pop(0)
        if self._empty_exc is TimeoutError:
            time.sleep(0.01)
        raise self._empty_exc("script exhausted")

    def close(self):
        self.closed = True


def _evt(d):
    return (OP_TEXT, json.dumps(d))


def test_realtime_connect_feed_finalize():
    events = [
        _evt({"type": "session.created"}),
        _evt({"type": "session.updated"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "Hello"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "world"}),
        _evt({"type": "input_audio_buffer.committed"}),
    ]
    fake = FakeWS(events)
    c = RealtimeClient("127.0.0.1", 9999, language="ru-RU", transport=fake)
    c.connect()
    c.feed(b"\x00" * 3200)
    c.feed(b"\x00" * 3200)
    text = c.finalize(timeout=2)
    assert text == "Hello world"
    assert abs(c.seconds - 0.2) < 1e-6  # 6400 bytes / 32000
    c.close()
    texts = [s[1] for s in fake.sent if s[0] == "text"]
    assert any("session.update" in t for t in texts)
    assert any("commit" in t for t in texts)
    assert any("ru-RU" in t for t in texts)
    assert any(s[0] == "binary" for s in fake.sent)


def test_realtime_finalize_timeout_returns_what_it_has():
    # Session stays alive (quiet server) but commit ack never comes → finalize
    # times out and still returns the collected finals.
    events = [
        _evt({"type": "session.created"}),
        _evt({"type": "session.updated"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "partial result"}),
    ]
    fake = FakeWS(events, empty_exc=TimeoutError)
    c = RealtimeClient("127.0.0.1", 9999, transport=fake)
    c.connect()
    text = c.finalize(timeout=0.4)
    assert text == "partial result"
    c.close()


def test_realtime_connect_rejects_wrong_first_event():
    fake = FakeWS([_evt({"type": "error"})])
    c = RealtimeClient("127.0.0.1", 9999, transport=fake)
    try:
        c.connect()
        assert False, "should have raised"
    except RuntimeError:
        pass


def test_realtime_on_delta_fires_per_fragment():
    """Each incremental delta fragment fires on_delta so the app can paste live."""
    frags: list[str] = []
    events = [
        _evt({"type": "session.created"}),
        _evt({"type": "session.updated"}),
        _evt({"type": "conversation.item.input_audio_transcription.delta", "delta": "Hel"}),
        _evt({"type": "conversation.item.input_audio_transcription.delta", "delta": ""}),
        _evt({"type": "conversation.item.input_audio_transcription.delta", "delta": "lo"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hello"}),
        _evt({"type": "input_audio_buffer.committed"}),
    ]
    fake = FakeWS(events)
    c = RealtimeClient("127.0.0.1", 9999, transport=fake, on_delta=frags.append)
    c.connect()
    c.finalize(timeout=2)
    assert frags == ["Hel", "lo"]  # empty delta skipped
    c.close()


def test_realtime_on_final_fires_per_completed():
    """Each finalized utterance fires on_final (used as a flush signal)."""
    finals: list[str] = []
    events = [
        _evt({"type": "session.created"}),
        _evt({"type": "session.updated"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "First sentence."}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "Second sentence."}),
        _evt({"type": "input_audio_buffer.committed"}),
    ]
    fake = FakeWS(events)
    c = RealtimeClient("127.0.0.1", 9999, transport=fake, on_final=finals.append)
    c.connect()
    c.finalize(timeout=2)
    assert finals == ["First sentence.", "Second sentence."]
    c.close()


def test_realtime_on_final_skips_empty_transcript():
    finals: list[str] = []
    events = [
        _evt({"type": "session.created"}),
        _evt({"type": "session.updated"}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": ""}),
        _evt({"type": "conversation.item.input_audio_transcription.completed",
              "transcript": "Real one."}),
        _evt({"type": "input_audio_buffer.committed"}),
    ]
    fake = FakeWS(events)
    c = RealtimeClient("127.0.0.1", 9999, transport=fake, on_final=finals.append)
    c.connect()
    c.finalize(timeout=2)
    assert finals == ["Real one."]
    c.close()


def test_on_dead_fires_on_unexpected_close():
    """An unexpected socket close (not a normal close()) fires on_dead."""
    dead = threading.Event()
    fake = FakeWS([_evt({"type": "session.created"}),
                   _evt({"type": "session.updated"})])  # then recv raises
    c = RealtimeClient("127.0.0.1", 9999, transport=fake, on_dead=dead.set)
    c.connect()
    assert dead.wait(2.0), "on_dead did not fire"
    c.close()


def test_finalize_returns_fast_when_already_dead():
    fake = FakeWS([_evt({"type": "session.created"}),
                   _evt({"type": "session.updated"})])
    c = RealtimeClient("127.0.0.1", 9999, transport=fake)
    c.connect()
    c._error = "simulated death"
    t0 = time.time()
    assert c.finalize(timeout=5) == ""
    assert time.time() - t0 < 0.5  # did not wait for the timeout
    c.close()


def test_on_dead_not_fired_on_normal_close():
    dead = threading.Event()
    events = [_evt({"type": "session.created"}), _evt({"type": "session.updated"})]
    # Quiet server: receiver keeps waiting (no death) until we close().
    fake = FakeWS(events, empty_exc=TimeoutError)
    c = RealtimeClient("127.0.0.1", 9999, transport=fake, on_dead=dead.set)
    c.connect()
    c.close()  # normal close — must NOT fire on_dead
    time.sleep(0.3)
    assert not dead.is_set()