"""Module entry point for `python3 -m arch_setup.backend.privileged`."""

import sys
from arch_setup.backend.privileged import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
