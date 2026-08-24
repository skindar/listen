"""Auto-start at login via a user LaunchAgent, toggled from the menu bar.

The checkbox must reflect *this* executable: an agent left over from a dev
copy (`python -m listen`) would otherwise both show as checked in a freshly
installed app and keep launching the dev interpreter at login.
`remove_stale_agent` (called at startup from the bundled app) deletes such a
leftover; the user re-enables Start at Login once, for this app.
"""
from __future__ import annotations

import functools
import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("listen")

AGENT_LABEL = "com.valentyn.listen"
AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
AGENT_LOG = Path.home() / "Library" / "Logs" / "listen-agent.log"


@functools.lru_cache(maxsize=1)
def _app_executable() -> str:
    """The executable to launch at login: the running .app bundle if any, else
    fall back to the python -m invocation used in dev. Fixed for the process
    lifetime, so memoized."""
    exe = Path(sys.executable)
    # Inside our py2app bundle: .../listen.app/Contents/MacOS/python
    # (sys.executable is the embedded interpreter). Launch the bundle stub
    # (CFBundleExecutable) — not the interpreter — so the app starts the way
    # Finder would start it.
    if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents" \
            and exe.parent.parent.parent.name.endswith(".app"):
        stub = exe.parent / "run"
        return str(stub if stub.is_file() else exe)
    # Dev: re-run via the venv python module.
    return f"{exe} -m listen"


def _in_bundle() -> bool:
    """True inside the py2app bundle (i.e. not a `python -m listen` dev run)."""
    return " -m listen" not in _app_executable()


def _uid() -> str:
    return str(os.getuid())


def _bootstrapped() -> bool:
    r = subprocess.run(
        ["launchctl", "print", f"gui/{_uid()}/{AGENT_LABEL}"], capture_output=True
    )
    return r.returncode == 0


def _plist_program() -> str | None:
    """The program the on-disk agent would run, joined into one string."""
    try:
        with open(AGENT_PLIST, "rb") as f:
            data = plistlib.load(f)
        return " ".join(str(a) for a in data.get("ProgramArguments") or [])
    except Exception:
        return None


def _launches_current(program: str | None) -> bool:
    return program is not None and _app_executable() in program


# is_on() only changes through this module's enable()/disable(), so cache it
# and invalidate there — avoids a launchctl subprocess + plist read per menu open.
_is_on_cache: bool | None = None


def _invalidate_cache() -> None:
    global _is_on_cache
    _is_on_cache = None


def is_on() -> bool:
    """True only when the agent is loaded AND launches this executable."""
    global _is_on_cache
    if _is_on_cache is None:
        _is_on_cache = _bootstrapped() and _launches_current(_plist_program())
    return _is_on_cache


def remove_stale_agent() -> None:
    """From the bundled app: delete an agent that launches a different copy.

    No-op in dev (a dev run must never touch the installed app's agent) and
    when the agent already points here.
    """
    if not _in_bundle() or not _bootstrapped():
        return
    program = _plist_program()
    if _launches_current(program):
        return
    log.info("removing stale LaunchAgent that launched %r", program)
    disable()


def _program_arguments() -> list[str]:
    """ProgramArguments for the agent plist: split the dev `python -m listen`
    form into argv, keep the bundle form as a single binary path."""
    exe = _app_executable()
    if " -m listen" in exe:
        prog, rest = exe.split(" -m ", 1)
        return [prog, "-m", rest]
    return [exe]


def _plist() -> bytes:
    return plistlib.dumps(
        {
            "Label": AGENT_LABEL,
            "ProgramArguments": _program_arguments(),
            "RunAtLoad": True,
            "StandardOutPath": str(AGENT_LOG),
            "StandardErrorPath": str(AGENT_LOG),
        },
        fmt=plistlib.FMT_XML,
    )


def _bootstrap() -> None:
    AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    AGENT_PLIST.write_bytes(_plist())
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(AGENT_PLIST)],
        capture_output=True,
    )


def enable() -> None:
    # bootout first: bootstrapping into an occupied label keeps the OLD program.
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{AGENT_LABEL}"], capture_output=True
    )
    _bootstrap()
    subprocess.run(
        ["launchctl", "kickstart", f"gui/{_uid()}/{AGENT_LABEL}"], capture_output=True
    )
    _invalidate_cache()


def disable() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{AGENT_LABEL}"], capture_output=True
    )
    AGENT_PLIST.unlink(missing_ok=True)
    _invalidate_cache()
