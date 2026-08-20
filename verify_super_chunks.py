#!/usr/bin/env python3
import argparse
import hashlib
import re
import zipfile
from pathlib import Path


def entry_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare super chunks in two update ZIPs")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    with zipfile.ZipFile(args.reference) as reference, zipfile.ZipFile(args.candidate) as candidate:
        names = sorted(
            (name for name in reference.namelist() if re.fullmatch(r"images/super\.img\.\d+", name)),
            key=lambda name: int(name.rsplit(".", 1)[1]),
        )
        candidate_names = {
            name for name in candidate.namelist() if re.fullmatch(r"images/super\.img\.\d+", name)
        }
        if set(names) != candidate_names:
            raise SystemExit("The ZIPs contain different super chunk lists")
        all_equal = True
        for name in names:
            reference_hash = entry_sha256(reference, name)
            candidate_hash = entry_sha256(candidate, name)
            equal = reference_hash == candidate_hash
            all_equal &= equal
            print(f"{name} {candidate_hash} equal={str(equal).lower()}")
        print(f"all_sha256_identical={str(all_equal).lower()}")
        if not all_equal:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
