import argparse
import hashlib
import os
import zipfile

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from payload_dumper.dumper import Dumper


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("out")
    parser.add_argument("partitions", nargs="+")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    requested = set(args.partitions)
    with zipfile.ZipFile(args.archive) as archive:
        with archive.open("payload.bin") as payload:
            dumper = Dumper(payload, out=args.out, workers=1)
            parts = [p for p in dumper.dam.partitions if p.partition_name in requested]
            missing = requested - {p.partition_name for p in parts}
            if missing:
                raise SystemExit(f"Partitions not found: {', '.join(sorted(missing))}")

            for part in parts:
                output = os.path.join(args.out, f"{part.partition_name}.img")
                print(f"extracting {part.partition_name} ({part.new_partition_info.size} bytes)")
                with open(output, "wb") as out:
                    for index, operation in enumerate(part.operations, 1):
                        payload.seek(dumper.data_offset + operation.data_offset)
                        data = payload.read(operation.data_length)
                        if len(data) != operation.data_length:
                            raise IOError(f"Short payload read for {part.partition_name} op {index}")
                        dumper.data_for_op(
                            {"operation": operation, "data": data}, out, old_file=None
                        )
                    out.truncate(part.new_partition_info.size)
                actual = file_sha256(output)
                expected = bytes(part.new_partition_info.hash).hex()
                if actual != expected:
                    raise ValueError(
                        f"Hash mismatch for {part.partition_name}: {actual} != {expected}"
                    )
                print(f"verified {part.partition_name}: {actual}")


if __name__ == "__main__":
    main()
