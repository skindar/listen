"""py2app build script for a self-contained Listen.app bundle.

Build:  .venv/bin/python setup_app.py py2app
Output: dist/Listen.app
"""
from __future__ import annotations

import os
from pathlib import Path

from setuptools import setup

from listen import config

# Ship the bundled nemo-speech binary + dylibs into Contents/Resources/nemo-speech/
NEMO_DIR = Path(__file__).parent / "listen" / "resources" / "nemo-speech"

PLIST = {
    "CFBundleName": "Listen",
    "CFBundleDisplayName": "Listen",
    "CFBundleIdentifier": "com.valentyn.listen",
    "CFBundleExecutable": "run",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": config.APP_VERSION,
    "CFBundleVersion": config.APP_VERSION,
    "LSUIElement": True,  # menu-bar-only, no Dock icon
    "LSMinimumSystemVersion": "13.0",
    "NSMicrophoneUsageDescription": "Listen records the microphone to transcribe speech to text.",
    "NSHighResolutionCapable": True,
}

setup(
    app=["run.py"],
    name="Listen",
    options={
        "py2app": {
            "plist": PLIST,
            "resources": [str(NEMO_DIR)],
            "includes": [
                "AppKit",
                "Quartz",
                "ApplicationServices",
                "CoreFoundation",
                "Foundation",
            ],
            # Copy these as real directories (not into the zip) so their bundled
            # data/dylibs (PortAudio) load at runtime.
            "packages": ["sounddevice", "_sounddevice_data", "numpy"],
            "excludes": [
                "PyObjCTest",
                "pip",
                "setuptools",
                "distutils",
                "huggingface_hub",
                "requests",
                "urllib3",
                "certifi",
                "tqdm",
                "pytest",
                "unittest",
            ],
            "argv_emulation": False,
            "strip": True,
            "iconfile": str(Path(__file__).parent / "assets" / "Listen.icns"),
        }
    },
    setup_requires=["py2app"],
)