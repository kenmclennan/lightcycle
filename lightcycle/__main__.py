import os
import sys

from lightcycle.cli import main

if __name__ == "__main__":
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (ValueError, OSError):
        pass
    os._exit(_rc if isinstance(_rc, int) else 0)
