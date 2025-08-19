#!/usr/bin/env python3
"""Convenience launcher to run the `craigify` package as a script.

Usage:
  ./craigify.py [args...]

This mirrors `python3 -m craigify` while keeping a single-file entrypoint in the repo root.
"""

import runpy

if __name__ == "__main__":
    # Run the package as a module so `craigify.__main__` (or package entry) executes
    # sys.argv is preserved so subcommands/argparse in the package will see the args.
    runpy.run_module("craigify", run_name="__main__", alter_sys=True)
