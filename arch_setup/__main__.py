"""Module entry point for `python3 -m arch_setup`."""

import sys

from arch_setup.main import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
