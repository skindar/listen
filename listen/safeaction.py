"""A decorator for ObjC-exposed selectors that logs and swallows exceptions.

A Python exception escaping an ObjC-invoked method becomes an uncaught ObjC
exception → the macOS "unexpectedly quit" alert → abort (see STABILITY.md).
The uniform "log + return None" actions use this; selectors whose failure
needs user-visible recovery (an alert, a state change, a super-call) keep
their own try/except.

Verified to preserve PyObjC selector registration: a @functools.wraps-wrapped
method is registered by PyObjC with the same ObjC type signature as the plain
method (it reads the original signature via __wrapped__), so the 1-argument
selector argcount is retained.
"""
from __future__ import annotations

import functools
import logging

log = logging.getLogger("listen")


def safe_action(what: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except Exception:
                log.exception("%s failed (recovered)", what)

        return wrapper

    return deco