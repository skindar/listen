"""Pilot: distill the ASR's own errors into a correction dictionary.

For each term x carrier x voice: synthesize Russian-accented speech of the
English term embedded in a Russian carrier sentence (`say`), stream it through
the same /v1/realtime session the app uses, and record what the model actually
transcribed. The middle segment (between the known carrier words) is the
mis-recognized form of the term — a ready correction pair. No manual
transcription anywhere: the ASR labels its own errors.

Run (repo root):  .venv/bin/python scripts/pilot_corrections.py
Requires a running nemo-speech server (the menu-bar app's own is reused).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
import wave
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from listen import config
from listen.realtime import RealtimeClient

# --- pilot inputs --------------------------------------------------------------

TERMS = ["brew cask", "Kubernetes", "GitHub", "Docker", "PostgreSQL"]

# (rendered sentence, known tokens before the term, known tokens after it)
CARRIERS = [
    ("Термин {t}, важен.", ["термин"], ["важен"]),
    ("Сделай {t} и запусти.", ["сделай"], ["и", "запусти"]),
]

VOICES = ["Milena", "Milena (Enhanced)"]

# --- helpers -------------------------------------------------------------------


def find_server_port() -> int | None:
    """Reuse the running app's nemo-speech server; None if there is none."""
    r = subprocess.run(
        ["pgrep", "-f", r"nemo-speech serve .*--no-warmup"],
        capture_output=True, text=True,
    )
    for pid in r.stdout.split():
        ps = subprocess.run(
            ["ps", "-p", pid, "-o", "command="], capture_output=True, text=True
        )
        m = re.search(r"--port (\d+)", ps.stdout)
        if m:
            return int(m.group(1))
    return None


def synth(text: str, voice: str, path: Path) -> None:
    subprocess.run(
        ["say", "-v", voice, "-o", str(path), "--data-format=LEI16@16000", text],
        check=True,
    )


def pcm_of(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes())


def transcribe(port: int, pcm: bytes) -> str:
    """One fresh realtime session per utterance, like the app's recording."""
    client = RealtimeClient(config.HOST, port, endpointing_ms=config.ENDPOINTING_MS)
    client.connect()
    try:
        trailing_silence = b"\x00" * (config.SAMPLE_RATE * 2 // 5)  # 0.4 s
        for i in range(0, len(pcm), 3200):  # 100 ms chunks
            client.feed(pcm[i:i + 3200])
            # Pace the feed: dumped at once, the server can lag behind the
            # commit and return an empty transcript (empirically).
            time.sleep(0.03)
        client.feed(trailing_silence)
        return client.finalize().strip()
    finally:
        client.close()


_PUNCT = str.maketrans("", "", ",.!?:;«»\"'()—–")


def tokens(text: str) -> list[str]:
    return [t for t in text.lower().translate(_PUNCT).split() if t]


def close(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def extract_variant(transcript: str, pre: list[str], post: list[str]) -> str:
    """Strip the known carrier words; the middle is the term's observed form."""
    toks = tokens(transcript)
    while toks and any(close(toks[0], p) for p in pre):
        toks.pop(0)
    while toks and any(close(toks[-1], p) for p in post):
        toks.pop()
    return " ".join(toks)


def main() -> int:
    port = find_server_port()
    if port is None:
        print("No nemo-speech server found — launch the Listen app first.")
        return 2

    samples: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "utt.wav"
        for term in TERMS:
            for sentence, pre, post in CARRIERS:
                for voice in VOICES:
                    synth(sentence.format(t=term), voice, wav)
                    text = transcribe(port, pcm_of(wav))
                    variant = extract_variant(text, pre, post)
                    samples.append({
                        "term": term, "voice": voice.split(" ")[0],
                        "carrier": sentence, "transcript": text,
                        "variant": variant,
                    })
                    print(f"[{term}] {voice}: {text!r}  ->  {variant!r}")

    # Aggregate: term -> distinct observed mis-forms (drop empty extractions).
    by_term: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        by_term[s["term"]].append(s)

    pairs = []
    print("\n=== Correction pairs ===")
    for term, rows in by_term.items():
        variants = sorted({s["variant"] for s in rows if s["variant"]})
        pairs.append({"term": term, "variants": variants})
        print(f"{term!r}: {[v for v in variants]}")
        for s in rows:
            note = "" if s["variant"] else "   (extraction failed — eyeball)"
            print(f"    {s['voice']:<8} {s['transcript']!r}{note}")

    out = Path(__file__).parent / "pilot-out"
    out.mkdir(exist_ok=True)
    report = out / "corrections-pilot.json"
    report.write_text(json.dumps(
        {"meta": {"language": None, "endpointing_ms": config.ENDPOINTING_MS},
         "pairs": pairs, "samples": samples},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    print(f"\nwrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
