# listen

**Free, offline speech-to-text. **

Press a key. Talk. Text appears at your cursor. That is the whole app.

Listen runs entirely on your Mac — no cloud, no account, no telemetry, no
subscription. A speech model is downloaded once and lives on your disk.

## The promise

- **Free, forever.** No paywall, no "pro" tier, no future bait-and-switch.
- **Offline.** Audio never leaves your machine.
- **One job.** Recognize speech and type it. Two settings, zero windows.
- **Yours.** Open source (MIT). A few hundred lines of Python you can read in one sitting.

## Use

1. Press **right Option** — the menu-bar mic turns into a red dot (recording).
2. Speak.
3. Press **right Option** again — text is typed into whatever field is focused.

The language is detected automatically (40 locales). Clicking the menu-bar icon opens the whole UI: change the hotkey,
pin the language (32 locales), or toggle Start at Login.

## Install

Download DMG file via github release

```bash
git clone https://github.com/valentyn/listen && cd listen
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m listen          # first run downloads the model (707 MB, one-time)
.venv/bin/python setup_app.py py2app  # build dist/Listen.app
```

On first launch macOS asks for **Accessibility** (so the hotkey + paste work)
and **Microphone** — grant them once. Listen waits politely (⚠ icon + a menu
link to the right settings pane) and picks a grant up the moment you give it,
no restart. A monochrome mic icon appears in the menu bar. That's it.

## Why

On-device speech recognition is a solved, open problem — the models are free
and run fast on Apple Silicon. There is no honest reason to charge a
subscription for it. Listen exists because dictation should be a quiet utility
that belongs to you, not a recurring bill.

## How it works

- **Model:** [`nvidia/nemotron-3.5-asr-streaming-0.6b`](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
  — 600M params, native streaming, 40 language-locales, auto-detected.
- **Engine:** [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) (C++,
  Metal) bundled inside the app.
- **App:** Python + PyObjC, menu-bar-only (`LSUIElement`), packaged with py2app.

```
listen/
├── listen/
│   ├── __main__.py    # entry: single-instance lock, first-run download, run
│   ├── app.py         # the App: state machine + record→transcribe→paste
│   ├── state.py       # AppState enum — the single source of truth
│   ├── icons.py       # menu-bar icon rendering + recording pulse
│   ├── menu.py        # the entire UI: hotkey / language / autostart / quit
│   ├── settings.py    # ~/.listen/settings.json (hotkey, language)
│   ├── permissions.py # Accessibility + Microphone (queries, settings links)
│   ├── firstrun.py    # the one-time model-download window (the only window)
│   ├── server.py      # nemo-speech serve subprocess (ephemeral loopback port)
│   ├── model.py       # one-time streaming model download + sha256 verify
│   ├── hotkey.py      # CGEventTap hotkey (pure, testable decision logic)
│   ├── audio.py       # sounddevice (16 kHz mono, in-memory WAV)
│   ├── paste.py       # clipboard + Cmd+V, then careful restore
│   ├── autostart.py   # optional Start at Login (LaunchAgent)
│   ├── languages.py   # the 32 supported transcription locales
│   ├── config.py      # constants + resource/model resolution
│   └── resources/nemo-speech/   # bundled C++ runtime + Metal libs
├── tests/             # pytest suite for the pure logic
├── run.py             # thin launcher for py2app
├── setup_app.py       # py2app build
└── requirements.txt
```

The local server binds a fresh ephemeral `127.0.0.1` port at every start, so
Listen never collides with whatever else you run on 8080. Run the tests with
`.venv/bin/python -m pytest tests`.

## License

MIT. The model is governed by NVIDIA's OpenMDW-1.1 license.
