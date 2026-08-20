#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path


AUTOMATION = Path(__file__).resolve().parent
CONFIG_PATH = AUTOMATION / "config.example.json"
LOCAL_CONFIG_PATH = AUTOMATION / "config.local.json"
MANIFEST_PATH = AUTOMATION / "patch_manifest.json"
PATCHES = AUTOMATION / "patches"
BASE_DYNAMIC = AUTOMATION / "base_dynamic"
TOOLS = AUTOMATION / "tools"
EROFS = TOOLS / "erofs-utils"
EXTRACT_EROFS = EROFS / "extract.erofs.exe"
MKFS_EROFS = EROFS / "mkfs.erofs.exe"
PAYLOAD_EXTRACTOR = AUTOMATION / "scripts" / "extract_payload_zip_sequential.py"
LPMAKE = TOOLS / "android-tools-static" / "android-tools-static" / "lpmake"

DONOR_PARTITIONS = ("system", "system_ext", "product", "mi_ext")
BASE_PARTITIONS = {
    "odm": "odm_a.img",
    "system_dlkm": "system_dlkm_a.img",
    "vendor": "vendor_a.img",
    "vendor_dlkm": "vendor_dlkm_a.img",
}
DERIVED_SUFFIXES = (".art", ".odex", ".vdex", ".oat", ".prof", ".fsv_meta")
PRODUCT_PRUNE = (
    "app/CameraTools_beta",
    "data-app/MIGalleryLockscreen",
    "data-app/MIUICalculator",
    "data-app/MIUICompass",
    "data-app/MIUIHuanji",
    "data-app/MIUIVirtualSim",
    "data-app/XMRemoteController",
    "data-app/wps-lite",
    "media/wallpaper",
    "etc/device_features/pudding.xml",
)


