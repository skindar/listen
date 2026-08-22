"""Entry point: `python -m listen` (run app) or `python -m listen pull` (download model)."""
from __future__ import annotations

import fcntl
import logging
import signal
import sys
import threading

from . import config


def _acquire_singleton_lock():
    """One app instance at a time. flock dies with the process — even SIGKILL."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(config.APP_LOCK, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        print("Listen is already running.", file=sys.stderr)
        sys.exit(0)
    return f


def pull() -> int:
    """Download the ASR model to ~/.listen/models (CLI, with progress)."""
    from . import model

    def progress(downloaded: int, total: int | None) -> None:
        if total:
            mb = downloaded / (1 << 20)
            tot = total / (1 << 20)
            sys.stdout.write(f"\r{mb:.0f} / {tot:.0f} MB ({downloaded * 100 // total}%)")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\r{downloaded / (1 << 20):.0f} MB")
            sys.stdout.flush()

    print(f"Downloading {config.MODEL_FILENAME} into {config.MODEL_DIR}…")
    model.download(progress=progress)
    print()
    return 0


def _install_excepthooks() -> None:
    """Log uncaught exceptions instead of letting them abort the process.

    A Python exception escaping an ObjC entry point becomes an uncaught ObjC
    exception → the macOS "unexpectedly quit" alert → abort. Logging worker-
    thread exceptions (via threading.excepthook) makes silent thread deaths
    visible, and the main excepthook is a last-resort record for anything that
    slips past the run loop's own try/except.
    """
    log = logging.getLogger("listen")

    def _thread(args) -> None:
        log.error(
            "uncaught exception in thread %r: %s",
            getattr(args.thread, "name", "?"), args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    def _main(etype, value, tb) -> None:
        log.error("uncaught exception: %s", value, exc_info=(etype, value, tb))

    threading.excepthook = _thread
    sys.excepthook = _main


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=str(config.LOG_PATH),
    )
    _install_excepthooks()

    if len(sys.argv) > 1 and sys.argv[1] == "pull":
        sys.exit(pull())

    lock = _acquire_singleton_lock()  # noqa: F841 — held until the app exits

    # A LaunchAgent left by a dev copy (`python -m listen`) would keep
    # launching the dev interpreter at login; from the bundled app, drop it.
    from . import autostart

    autostart.remove_stale_agent()

    # One-time: download the model if it's missing (verified via sha256).
    # After this, fully offline. Accessibility is NOT requested up front: the
    # app idles with a ⚠ and picks the permission up the moment it is granted
    # (app._poll_accessibility); the microphone prompt appears naturally on
    # the first recording.
    from . import firstrun

    if not firstrun.run_download():
        if config.resolve_model_path() is None:
            print("Model is required to run Listen. Re-launch to download again.", file=sys.stderr)
            sys.exit(1)

    from .app import App

    app = App.alloc().init()

    def _shutdown(signum, frame):
        sys.exit(0)  # atexit stops the server

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        app.run()
    except SystemExit:
        raise
    except Exception:
        logging.getLogger("listen").exception("fatal error in app.run — exiting cleanly")
        sys.exit(1)


if __name__ == "__main__":
    main()
