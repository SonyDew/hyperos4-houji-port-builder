#!/usr/bin/env python3
"""Stop firmware archives and other large files from reaching Git."""

from __future__ import annotations

import subprocess
from pathlib import Path


LIMIT = 5 * 1024 * 1024
FORBIDDEN = {
    ".zip",
    ".img",
    ".bin",
    ".br",
    ".7z",
    ".rar",
    ".tar",
    ".tgz",
}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / name.decode("utf-8") for name in result.stdout.split(b"\0") if name]


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    problems: list[str] = []
    for path in tracked_files(root):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in FORBIDDEN or path.name.lower().endswith(".new.dat"):
            problems.append(f"firmware file is tracked: {relative}")
        if path.stat().st_size > LIMIT:
            problems.append(f"file is larger than 5 MiB: {relative}")

    if problems:
        raise SystemExit("Repository size check failed:\n- " + "\n- ".join(problems))
    print("Repository size check passed")


if __name__ == "__main__":
    main()
