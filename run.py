"""Thin launcher so py2app has a script entry point (`python -m listen` in dev)."""
from listen.__main__ import main

if __name__ == "__main__":
    main()