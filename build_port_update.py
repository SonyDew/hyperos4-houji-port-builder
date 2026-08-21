#!/usr/bin/env python3
"""Compatibility entry point for update-only builds."""

import sys

from build_port import main


if __name__ == "__main__":
    if "--package" not in sys.argv:
        sys.argv.extend(("--package", "update"))
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"ERROR: {error}", flush=True)
        raise SystemExit(1)
