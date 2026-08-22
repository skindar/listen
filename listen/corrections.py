"""User-editable auto-replace dictionary: ~/.listen/corrections.json.

Pairs {"from": "бреукас", "to": "brew cask"} applied to every transcript just
before it is pasted — the model's Cyrillic renderings of foreign terms are
restored to the intended spelling. This is the manual "fine-tuning" surface:
what the user fixes once is fixed forever.

Matching rules:
    - whole words/phrases only (unicode-aware boundaries — no substring hits
      inside a longer word), case-insensitive on the "from" side;
    - longer patterns win ("брук эской" before "брук");
    - all pairs apply in a single regex pass, so one rule's output can never
      feed another rule's input;
    - an empty "to" deletes the word (filler-word removal).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from . import config

log = logging.getLogger("listen")

# Shown the first time the window opens (file absent) so the list is never an
# empty mystery. Deleting a row writes the file — the seed never returns.
SEED_PAIRS = [
    {"from": "бреукас", "to": "brew cask"},
    {"from": "гитхаб", "to": "GitHub"},
]


class Corrections:
    """The pair list + the compiled matcher. Reads are lock-free: the editor
    swaps in a new compiled pattern atomically, so a paste mid-edit uses
    either the old or the new rules — never a torn mix."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config.DATA_DIR / "corrections.json"
        self._pairs: list[dict] = []
        self._regex: re.Pattern | None = None
        self._by_lower: dict[str, str] = {}
        self.load()

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Read the dictionary; any problem falls back to empty (never raises)."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if not isinstance(pairs, list):
                raise ValueError("expected {'pairs': [...]}")
        except FileNotFoundError:
            self._set(SEED_PAIRS)  # in-memory only — saved on the first edit
            return
        except Exception:
            log.exception("corrections unreadable, starting empty: %s", self._path)
            self._set([])
            return
        self._set([p for p in pairs if isinstance(p, dict)])

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"pairs": self._pairs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)  # atomic on the same directory
        except Exception:
            log.exception("failed to save corrections to %s", self._path)

    # -- the pair list ---------------------------------------------------------

    @property
    def pairs(self) -> list[dict]:
        return self._pairs

    def set_pairs(self, rows: list[dict]) -> None:
        """Clean + persist the editor's rows. Empty 'from' rows are kept out
        of the matcher (the editor may still show them mid-editing)."""
        self._set(rows)
        self.save()

    def _set(self, rows: list[dict]) -> None:
        cleaned: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            src = str(row.get("from", "")).strip()
            dst = str(row.get("to", "")).strip()
            if not src or src.lower() in seen:
                continue
            seen.add(src.lower())
            cleaned.append({"from": src, "to": dst})
        self._pairs = cleaned
        if cleaned:
            froms = sorted((p["from"] for p in cleaned), key=len, reverse=True)
            self._by_lower = {p["from"].lower(): p["to"] for p in cleaned}
            self._regex = re.compile(
                r"(?<!\w)(" + "|".join(re.escape(f) for f in froms) + r")(?!\w)",
                re.IGNORECASE,
            )
        else:
            self._by_lower = {}
            self._regex = None

    # -- the matcher -----------------------------------------------------------

    def apply(self, text: str) -> str:
        if not text or self._regex is None:
            return text
        return self._regex.sub(
            lambda m: self._by_lower.get(m.group(0).lower(), m.group(0)), text
        )