def log(message: str) -> None:
    print(message, flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def load_config() -> dict:
    config = load_json(CONFIG_PATH)
    if LOCAL_CONFIG_PATH.is_file():
        config.update(load_json(LOCAL_CONFIG_PATH))
    return config


def resolve_from(base: Path, supplied: str) -> Path:
    path = Path(supplied)
    return (path if path.is_absolute() else base / path).resolve()


def safe_remove_tree(path: Path, allowed_parent: Path) -> None:
    target = path.resolve()
    parent = allowed_parent.resolve()
    if target == parent or os.path.commonpath((str(parent), str(target))) != str(parent):
        raise RuntimeError(f"Refusing unsafe cleanup target: {target}")
    if target.exists():
        shutil.rmtree(target)


def run(command: list[str], cwd: Path | None = None) -> None:
    display = subprocess.list2cmdline(command)
    log(f"RUN: {display}")
    subprocess.run(command, cwd=cwd, check=True)


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise RuntimeError(f"Expected a Windows drive path: {resolved}")
    tail = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{tail}"


def read_ota_metadata(archive_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if "payload.bin" not in names:
            raise RuntimeError("The donor archive has no payload.bin; a full official OTA is required")
        try:
            raw = archive.read("META-INF/com/android/metadata").decode("utf-8", "replace")
        except KeyError as error:
            raise RuntimeError("The donor archive has no Android OTA metadata") from error
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def donor_version(metadata: dict[str, str], archive_path: Path) -> str:
    public_version = re.search(r"OS\d+\.\d+\.\d+\.\d+\.[A-Z]{4,}[A-Z0-9]*", archive_path.name)
    if public_version:
        return public_version.group(0)
    for key in ("post-build-incremental", "post-build"):
        match = re.search(r"OS\d+(?:\.\d+)+\.[A-Z0-9]+", metadata.get(key, ""))
        if match:
            return match.group(0)
    raise RuntimeError("Could not determine the donor HyperOS version from OTA metadata")


def choose_donor(config: dict, supplied: str | None) -> Path:
    if supplied:
        donor = resolve_from(Path.cwd(), supplied)
        if not donor.is_file():
            raise RuntimeError(f"Donor OTA not found: {donor}")
        return donor
    input_dir = resolve_from(AUTOMATION, config["input_directory"])
    input_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(input_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise RuntimeError(
            f"Put one new pudding full OTA ZIP in {input_dir}, or drag a ZIP onto BUILD_UPDATE.bat"
        )
    if len(candidates) > 1:
        names = ", ".join(item.name for item in candidates)
        raise RuntimeError(f"More than one donor ZIP found in {input_dir}: {names}")
    return candidates[0].resolve()


def validate_inputs(config: dict, manifest: dict, donor: Path, baseline: Path) -> tuple[dict[str, str], str]:
    required = (EXTRACT_EROFS, MKFS_EROFS, PAYLOAD_EXTRACTOR, LPMAKE, baseline)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Some local files are missing:\n"
            + "\n".join(missing)
            + "\nSee the Local files section in README.md."
        )
    for relative, expected in manifest["patched_hashes"].items():
        path = PATCHES / Path(relative)
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Patch artifact is missing or damaged: {path}")
    for name, expected in manifest["base_dynamic_hashes"].items():
        path = BASE_DYNAMIC / name
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Base dynamic image is missing or damaged: {path}")

    metadata = read_ota_metadata(donor)
    expected_device = config["expected_donor_device"]
    pre_device = metadata.get("pre-device", "")
    if expected_device not in pre_device.split(","):
        raise RuntimeError(f"Wrong donor device: expected {expected_device}, metadata says {pre_device!r}")
    sdk = metadata.get("post-sdk-level", "")
    if sdk and sdk != str(config["expected_sdk"]):
        raise RuntimeError(f"Unsupported donor SDK {sdk}; expected {config['expected_sdk']}")
    if metadata.get("ota-type") not in (None, "AB"):
        raise RuntimeError(f"Unsupported donor OTA type: {metadata.get('ota-type')}")
    return metadata, donor_version(metadata, donor)


def check_free_space(config: dict, path: Path) -> None:
    free = shutil.disk_usage(path).free
    required = int(config["minimum_free_space_gib"]) * 1024**3
    if free < required:
        raise RuntimeError(
            f"Not enough free space: {free / 1024**3:.1f} GiB available, "
            f"at least {required / 1024**3:.0f} GiB required"
        )


def extract_payload(donor: Path, images: Path) -> None:
    command = [sys.executable, str(PAYLOAD_EXTRACTOR), str(donor), str(images), *DONOR_PARTITIONS]
    for attempt in (1, 2):
        if images.exists():
            shutil.rmtree(images)
        images.mkdir(parents=True)
        try:
            run(command)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            log("Payload extraction hash check failed; deleting the partial images and retrying once")


def extract_erofs(images: Path, trees: Path) -> None:
    trees.mkdir(parents=True)
    for partition in DONOR_PARTITIONS:
        run(
            [
                str(EXTRACT_EROFS),
                "-i",
                str(images / f"{partition}.img"),
                "-x",
                "-o",
                str(trees),
                "-f",
                "-s",
                "-T8",
            ]
        )
        if not (trees / partition).is_dir():
            raise RuntimeError(f"EROFS extractor did not create the expected tree: {trees / partition}")


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def prune_generated(root: Path) -> tuple[int, int]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and ("oat" in path.relative_to(root).parts or path.name.endswith(DERIVED_SUFFIXES))
    ]
    count = len(files)
    size = sum(path.stat().st_size for path in files)
    for path in files:
        path.unlink()
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    return count, size


def remove_path(path: Path, root: Path) -> None:
    target = path.resolve()
    resolved_root = root.resolve()
    if target == resolved_root or os.path.commonpath((str(resolved_root), str(target))) != str(resolved_root):
        raise RuntimeError(f"Unsafe prune path: {target}")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()


def ensure_config_entry(config_path: Path, entry: str) -> None:
    text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    key = entry.split(" ", 1)[0]
    if not any(line.split(" ", 1)[0] == key for line in text.splitlines() if line):
        with config_path.open("a", encoding="utf-8", newline="\n") as stream:
            if text and not text.endswith("\n"):
                stream.write("\n")
            stream.write(entry + "\n")


def apply_port_patch(trees: Path, manifest: dict, version: str, config: dict) -> list[str]:
    warnings: list[str] = []
    original_hashes = manifest["original_donor_hashes"]
    for relative, baseline_hash in original_hashes.items():
        source = trees / Path(relative)
        if not source.is_file():
            raise RuntimeError(f"Required donor file moved or disappeared: {relative}")
        current_hash = sha256(source)
        if current_hash != baseline_hash:
            warnings.append(
                f"Donor file changed since {manifest['baseline_donor']}: {relative}; "
                "the proven v1 patched file was retained"
            )

    system_props_path = trees / "system" / "system" / "build.prop"
    product_props_path = trees / "product" / "etc" / "build.prop"
    mi_ext_props_path = trees / "mi_ext" / "etc" / "build.prop"
    props = read_properties(product_props_path)
    release = props.get("ro.build.version.release")
    sdk = props.get("ro.build.version.sdk")
    if release != str(config["expected_android_release"]) or sdk != str(config["expected_sdk"]):
        raise RuntimeError(
            f"Unsupported donor platform: Android {release}, SDK {sdk}; "
            f"expected Android {config['expected_android_release']}, SDK {config['expected_sdk']}"
        )

    product_text = product_props_path.read_text(encoding="utf-8", errors="strict").replace("pudding", "houji")
    product_updates = {
        "persist.miui.density_v2": "480",
        "ro.sf.lcd_density": "480",
    }
    product_removals = {
        "persist.sys.dexpreload.cpu_cores",
        "persist.sys.dexpreload.big_prime_cores",
        "persist.sys.dexpreload.other_cores",
        "ro.miui.affinity.sfui",
        "ro.miui.affinity.sfre",
        "ro.miui.affinity.sfuireset",
        "persist.sys.miui_animator_sched.bigcores",
        "persist.sys.miui_animator_sched.sched_threads",
        "persist.sys.miui.sf_cores",
        "persist.vendor.display.miui.composer_boost",
        "persist.sys.miui_animator_sched.big_prime_cores",
        "persist.sys.minfree_def",
        "persist.sys.minfree_6g",
        "persist.sys.minfree_8g",
    }
    product_lines: list[str] = []
    for line in product_text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in product_removals:
                continue
            if key in product_updates:
                line = f"{key}={product_updates[key]}"
        product_lines.append(line)
    scheduling_block = [
        "# houji (SM8650) scheduling and memory profile",
        "persist.sys.miui_animator_sched.bigcores=4-7",
        "persist.sys.miui_animator_sched.sched_threads=2",
        "persist.sys.miui.sf_cores=4-7",
        "persist.vendor.display.miui.composer_boost=4-7",
        "persist.sys.miui_animator_sched.big_prime_cores=4-7",
        "persist.sys.minfree_def=73728,92160,110592,154832,482560,579072",
        "persist.sys.minfree_6g=73728,92160,110592,258048,663552,903168",
        "persist.sys.minfree_8g=73728,92160,110592,387072,1105920,1451520",
        "persist.sys.first.frame.accelerates=true",
        "ro.miui.affinity.sfui=4-6",
        "ro.miui.affinity.sfre=4-6",
        "ro.miui.affinity.sfuireset=0-6",
    ]
    product_props_path.write_text(
        "\n".join(product_lines).rstrip("\n") + "\n\n" + "\n".join(scheduling_block) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    mi_ext_text = mi_ext_props_path.read_text(encoding="utf-8", errors="strict")
    mi_ext_text, replacements = re.subn(
        r"(?m)^ro\.product\.mod_device=.*$", "ro.product.mod_device=houji", mi_ext_text
    )
    if replacements != 1:
        raise RuntimeError("Expected exactly one ro.product.mod_device property in mi_ext")
    mi_ext_props_path.write_text(mi_ext_text, encoding="utf-8", newline="\n")

    system_lines = [
        line
        for line in system_props_path.read_text(encoding="utf-8", errors="strict").splitlines()
        if not line.startswith("ro.build.fingerprint=")
        and line != "# Port identity: HyperOS 4 user space on houji Android 14 vendor base"
    ]
    system_block = [
        "# Port identity: HyperOS 4 user space on houji Android 14 vendor base",
        "Xiaomi/houji/houji:14/UKQ1.240624.001/" + version + ":user/release-keys",
    ]
    system_block[1] = "ro.build.fingerprint=" + system_block[1]
    system_props_path.write_text(
        "\n".join(system_lines).rstrip("\n") + "\n\n" + "\n".join(system_block) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    for relative in PRODUCT_PRUNE:
        remove_path(trees / "product" / Path(relative), trees / "product")
    total_count = 0
    total_size = 0
    for partition in DONOR_PARTITIONS:
        count, size = prune_generated(trees / partition)
        total_count += count
        total_size += size
    log(f"Removed {total_count} regenerated ART/OAT/profile files ({total_size / 1024**2:.1f} MiB)")

    for relative in manifest["patched_hashes"]:
        source = PATCHES / Path(relative)
        destination = trees / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # The donor has pudding.xml in its canned fs_config. mkfs.erofs requires an
    # explicit mode for the newly inserted houji.xml, while the existing
    # product file-context regex already supplies the correct SELinux label.
    ensure_config_entry(
        trees / "config" / "product_fs_config",
        "product/etc/device_features/houji.xml 0 0 0644",
    )
    ensure_config_entry(
        trees / "config" / "product_file_contexts",
        r"/product/etc/device_features/houji\.xml u:object_r:system_file:s0",
    )
    return warnings


def read_erofs_uuid(config_file: Path) -> str:
    text = config_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Filesystem UUID:\s*([0-9a-fA-F-]{36})", text)
    if not match:
        raise RuntimeError(f"Could not read EROFS UUID from {config_file}")
    return match.group(1)


def repack_erofs(trees: Path, repacked: Path) -> None:
    repacked.mkdir(parents=True)
    for partition in DONOR_PARTITIONS:
        fs_config = trees / "config" / f"{partition}_fs_config"
        file_contexts = trees / "config" / f"{partition}_file_contexts"
        fs_options = trees / "config" / f"{partition}_fs_options"
        for required in (fs_config, file_contexts, fs_options):
            if not required.is_file():
                raise RuntimeError(f"EROFS extraction config is missing: {required}")
        uuid = read_erofs_uuid(fs_options)
        output = repacked / f"{partition}.img"
        run(
            [
                str(MKFS_EROFS),
                "--quiet",
                "-zlz4hc",
                "-T0",
                "-U",
                uuid,
                f"--mount-point=/{partition}",
                f"--fs-config-file={fs_config}",
                f"--file-contexts={file_contexts}",
                str(output),
                str(trees / partition),
            ]
        )


def build_super(config: dict, repacked: Path, output: Path) -> None:
    group_a = "qti_dynamic_partitions_a"
    group_b = "qti_dynamic_partitions_b"
    command = [
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        wsl_path(LPMAKE),
        "--metadata-size",
        str(config["metadata_size"]),
        "--metadata-slots",
        str(config["metadata_slots"]),
        "--super-name",
        "super",
        "--device",
        f"super:{config['super_size']}",
        "--virtual-ab",
        "--sparse",
        "--group",
        f"{group_a}:{config['super_size']}",
        "--group",
        f"{group_b}:{config['super_size']}",
    ]
    image_map = {
        "mi_ext": repacked / "mi_ext.img",
        "odm": BASE_DYNAMIC / BASE_PARTITIONS["odm"],
        "product": repacked / "product.img",
        "system": repacked / "system.img",
        "system_dlkm": BASE_DYNAMIC / BASE_PARTITIONS["system_dlkm"],
        "system_ext": repacked / "system_ext.img",
        "vendor": BASE_DYNAMIC / BASE_PARTITIONS["vendor"],
        "vendor_dlkm": BASE_DYNAMIC / BASE_PARTITIONS["vendor_dlkm"],
    }
    for partition, image in image_map.items():
        command.extend(
            [
                "--partition",
                f"{partition}_a:none:{image.stat().st_size}:{group_a}",
                "--image",
                f"{partition}_a={wsl_path(image)}",
            ]
        )
    for partition in image_map:
        command.extend(["--partition", f"{partition}_b:none:0:{group_b}"])
    command.extend(["--output", wsl_path(output)])
    run(command)


def split_super(config: dict, super_image: Path, chunks: Path) -> list[Path]:
    chunks.mkdir(parents=True)
    base = chunks / "super.img"
    run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu-22.04",
            "--",
            "simg2simg",
            wsl_path(super_image),
            wsl_path(base),
            str(config["sparse_chunk_max_bytes"]),
        ]
    )
    produced = sorted(chunks.glob("super.img.*"), key=lambda path: int(path.name.rsplit(".", 1)[1]))
    if not produced:
        raise RuntimeError("simg2simg did not produce sparse chunks")
    if produced[0].name.endswith(".0"):
        temporary = []
        for index, path in enumerate(produced, 1):
            renamed = chunks / f"chunk-{index}.tmp"
            path.rename(renamed)
            temporary.append(renamed)
        produced = []
        for index, path in enumerate(temporary, 1):
            renamed = chunks / f"super.img.{index}"
            path.rename(renamed)
            produced.append(renamed)
    return produced


def windows_update_script(chunk_count: int) -> str:
    flashes = "\n".join(
        f'call :run "%FASTBOOT%" flash super "images\\super.img.{index}" || goto :fail'
        for index in range(1, chunk_count + 1)
    )
    checks = "\n".join(
        f'if not exist "images\\super.img.{index}" goto :missing' for index in range(1, chunk_count + 1)
    )
    return f"""@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "FASTBOOT=%~dp0bin\\windows\\fastboot.exe"
set "CHECK_FILE=%TEMP%\\houji_port_product_%RANDOM%.txt"

if not exist "%FASTBOOT%" (
  echo ERROR: fastboot.exe was not found.
  pause
  exit /b 1
)
{checks}
if not exist "images\\vbmeta.img" goto :missing
if not exist "images\\vbmeta_system.img" goto :missing

"%FASTBOOT%" getvar product 2>"%CHECK_FILE%"
set "DEVICE="
for /f "tokens=2" %%A in ('findstr /R /C:"product:" "%CHECK_FILE%"') do set "DEVICE=%%A"
del /q "%CHECK_FILE%" >nul 2>nul
if not "%DEVICE%"=="houji" (
  echo ERROR: connected device is "%DEVICE%". This update is only for houji.
  pause
  exit /b 1
)

echo This updates an existing houji HyperOS 4 CN port WITHOUT formatting data.
echo It does not erase userdata or metadata.
set /p "CHOICE=Type UPDATE to continue: "
if /i not "%CHOICE%"=="UPDATE" exit /b 0

{flashes}
call :run "%FASTBOOT%" flash vbmeta_ab "images\\vbmeta.img" || goto :fail
call :run "%FASTBOOT%" flash vbmeta_system_ab "images\\vbmeta_system.img" || goto :fail
call :run "%FASTBOOT%" set_active a || goto :fail
call :run "%FASTBOOT%" reboot || goto :fail
echo UPDATE COMPLETED.
pause
exit /b 0

:run
echo.
echo RUN: %*
%*
if errorlevel 1 exit /b 1
exit /b 0

:missing
echo ERROR: update package is incomplete. A required image is missing.
pause
exit /b 1

:fail
echo.
echo ERROR: fastboot failed. The script stopped immediately and did not continue.
echo Do not disconnect the phone until you have recorded the error above.
pause
exit /b 1
"""


def unix_update_script(chunk_count: int, platform: str) -> str:
    fastboot = "bin/macos/fastboot" if platform == "macos" else "bin/linux/fastboot"
    flashes = "\n".join(
        f'run "$FASTBOOT" flash super "images/super.img.{index}"' for index in range(1, chunk_count + 1)
    )
    checks = "\n".join(
        f'[ -f "images/super.img.{index}" ] || die "Missing images/super.img.{index}"'
        for index in range(1, chunk_count + 1)
    )
    return f"""#!/bin/sh
set -eu
cd "$(dirname "$0")"
FASTBOOT="{fastboot}"

die() {{ echo "ERROR: $*" >&2; exit 1; }}
run() {{ echo; echo "RUN: $*"; "$@" || die "fastboot command failed; update stopped"; }}

[ -f "$FASTBOOT" ] || die "fastboot was not found: $FASTBOOT"
[ -x "$FASTBOOT" ] || chmod +x "$FASTBOOT" || die "Cannot make fastboot executable"
{checks}
[ -f images/vbmeta.img ] || die "Missing images/vbmeta.img"
[ -f images/vbmeta_system.img ] || die "Missing images/vbmeta_system.img"

DEVICE=$("$FASTBOOT" getvar product 2>&1 | sed -n 's/.*product:[[:space:]]*//p' | head -n 1)
[ "$DEVICE" = "houji" ] || die "Connected device is '$DEVICE'; this update is only for houji"

echo "This updates an existing houji HyperOS 4 CN port WITHOUT formatting data."
echo "It does not erase userdata or metadata."
printf "Type UPDATE to continue: "
read -r CHOICE
[ "$CHOICE" = "UPDATE" ] || exit 0

{flashes}
run "$FASTBOOT" flash vbmeta_ab images/vbmeta.img
run "$FASTBOOT" flash vbmeta_system_ab images/vbmeta_system.img
run "$FASTBOOT" set_active a
run "$FASTBOOT" reboot
echo "UPDATE COMPLETED."
"""


def copy_zip_entry(source: zipfile.ZipFile, info: zipfile.ZipInfo, target: zipfile.ZipFile) -> None:
    new = zipfile.ZipInfo(info.filename, info.date_time)
    new.compress_type = zipfile.ZIP_DEFLATED
    new.create_system = info.create_system
    new.external_attr = info.external_attr
    new.comment = info.comment
    new.extra = info.extra
    with source.open(info) as incoming, target.open(new, "w", force_zip64=True) as outgoing:
        shutil.copyfileobj(incoming, outgoing, 8 * 1024 * 1024)


def add_text(archive: zipfile.ZipFile, name: str, content: str, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, (2026, 8, 20, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    archive.writestr(info, content.encode("utf-8"))


def build_update_zip(
    baseline: Path,
    output: Path,
    chunks: list[Path],
    version: str,
    donor: Path,
    warnings: list[str],
) -> None:
    excluded_top = {
        "windows_install_upgrade.bat",
        "windows_install_and_format_data.bat",
        "windows_format_data_only.bat",
        "linux_install_upgrade.sh",
        "linux_install_and_format_data.sh",
        "linux_format_data_only.sh",
        "macos_install_upgrade.sh",
        "macos_install_and_format_data.sh",
        "macos_format_data_only.sh",
    }
    with zipfile.ZipFile(baseline) as source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as target:
        for info in source.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir():
                continue
            if name in excluded_top or name.startswith("META-INF/") or re.match(r"images/super\.img\.\d+$", name):
                continue
            if name.startswith("images/") and name not in {
                "images/vbmeta.img",
                "images/vbmeta_system.img",
            }:
                continue
            copy_zip_entry(source, info, target)

        for chunk in chunks:
            target.write(chunk, f"images/{chunk.name}", compress_type=zipfile.ZIP_STORED)

        add_text(target, "FLASH_UPDATE_NO_WIPE.bat", windows_update_script(len(chunks)))
        add_text(target, "linux_flash_update_no_wipe.sh", unix_update_script(len(chunks), "linux"), True)
        add_text(target, "macos_flash_update_no_wipe.sh", unix_update_script(len(chunks), "macos"), True)
        warning_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- none"
        add_text(
            target,
            "UPDATE_INFO.txt",
            f"""HyperOS 4 CN port update for houji
Donor: {donor.name}
Donor version: {version}
Target hardware base: OS3.0.305.0.WNCCNXM
Mode: fastboot update only; userdata and metadata are not erased
Root: no
Custom recovery: no

Compatibility notes:
{warning_text}

This is not an official Xiaomi OTA and must not be installed from Xiaomi Updater or stock recovery.
Use only FLASH_UPDATE_NO_WIPE.bat (Windows) or the matching Linux/macOS script.
""",
        )


def verify_zip(path: Path, expected_chunks: int) -> None:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC verification failed: {bad}")
        names = set(archive.namelist())
        chunks = {name for name in names if re.match(r"images/super\.img\.\d+$", name)}
        if len(chunks) != expected_chunks:
            raise RuntimeError(f"ZIP contains {len(chunks)} super chunks; expected {expected_chunks}")
        forbidden = [name for name in names if "format_data" in name or name.startswith("META-INF/")]
        if forbidden:
            raise RuntimeError(f"Update ZIP contains forbidden recovery/format entries: {forbidden}")
        for required in (
            "FLASH_UPDATE_NO_WIPE.bat",
            "linux_flash_update_no_wipe.sh",
            "macos_flash_update_no_wipe.sh",
            "images/vbmeta.img",
            "images/vbmeta_system.img",
        ):
            if required not in names:
                raise RuntimeError(f"Update ZIP is missing {required}")


def write_report(
    output: Path,
    donor: Path,
    version: str,
    metadata: dict[str, str],
    chunks: list[Path],
    warnings: list[str],
) -> None:
    digest = sha256(output)
    report = output.with_suffix(".txt")
    lines = [
        "HyperOS 4 houji port update build report",
        f"output={output.name}",
        f"size={output.stat().st_size}",
        f"sha256={digest}",
        f"donor={donor.name}",
        f"donor_version={version}",
        f"post_build={metadata.get('post-build', '')}",
        f"super_chunks={len(chunks)}",
        "userdata_erased=no",
        "metadata_erased=no",
        "bootloader_firmware_flashing=no",
        "root=no",
        "custom_recovery=no",
        "",
        "Warnings:",
        *(f"- {item}" for item in warnings),
    ]
    if not warnings:
        lines.append("- none")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (output.parent / f"{output.name}.sha256").write_text(
        f"{digest} *{output.name}\n", encoding="ascii", newline="\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a no-wipe HyperOS 4 update for Xiaomi 14 (houji)"
    )
    parser.add_argument("donor", nargs="?", help="pudding full OTA ZIP; otherwise input/*.zip is used")
    parser.add_argument("--keep-work", action="store_true", help="keep temporary build files")
    args = parser.parse_args()

    config = load_config()
    manifest = load_json(MANIFEST_PATH)
    donor = choose_donor(config, args.donor)
    baseline = resolve_from(AUTOMATION, config["baseline_port_zip"])
    metadata, version = validate_inputs(config, manifest, donor, baseline)
    check_free_space(config, AUTOMATION)

    work_root = AUTOMATION / "work"
    work = work_root / "current"
    work_root.mkdir(exist_ok=True)
    safe_remove_tree(work, work_root)
    work.mkdir()
    output_dir = resolve_from(AUTOMATION, config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", version)
    output = output_dir / f"houji_HyperOS4_CN_{safe_version}_update-from-v1_no-wipe.zip"
    sidecars = (
        output.with_suffix(".txt"),
        output.parent / f"{output.name}.sha256",
    )
    for published in (output, *sidecars):
        if published.exists():
            published.unlink()

    warnings: list[str] = []
    try:
        log(f"Donor: {donor}")
        log(f"Version: {version}")
        images = work / "donor_images"
        trees = work / "trees"
        repacked = work / "repacked"
        extract_payload(donor, images)
        extract_erofs(images, trees)
        warnings = apply_port_patch(trees, manifest, version, config)
        for warning in warnings:
            log("WARNING: " + warning)
        repack_erofs(trees, repacked)
        super_image = work / "super.sparse.img"
        build_super(config, repacked, super_image)
        chunks = split_super(config, super_image, work / "chunks")
        log(f"Sparse chunks: {len(chunks)}")
        build_update_zip(baseline, output, chunks, version, donor, warnings)
        verify_zip(output, len(chunks))
        write_report(output, donor, version, metadata, chunks, warnings)
        log(f"DONE: {output}")
        log(f"SHA-256: {sha256(output)}")
    except Exception:
        for published in (output, *sidecars):
            if published.exists():
                published.unlink()
        raise
    finally:
        if not args.keep_work:
            safe_remove_tree(work, work_root)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Cancelled by user")
        raise SystemExit(130)
    except Exception as error:
        log(f"ERROR: {error}")
        raise SystemExit(1)
