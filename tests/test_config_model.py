"""Config/model resolution and the language catalogue."""
from listen import config
from listen import languages


def test_resolve_model_path_finds_gguf(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "m.q8_0.gguf"
    f.write_bytes(b"x")
    assert config.resolve_model_path() == f


def test_resolve_model_path_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    assert config.resolve_model_path() is None


def test_languages_catalogue():
    codes = [c for c, _ in languages.READY]
    assert len(codes) == 19  # transcription-ready locales
    assert len(set(codes)) == len(codes)
    assert all(len(c) == 5 and c[2] == "-" for c in codes)
    assert languages.is_supported("ru-RU")
    assert not languages.is_supported("xx-XX")
    assert not languages.is_supported("bg-BG")  # broad-coverage group removed
    assert languages.label(None) == "Auto"
    assert languages.label("ru-RU") == "Russian"
