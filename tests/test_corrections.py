"""Corrections dictionary: matching rules, persistence, cleaning."""
from __future__ import annotations

import json

import pytest

from listen.corrections import Corrections, merge_into, parse_pairs_text


def _pairs(**kw):
    return [{"from": f, "to": t} for f, t in kw.items()]


# -- matching -------------------------------------------------------------------


def test_no_file_starts_empty(tmp_path):
    """A fresh install shows NOTHING by default — the user's dictionary is
    theirs alone (import brings one in)."""
    c = Corrections(tmp_path / "c.json")
    assert c.pairs == []
    assert c.apply("термин бреукас важен") == "термин бреукас важен"


# -- import/export helpers --------------------------------------------------------


def test_parse_pairs_text_export_format():
    rows = parse_pairs_text(json.dumps({"pairs": [{"from": "а", "to": "A"}]}))
    assert rows == [{"from": "а", "to": "A"}]


def test_parse_pairs_text_bare_list():
    rows = parse_pairs_text('[{"from": "а", "to": "A"}, {"from": "б"}]')
    assert rows == [{"from": "а", "to": "A"}, {"from": "б", "to": ""}]


def test_parse_pairs_text_skips_junk():
    rows = parse_pairs_text(
        '[{"from": "", "to": "x"}, "nonsense", {"to": "y"}, {"from": "а"}]'
    )
    assert rows == [{"from": "а", "to": ""}]


def test_parse_pairs_text_malformed_raises():
    with pytest.raises(ValueError):
        parse_pairs_text('{"rules": []}')
    with pytest.raises(json.JSONDecodeError):
        parse_pairs_text("not json")


def test_merge_into_updates_in_place_and_appends():
    rows = [{"from": "а", "to": "A"}, {"from": "б", "to": "B"}]
    merged, n_up, n_add = merge_into(
        rows, [{"from": "А", "to": "A2"}, {"from": "в", "to": "V"}]
    )
    assert merged == [
        {"from": "а", "to": "A2"},
        {"from": "б", "to": "B"},
        {"from": "в", "to": "V"},
    ]
    assert (n_up, n_add) == (1, 1)
    assert rows == [{"from": "а", "to": "A"}, {"from": "б", "to": "B"}]  # pure


def test_merge_into_dedupe_within_incoming():
    merged, n_up, n_add = merge_into(
        [], [{"from": "а", "to": "1"}, {"from": "А", "to": "2"}]
    )
    assert merged == [{"from": "а", "to": "2"}]  # later line wins
    assert (n_up, n_add) == (1, 1)  # first appends, the duplicate updates it


def test_identity_without_pairs(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs([])
    assert c.apply("просто текст") == "просто текст"
    assert c.apply("") == ""


def test_word_boundaries(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs(_pairs(докер="Docker"))
    assert c.apply("докер") == "Docker"
    assert c.apply("Докер стоит") == "Docker стоит"  # case-insensitive from
    assert c.apply("докеров было много") == "докеров было много"  # no substring
    assert c.apply("докер, докер.") == "Docker, Docker."  # punctuation bounds


def test_multiword_phrase(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs(_pairs(**{"брук эской": "brew cask"}))
    assert c.apply("сделай брук эской и запусти") == "сделай brew cask и запусти"


def test_longest_pattern_wins(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs([{"from": "брук", "to": "brew"},
                 {"from": "брук эской", "to": "brew cask"}])
    assert c.apply("брук эской") == "brew cask"
    assert c.apply("брук") == "brew"


def test_no_chained_replacement(tmp_path):
    # A rule's output must not feed another rule's input.
    c = Corrections(tmp_path / "c.json")
    c.set_pairs([{"from": "а", "to": "б в"},
                 {"from": "б в", "to": "X"}])
    assert c.apply("а") == "б в"


def test_empty_to_deletes_word(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs(_pairs(эээ=""))
    assert c.apply("ну эээ да") == "ну  да"


def test_latin_and_mixed_scripts(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs(_pairs(kubectl="кубектл"))
    assert c.apply("запусти kubectl") == "запусти кубектл"


# -- persistence / cleaning -------------------------------------------------------


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    c = Corrections(path)
    c.set_pairs(_pairs(бреукас="brew cask"))
    again = Corrections(path)
    assert again.pairs == [{"from": "бреукас", "to": "brew cask"}]
    assert again.apply("бреукас") == "brew cask"


def test_set_pairs_strips_dedupes_drops_empty_from(tmp_path):
    c = Corrections(tmp_path / "c.json")
    c.set_pairs([
        {"from": "  бреукас ", "to": " brew cask "},
        {"from": "БРЕУКАС", "to": "other"},   # duplicate (case-insensitive)
        {"from": "", "to": "x"},              # no 'from' — dropped
        {"to": "y"},                          # no 'from' — dropped
    ])
    assert c.pairs == [{"from": "бреукас", "to": "brew cask"}]


def test_malformed_file_starts_empty(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ not json", encoding="utf-8")
    c = Corrections(path)
    assert c.pairs == []
    assert c.apply("текст") == "текст"


def test_non_dict_entries_dropped(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"pairs": [None, 5, {"from": "гитхаб", "to": "GitHub"}]}),
                    encoding="utf-8")
    c = Corrections(path)
    assert c.pairs == [{"from": "гитхаб", "to": "GitHub"}]


def test_saved_file_is_human_readable_unicode(tmp_path):
    path = tmp_path / "c.json"
    Corrections(path).set_pairs(_pairs(бреукас="brew cask"))
    raw = path.read_text(encoding="utf-8")
    assert "бреукас" in raw  # not \u-escaped
