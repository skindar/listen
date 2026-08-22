"""A minimal RFC 6455 WebSocket client over a raw socket — localhost only.

No third-party dependency (the project ships zero runtime deps beyond PyObjC,
numpy, sounddevice). This implements exactly what Listen's realtime ASR path
needs: an upgrade handshake, client→server masked binary/text frames, and
server→client frame reads with auto-pong. It is not a general-purpose client:
no TLS, no extensions, no compression, no subprotocols — a single loopback
connection to the bundled nemo-speech server.

Frame format refresher (RFC 6455):
  byte0: FIN(1) | RSV(3) | opcode(4)
  byte1: MASK(1) | payload_len(7)   → 126: next 2 bytes len; 127: next 8 bytes
  then 4-byte masking key if MASK, then payload XOR'd with the key.
Server→client frames are not masked.
"""
from __future__ import annotations

import base64
import os
import socket
import struct

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WS:
    """A blocking, single-connection loopback WebSocket client."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None

    def connect(self, host: str, port: int, path: str, timeout: float = 10.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(req.encode())
        # Read the HTTP upgrade response headers.
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed during WebSocket handshake")
            data += chunk
        status = data.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"WebSocket upgrade failed: {status.decode(errors='replace')}")
        # The handshake used `timeout`; from here on the socket blocks
        # indefinitely so a quiet server (silence, a pause between utterances)
        # doesn't look like a dead connection. The receiver thread relies on
        # this — a recv timeout would otherwise tear down the session.
        self._sock.settimeout(None)

    def set_timeout(self, seconds: float | None) -> None:
        """Switch the socket timeout for ongoing recv/send operations."""
        if self._sock is not None:
            self._sock.settimeout(seconds)

    def send_binary(self, payload: bytes) -> None:
        self._send(payload, OP_BINARY)

    def send_text(self, text: str) -> None:
        self._send(text.encode("utf-8"), OP_TEXT)

    def _send(self, payload: bytes, opcode: int) -> None:
        if self._sock is None:
            raise ConnectionError("not connected")
        out = bytearray([0x80 | opcode])  # FIN + opcode
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            out.append(0x80 | n)  # client frames must be masked
        elif n < 65536:
            out.append(0x80 | 126)
            out += struct.pack("!H", n)
        else:
            out.append(0x80 | 127)
            out += struct.pack("!Q", n)
        out += mask
        out += bytes(payload[i] ^ mask[i % 4] for i in range(n))
        self._sock.sendall(bytes(out))

    def recv(self) -> tuple[int, bytes]:
        """Return (opcode, payload) for one complete message, reassembling
        fragmented frames and answering pings with pongs automatically.
        Returns (OP_CLOSE, b'') when the peer closes."""
        opcode, payload = self._recv_frame()
        if opcode == OP_PING:
            self._send(payload, OP_PONG)
            return self.recv()
        if opcode == OP_PONG:
            return self.recv()
        if opcode == OP_CLOSE:
            return OP_CLOSE, b""
        # Reassemble a fragmented message (FIN=0 → continuation frames).
        while not self._last_fin and opcode != OP_CLOSE:
            cont_op, cont = self._recv_frame()
            if cont_op == OP_PING:
                self._send(cont, OP_PONG)
                continue
            payload += cont
            if self._last_fin or cont_op == OP_CLOSE:
                break
        return opcode, payload

    def _recv_frame(self) -> tuple[int, bytes]:
        assert self._sock is not None
        b0, b1 = self._recv_exact(2)
        self._last_fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        plen = b1 & 0x7F
        if plen == 126:
            plen = struct.unpack("!H", self._recv_exact(2))[0]
        elif plen == 127:
            plen = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(plen) if plen else b""
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        return opcode, payload

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed mid-frame")
            buf += chunk
        return buf

    def close(self) -> None:
        if self._sock is not None:
            try:
                # Send a close frame, best-effort.
                self._send(b"", OP_CLOSE)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None