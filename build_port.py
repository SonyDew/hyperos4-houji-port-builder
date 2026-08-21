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

import bsdiff4


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.example.json"
LOCAL_CONFIG_PATH = ROOT / "config.local.json"
MANIFEST_PATH = ROOT / "patch_manifest.json"
PAYLOAD_EXTRACTOR = ROOT / "scripts" / "extract_payload_zip_sequential.py"

DONOR_PARTITIONS = ("system", "system_ext", "product", "mi_ext")
REPACKED_PARTITIONS = (*DONOR_PARTITIONS, "vendor")
BASE_DYNAMIC_DIRECT = ("odm", "system_dlkm", "vendor_dlkm")

FIRMWARE_PARTITIONS = (
    "abl",
    "aop",
    "aop_config",
    "bluetooth",
    "cpucp",
    "cpucp_dtb",
    "devcfg",
    "dsp",
    "dtbo",
    "featenabler",
    "hyp",
    "imagefv",
    "keymaster",
    "modem",
    "modemfirmware",
    "multiimgqti",
    "qupfw",
    "shrm",
    "spuservice",
    "tz",
    "uefi",
    "uefisecapp",
    "vm-bootsys",
    "xbl",
    "xbl_config",
    "xbl_ramdump",
    "boot",
    "init_boot",
    "vendor_boot",
    "recovery",
    "vbmeta",
    "vbmeta_system",
)

BASE_PAYLOAD_PARTITIONS = tuple(
    dict.fromkeys((*FIRMWARE_PARTITIONS, *BASE_DYNAMIC_DIRECT, "vendor", "product"))
)

BASE_PRODUCT_FILES = (
    "product/etc/device_features/houji.xml",
    "product/overlay/DevicesAndroidOverlay.apk",
    "product/overlay/DevicesOverlay.apk",
    "product/overlay/MiuiFrameworkResOverlay.apk",
    "product/priv-app/MiuiCamera/MiuiCamera.apk",
)

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

# These are the unused 32-bit GPU/display files removed from the proven v1
# build. The matching 64-bit files remain untouched.
VENDOR_32_BIT_PRUNE = (
    "lib/egl/eglSubDriverAndroid.so",
    "lib/egl/libEGL_adreno.so",
    "lib/egl/libGLESv1_CM_adreno.so",
    "lib/egl/libGLESv2_adreno.so",
    "lib/egl/libVkLayer_ADRENO_qprofiler.so",
    "lib/egl/libq3dtools_adreno.so",
    "lib/egl/libq3dtools_esx.so",
    "lib/hw/android.hardware.graphics.mapper@4.0-impl-qti-display.so",
    "lib/hw/vulkan.adreno.so",
    "lib/hw/vulkan.adreno.so.tango",
    "lib/libCB.so",
    "lib/libOpenCL.so",
    "lib/libOpenCL_adreno.so",
    "lib/libadreno_app_profiles.so",
    "lib/libadreno_utils.so",
    "lib/libcamxexternalformatutils.so",
    "lib/libdrm.so",
    "lib/libgpudataproducer.so",
    "lib/libgralloc.qti.so",
    "lib/libgralloccore.so",
    "lib/libgrallocutils.so",
    "lib/libgsl.so",
    "lib/libkcl.so",
    "lib/libkernelmanager.so",
    "lib/libllvm-glnext.so",
    "lib/libllvm-qcom.so",
    "lib/libllvm-qgl.so",
    "lib/libvmmem.so",
    "lib/vendor.qti.hardware.display.allocator@1.0.so",
    "lib/vendor.qti.hardware.display.allocator@3.0.so",
    "lib/vendor.qti.hardware.display.allocator@4.0.so",
    "lib/vendor.qti.hardware.display.composer@1.0.so",
    "lib/vendor.qti.hardware.display.composer@2.0.so",
    "lib/vendor.qti.hardware.display.composer@3.0.so",
    "lib/vendor.qti.hardware.display.config-V1-ndk.so",
    "lib/vendor.qti.hardware.display.config-V2-ndk.so",
    "lib/vendor.qti.hardware.display.config-V3-ndk.so",
    "lib/vendor.qti.hardware.display.config-V4-ndk.so",
    "lib/vendor.qti.hardware.display.config-V5-ndk.so",
    "lib/vendor.qti.hardware.display.config-V6-ndk.so",
    "lib/vendor.qti.hardware.display.demura@2.0.so",
    "lib/vendor.qti.hardware.display.mapper@1.0.so",
    "lib/vendor.qti.hardware.display.mapper@1.1.so",
    "lib/vendor.qti.hardware.display.mapper@2.0.so",
    "lib/vendor.qti.hardware.display.mapper@3.0.so",
    "lib/vendor.qti.hardware.display.mapper@4.0.so",
    "lib/vendor.qti.hardware.display.mapperextensions@1.0.so",
    "lib/vendor.qti.hardware.display.mapperextensions@1.1.so",
    "lib/vendor.qti.hardware.display.mapperextensions@1.2.so",
    "lib/vendor.qti.hardware.display.mapperextensions@1.3.so",
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


def resolve_from(base: Path, supplied: str | Path) -> Path:
    path = Path(supplied)
    return (path if path.is_absolute() else base / path).resolve()


def safe_remove_tree(path: Path, allowed_parent: Path) -> None:
    target = path.resolve()
    parent = allowed_parent.resolve()
    if target == parent or os.path.commonpath((str(parent), str(target))) != str(parent):
        raise RuntimeError(f"Refusing unsafe cleanup target: {target}")
    if target.exists():
        shutil.rmtree(target)


def run(command: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    log("RUN: " + subprocess.list2cmdline(command))
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=capture,
        capture_output=capture,
    )
    return result.stdout if capture else ""


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise RuntimeError(f"Expected a Windows drive path: {resolved}")
    tail = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{tail}"


def read_ota_metadata(archive_path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if "payload.bin" not in archive.namelist():
                raise RuntimeError(f"Full OTA payload.bin is missing: {archive_path.name}")
            raw = archive.read("META-INF/com/android/metadata").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile) as error:
        raise RuntimeError(f"Invalid Android full OTA: {archive_path}") from error

    result: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def public_version(path: Path, prefix: str) -> str:
    match = re.search(rf"{prefix}\d+(?:\.\d+)+\.[A-Z0-9]+", path.name, re.IGNORECASE)
    if not match:
        raise RuntimeError(
            f"Could not read the public HyperOS version from {path.name}. "
            "Keep the original Xiaomi OTA filename."
        )
    return match.group(0).upper()


def scan_input_otas(input_dir: Path, base_device: str, donor_device: str) -> tuple[Path, Path]:
    input_dir.mkdir(parents=True, exist_ok=True)
    matches: dict[str, list[Path]] = {base_device: [], donor_device: []}
    for candidate in sorted(input_dir.glob("*.zip")):
        try:
            metadata = read_ota_metadata(candidate)
        except RuntimeError:
            continue
        devices = metadata.get("pre-device", "").split(",")
        for device in matches:
            if device in devices:
                matches[device].append(candidate.resolve())
    for device, paths in matches.items():
        if len(paths) != 1:
            found = ", ".join(path.name for path in paths) or "none"
            raise RuntimeError(
                f"Expected exactly one full {device} OTA in {input_dir}; found: {found}"
            )
    return matches[base_device][0], matches[donor_device][0]


def choose_otas(config: dict, base_arg: str | None, donor_arg: str | None) -> tuple[Path, Path]:
    if bool(base_arg) != bool(donor_arg):
        raise RuntimeError("Pass both OTA paths, or put both official OTA ZIPs in input")
    if base_arg and donor_arg:
        base = resolve_from(Path.cwd(), base_arg)
        donor = resolve_from(Path.cwd(), donor_arg)
        if not base.is_file() or not donor.is_file():
            raise RuntimeError(f"OTA not found: {base if not base.is_file() else donor}")
        return base, donor
    input_dir = resolve_from(ROOT, config["input_directory"])
    return scan_input_otas(
        input_dir,
        config["expected_base_device"],
        config["expected_donor_device"],
    )


def validate_otas(
    config: dict, manifest: dict, base: Path, donor: Path
) -> tuple[dict[str, str], dict[str, str], str, str]:
    base_metadata = read_ota_metadata(base)
    donor_metadata = read_ota_metadata(donor)
    checks = (
        ("base", base_metadata, config["expected_base_device"], config["expected_base_sdk"]),
        ("donor", donor_metadata, config["expected_donor_device"], config["expected_donor_sdk"]),
    )
    for label, metadata, device, sdk in checks:
        if device not in metadata.get("pre-device", "").split(","):
            raise RuntimeError(f"Wrong {label} device: expected {device}")
        if metadata.get("post-sdk-level") != str(sdk):
            raise RuntimeError(
                f"Wrong {label} Android SDK: expected {sdk}, got {metadata.get('post-sdk-level')!r}"
            )
        if metadata.get("ota-type") != "AB":
            raise RuntimeError(f"{label.capitalize()} must be a full A/B Recovery OTA")

    base_version = public_version(base, "OS3.")
    donor_version = public_version(donor, "OS4.")
    if base_version != manifest["base_profile"]["version"]:
        raise RuntimeError(
            f"Unsupported houji base {base_version}; expected {manifest['base_profile']['version']}"
        )
    expected_post_build = manifest["base_profile"]["post_build"]
    if base_metadata.get("post-build") != expected_post_build:
        raise RuntimeError("The houji OTA metadata does not match the verified OS3.0.305 base")
    return base_metadata, donor_metadata, base_version, donor_version


def tool_paths(config: dict) -> dict[str, Path]:
    tools = resolve_from(ROOT, config["tools_directory"])
    erofs = tools / "erofs-utils"
    android = tools / "android-tools-static" / "android-tools-static"
    result = {
        "extract_erofs": erofs / "extract.erofs.exe",
        "mkfs_erofs": erofs / "mkfs.erofs.exe",
        "lpmake": android / "lpmake",
        "lpdump": android / "lpdump",
        "simg2img": android / "simg2img",
        "avbtool": tools / "avbtool.py",
    }
    missing = [str(path) for path in (*result.values(), PAYLOAD_EXTRACTOR) if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Required local build tools are missing:\n"
            + "\n".join(missing)
            + "\nRun LINK_LOCAL_FILES.bat or set tools_directory in config.local.json."
        )
    return result


def check_environment(config: dict, tools: dict[str, Path]) -> None:
    if shutil.which("wsl.exe") is None:
        raise RuntimeError("WSL is required on Windows")
    distro = config["wsl_distribution"]
    run(["wsl.exe", "-d", distro, "--", "sh", "-lc", "command -v simg2simg >/dev/null"])
    run(["wsl.exe", "-d", distro, "--", "test", "-x", wsl_path(tools["lpmake"])])


def check_free_space(config: dict, path: Path) -> None:
    free = shutil.disk_usage(path).free
    required = int(config["minimum_free_space_gib"]) * 1024**3
    if free < required:
        raise RuntimeError(
            f"Not enough free space: {free / 1024**3:.1f} GiB available; "
            f"at least {required / 1024**3:.0f} GiB required"
        )


def extract_payload(archive: Path, output: Path, partitions: tuple[str, ...], work: Path) -> None:
    command = [sys.executable, str(PAYLOAD_EXTRACTOR), str(archive), str(output), *partitions]
    for attempt in (1, 2):
        safe_remove_tree(output, work)
        output.mkdir(parents=True)
        try:
            run(command)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            log("Payload verification failed; retrying extraction once")


def extract_erofs_full(
    extractor: Path, images: Path, trees: Path, partitions: tuple[str, ...]
) -> None:
    trees.mkdir(parents=True, exist_ok=True)
    for partition in partitions:
        run(
            [
                str(extractor),
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
            raise RuntimeError(f"EROFS extractor did not create {trees / partition}")


def extract_base_product_files(extractor: Path, image: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for relative in BASE_PRODUCT_FILES:
        inside = "/" + relative.removeprefix("product/")
        run(
            [
                str(extractor),
                "-i",
                str(image),
                "-X",
                inside,
                "-o",
                str(output),
                "-f",
                "-s",
            ]
        )
        if not (output / relative).is_file():
            raise RuntimeError(f"Could not extract official houji file: {relative}")


def remove_path(path: Path, root: Path) -> None:
    target = path.resolve()
    resolved_root = root.resolve()
    if target == resolved_root or os.path.commonpath((str(resolved_root), str(target))) != str(
        resolved_root
    ):
        raise RuntimeError(f"Unsafe prune path: {target}")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()


def prune_generated(root: Path) -> tuple[int, int]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and ("oat" in path.relative_to(root).parts or path.name.endswith(DERIVED_SUFFIXES))
    ]
    count = len(files)
    size = sum(path.stat().st_size for path in files)
    for path in files:
        path.unlink()
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    return count, size


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def ensure_config_entry(config_path: Path, entry: str) -> None:
    text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    key = entry.split(" ", 1)[0]
    if not any(line.split(" ", 1)[0] == key for line in text.splitlines() if line):
        with config_path.open("a", encoding="utf-8", newline="\n") as stream:
            if text and not text.endswith("\n"):
                stream.write("\n")
            stream.write(entry + "\n")


def patch_properties(trees: Path, donor_version: str, config: dict) -> None:
    system_props_path = trees / "system" / "system" / "build.prop"
    product_props_path = trees / "product" / "etc" / "build.prop"
    mi_ext_props_path = trees / "mi_ext" / "etc" / "build.prop"
    props = read_properties(product_props_path)
    if props.get("ro.build.version.release") != str(config["expected_android_release"]):
        raise RuntimeError("Donor product has an unexpected Android release")
    if props.get("ro.build.version.sdk") != str(config["expected_donor_sdk"]):
        raise RuntimeError("Donor product has an unexpected Android SDK")

    product_text = product_props_path.read_text(encoding="utf-8", errors="strict").replace(
        "pudding", "houji"
    )
    updates = {"persist.miui.density_v2": "480", "ro.sf.lcd_density": "480"}
    removals = {
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
    lines: list[str] = []
    for line in product_text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in removals:
                continue
            if key in updates:
                line = f"{key}={updates[key]}"
        lines.append(line)
    scheduling = (
        "# houji SM8650 scheduling and memory profile",
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
    )
    product_props_path.write_text(
        "\n".join(lines).rstrip("\n") + "\n\n" + "\n".join(scheduling) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    mi_ext_text = mi_ext_props_path.read_text(encoding="utf-8", errors="strict")
    mi_ext_text, replacements = re.subn(
        r"(?m)^ro\.product\.mod_device=.*$", "ro.product.mod_device=houji", mi_ext_text
    )
    if replacements != 1:
        raise RuntimeError("Expected one ro.product.mod_device entry in mi_ext")
    mi_ext_props_path.write_text(mi_ext_text, encoding="utf-8", newline="\n")

    system_lines = [
        line
        for line in system_props_path.read_text(encoding="utf-8", errors="strict").splitlines()
        if not line.startswith("ro.build.fingerprint=")
        and line != "# Port identity: HyperOS 4 user space on houji Android 14 vendor base"
    ]
    system_block = (
        "# Port identity: HyperOS 4 user space on houji Android 14 vendor base",
        "ro.build.fingerprint=Xiaomi/houji/houji:14/UKQ1.240624.001/"
        + donor_version
        + ":user/release-keys",
    )
    system_props_path.write_text(
        "\n".join(system_lines).rstrip("\n") + "\n\n" + "\n".join(system_block) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_base_assets(base_assets: Path, manifest: dict) -> None:
    for relative, expected in manifest["base_profile"]["product_file_hashes"].items():
        path = base_assets / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Official houji product file failed verification: {relative}")


def apply_binary_profile(trees: Path, donor_version: str, manifest: dict) -> tuple[str, list[str]]:
    profile = manifest.get("donor_profiles", {}).get(donor_version)
    warnings: list[str] = []
    if profile:
        sources_match = all(
            (trees / item["target"]).is_file()
            and sha256(trees / item["target"]) == item["source_sha256"]
            for item in profile["binary_patches"]
        )
    else:
        sources_match = False

    if not sources_match:
        warnings.append(
            f"No exact proven patch profile for {donor_version}; stock houji camera compatibility mode was used"
        )
        return "stock-houji-camera", warnings

    for item in profile["binary_patches"]:
        target = trees / item["target"]
        patch = ROOT / item["patch"]
        if not patch.is_file() or sha256(patch) != item["patch_sha256"]:
            raise RuntimeError(f"Binary patch is missing or damaged: {patch}")
        temporary = target.with_name(target.name + ".patched")
        if temporary.exists():
            temporary.unlink()
        bsdiff4.file_patch(str(target), str(temporary), str(patch))
        if sha256(temporary) != item["output_sha256"]:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Patched output failed verification: {item['target']}")
        temporary.replace(target)
    return "proven-binary-profile", warnings


def apply_port_changes(
    trees: Path,
    base_assets: Path,
    donor_version: str,
    config: dict,
    manifest: dict,
) -> tuple[str, list[str]]:
    patch_properties(trees, donor_version, config)

    for relative in PRODUCT_PRUNE:
        remove_path(trees / "product" / relative, trees / "product")
    for relative in VENDOR_32_BIT_PRUNE:
        remove_path(trees / "vendor" / relative, trees / "vendor")

    removed_count = 0
    removed_size = 0
    for partition in DONOR_PARTITIONS:
        count, size = prune_generated(trees / partition)
        removed_count += count
        removed_size += size
    log(f"Removed {removed_count} generated files ({removed_size / 1024**2:.1f} MiB)")

    for relative in BASE_PRODUCT_FILES[:-1]:
        destination = trees / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_assets / relative, destination)

    profile_mode, warnings = apply_binary_profile(trees, donor_version, manifest)
    if profile_mode == "stock-houji-camera":
        camera = "product/priv-app/MiuiCamera/MiuiCamera.apk"
        shutil.copy2(base_assets / camera, trees / camera)

    ensure_config_entry(
        trees / "config" / "product_fs_config",
        "product/etc/device_features/houji.xml 0 0 0644",
    )
    ensure_config_entry(
        trees / "config" / "product_file_contexts",
        r"/product/etc/device_features/houji\.xml u:object_r:system_file:s0",
    )
    return profile_mode, warnings


def read_erofs_uuid(config_file: Path) -> str:
    text = config_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Filesystem UUID:\s*([0-9a-fA-F-]{36})", text)
    if not match:
        raise RuntimeError(f"Could not read EROFS UUID from {config_file}")
    return match.group(1)


def repack_erofs(mkfs: Path, trees: Path, repacked: Path) -> None:
    repacked.mkdir(parents=True, exist_ok=True)
    for partition in REPACKED_PARTITIONS:
        fs_config = trees / "config" / f"{partition}_fs_config"
        contexts = trees / "config" / f"{partition}_file_contexts"
        options = trees / "config" / f"{partition}_fs_options"
        for required in (fs_config, contexts, options):
            if not required.is_file():
                raise RuntimeError(f"EROFS config is missing: {required}")
        run(
            [
                str(mkfs),
                "--quiet",
                "-zlz4hc",
                "-T0",
                "-U",
                read_erofs_uuid(options),
                f"--mount-point=/{partition}",
                f"--fs-config-file={fs_config}",
                f"--file-contexts={contexts}",
                str(repacked / f"{partition}.img"),
                str(trees / partition),
            ]
        )


def avb_info(avbtool: Path, image: Path) -> dict[str, int]:
    text = run([sys.executable, str(avbtool), "info_image", "--image", str(image)], capture=True)
    result: dict[str, int] = {}
    for field, key in (("Rollback Index", "rollback"), ("Rollback Index Location", "location")):
        match = re.search(rf"(?m)^{re.escape(field)}:\s*(\d+)", text)
        if not match:
            raise RuntimeError(f"Could not read {field} from {image}")
        result[key] = int(match.group(1))
    return result


def patch_vbmeta(avbtool: Path, base_images: Path, output: Path, manifest: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("vbmeta", "vbmeta_system"):
        source = base_images / f"{name}.img"
        target = output / f"{name}.img"
        info = avb_info(avbtool, source)
        run(
            [
                sys.executable,
                str(avbtool),
                "make_vbmeta_image",
                "--output",
                str(target),
                "--include_descriptors_from_image",
                str(source),
                "--algorithm",
                "NONE",
                "--flags",
                "3",
                "--padding_size",
                str(source.stat().st_size),
                "--rollback_index",
                str(info["rollback"]),
                "--rollback_index_location",
                str(info["location"]),
            ]
        )
        expected = manifest["base_profile"]["patched_vbmeta_hashes"][f"{name}.img"]
        if sha256(target) != expected:
            raise RuntimeError(f"Patched {name} does not match the verified profile")


def build_super(
    config: dict,
    tools: dict[str, Path],
    base_images: Path,
    repacked: Path,
    output: Path,
) -> None:
    group_a = "qti_dynamic_partitions_a"
    group_b = "qti_dynamic_partitions_b"
    distro = config["wsl_distribution"]
    command = [
        "wsl.exe",
        "-d",
        distro,
        "--",
        wsl_path(tools["lpmake"]),
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
    images = {
        "mi_ext": repacked / "mi_ext.img",
        "odm": base_images / "odm.img",
        "product": repacked / "product.img",
        "system": repacked / "system.img",
        "system_dlkm": base_images / "system_dlkm.img",
        "system_ext": repacked / "system_ext.img",
        "vendor": repacked / "vendor.img",
        "vendor_dlkm": base_images / "vendor_dlkm.img",
    }
    total = sum(path.stat().st_size for path in images.values())
    if total > int(config["super_size"]):
        raise RuntimeError(
            f"Dynamic partitions need {total} bytes but super only has {config['super_size']} bytes"
        )
    for partition, image in images.items():
        command.extend(
            [
                "--partition",
                f"{partition}_a:none:{image.stat().st_size}:{group_a}",
                "--image",
                f"{partition}_a={wsl_path(image)}",
            ]
        )
    for partition in images:
        command.extend(["--partition", f"{partition}_b:none:0:{group_b}"])
    command.extend(["--output", wsl_path(output)])
    run(command)


def validate_super(config: dict, tools: dict[str, Path], super_image: Path, report: Path) -> None:
    raw_image = super_image.with_name("super.validation.raw.img")
    try:
        run(
            [
                "wsl.exe",
                "-d",
                config["wsl_distribution"],
                "--",
                wsl_path(tools["simg2img"]),
                wsl_path(super_image),
                wsl_path(raw_image),
            ]
        )
        text = run(
            [
                "wsl.exe",
                "-d",
                config["wsl_distribution"],
                "--",
                wsl_path(tools["lpdump"]),
                wsl_path(raw_image),
            ],
            capture=True,
        )
    finally:
        raw_image.unlink(missing_ok=True)
    required = {f"{name}_a" for name in (*DONOR_PARTITIONS, "odm", "system_dlkm", "vendor", "vendor_dlkm")}
    missing = sorted(name for name in required if f"Name: {name}" not in text)
    if missing:
        raise RuntimeError(f"super.img is missing dynamic partitions: {', '.join(missing)}")
    report.write_text(text, encoding="utf-8", newline="\n")


def split_super(config: dict, super_image: Path, chunks: Path, work: Path) -> list[Path]:
    safe_remove_tree(chunks, work)
    chunks.mkdir(parents=True)
    run(
        [
            "wsl.exe",
            "-d",
            config["wsl_distribution"],
            "--",
            "simg2simg",
            wsl_path(super_image),
            wsl_path(chunks / "super.img"),
            str(config["sparse_chunk_max_bytes"]),
        ]
    )
    produced = sorted(chunks.glob("super.img.*"), key=lambda p: int(p.name.rsplit(".", 1)[1]))
    if not produced:
        raise RuntimeError("simg2simg did not produce any chunks")
    if produced[0].name.endswith(".0"):
        temporary: list[Path] = []
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


def prepare_experimental_modem(
    supplied: str | None, config: dict, work: Path, manifest: dict
) -> Path | None:
    candidates: list[Path] = []
    if supplied:
        candidates.append(resolve_from(Path.cwd(), supplied))
    else:
        candidates.extend(
            [
                ROOT / "local" / "modemfirmware_ww.img",
                ROOT / "input" / "modemfirmware_ww.img",
                ROOT / "local" / "experimental-modem.zip",
            ]
        )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        return None

    output = work / "experimental" / "modemfirmware_ww.img"
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".img":
        shutil.copy2(source, output)
    elif source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            choices = ("images/modemfirmware_ww.img", "modemfirmware_ww.img")
            name = next((item for item in choices if item in archive.namelist()), None)
            if name is None:
                raise RuntimeError("The experimental modem ZIP has no modemfirmware_ww.img")
            with archive.open(name) as incoming, output.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 8 * 1024 * 1024)
    else:
        raise RuntimeError("Experimental modem source must be an IMG or ZIP")

    expected = manifest["experimental_modem"]["sha256"]
    if sha256(output) != expected:
        raise RuntimeError("Experimental modem hash is not recognized; it was not included")
    if output.stat().st_size != int(manifest["experimental_modem"]["size"]):
        raise RuntimeError("Experimental modem has an unexpected size")
    return output


def fastboot_candidates(tools_directory: Path) -> dict[str, Path]:
    choices = {
        "bin/windows/fastboot.exe": (
            tools_directory / "platform-tools" / "fastboot.exe",
            tools_directory / "fastboot" / "windows" / "fastboot.exe",
        ),
        "bin/linux/fastboot": (
            tools_directory / "fastboot" / "linux" / "fastboot",
        ),
        "bin/macos/fastboot": (
            tools_directory / "fastboot" / "macos" / "fastboot",
        ),
    }
    result: dict[str, Path] = {}
    for archive_name, candidates in choices.items():
        source = next((path for path in candidates if path.is_file()), None)
        if source:
            result[archive_name] = source
    return result


def windows_fastboot_header(required_images: tuple[str, ...]) -> str:
    checks = "\n".join(f'if not exist "images\\{name}" goto :missing' for name in required_images)
    return f'''@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "FASTBOOT="
if exist "%~dp0bin\\windows\\fastboot.exe" set "FASTBOOT=%~dp0bin\\windows\\fastboot.exe"
if not defined FASTBOOT if exist "%~dp0fastboot.exe" set "FASTBOOT=%~dp0fastboot.exe"
if not defined FASTBOOT where fastboot.exe >nul 2>nul && set "FASTBOOT=fastboot.exe"
if not defined FASTBOOT (
  echo ERROR: fastboot was not found. Install Android Platform Tools or copy fastboot.exe here.
  pause
  exit /b 1
)
{checks}
set "CHECK_FILE=%TEMP%\\houji_product_%RANDOM%.txt"
"%FASTBOOT%" getvar product 2>"%CHECK_FILE%"
set "DEVICE="
for /f "tokens=2" %%A in ('findstr /R /C:"product:" "%CHECK_FILE%"') do set "DEVICE=%%A"
del /q "%CHECK_FILE%" >nul 2>nul
if not "%DEVICE%"=="houji" (
  echo ERROR: connected device is "%DEVICE%". This package is only for Xiaomi 14 houji.
  pause
  exit /b 1
)
'''


def windows_run_footer() -> str:
    return '''
:run
echo.
echo RUN: %*
%*
if errorlevel 1 exit /b 1
exit /b 0

:missing
echo ERROR: the package is incomplete. A required image is missing.
pause
exit /b 1

:fail
echo.
echo ERROR: fastboot failed. Flashing stopped immediately.
echo Keep the phone connected and save the error shown above.
pause
exit /b 1
'''


def windows_first_install_script(chunk_count: int, experimental: bool) -> str:
    image_names = tuple(f"super.img.{index}" for index in range(1, chunk_count + 1)) + tuple(
        f"{name}.img" for name in FIRMWARE_PARTITIONS
    )
    experimental_block = (
        '''if not exist "images\\modemfirmware_ww.img" goto :region_error
echo.
echo EXPERIMENTAL MODEM WARNING
echo This modem works, but it has not been tested for a long period.
echo Continue only if you understand the risk.
set /p "MODEM_CONFIRM=Type EXPERIMENTAL to use it: "
if /i not "%MODEM_CONFIRM%"=="EXPERIMENTAL" exit /b 0
set "MODEM_IMAGE=images\\modemfirmware_ww.img"'''
        if experimental
        else "goto :region_error"
    )
    firmware_lines = []
    for name in FIRMWARE_PARTITIONS:
        if name == "modemfirmware":
            firmware_lines.append('call :run "%FASTBOOT%" flash modemfirmware_ab "%MODEM_IMAGE%" || goto :fail')
        elif name in {"vbmeta", "vbmeta_system"}:
            firmware_lines.append(
                f'call :run "%FASTBOOT%" flash {name}_ab "images\\{name}.img" || goto :fail'
            )
        else:
            firmware_lines.append(
                f'call :run "%FASTBOOT%" flash {name}_ab "images\\{name}.img" || goto :fail'
            )
    chunks = "\n".join(
        f'call :run "%FASTBOOT%" flash super "images\\super.img.{index}" || goto :fail'
        for index in range(1, chunk_count + 1)
    )
    return (
        windows_fastboot_header(image_names)
        + f'''set "HWC_FILE=%TEMP%\\houji_hwc_%RANDOM%.txt"
"%FASTBOOT%" oem hwid 2>"%HWC_FILE%"
set "HWC="
for /f "tokens=3" %%A in ('findstr /R /C:"HwCountry:" "%HWC_FILE%"') do set "HWC=%%A"
del /q "%HWC_FILE%" >nul 2>nul
set "MODEM_IMAGE=images\\modemfirmware.img"
if /i not "%HWC%"=="CN" (
{experimental_block}
)

echo.
echo FIRST INSTALL: userdata and metadata will be erased.
echo All apps, settings and internal-storage files will be deleted.
set /p "CONFIRM=Type ERASE to continue: "
if /i not "%CONFIRM%"=="ERASE" exit /b 0

call :run "%FASTBOOT%" set_active a || goto :fail
{chr(10).join(firmware_lines)}
{chunks}
call :run "%FASTBOOT%" erase metadata || goto :fail
call :run "%FASTBOOT%" erase userdata || goto :fail
call :run "%FASTBOOT%" reboot || goto :fail
echo FIRST INSTALL COMPLETED.
pause
exit /b 0

:region_error
echo ERROR: this is not a CN device and the experimental modem is not available or was declined.
echo Nothing was flashed.
pause
exit /b 1
'''
        + windows_run_footer()
    )


def windows_update_script(chunk_count: int) -> str:
    required = tuple(f"super.img.{index}" for index in range(1, chunk_count + 1)) + (
        "vbmeta.img",
        "vbmeta_system.img",
    )
    chunks = "\n".join(
        f'call :run "%FASTBOOT%" flash super "images\\super.img.{index}" || goto :fail'
        for index in range(1, chunk_count + 1)
    )
    return (
        windows_fastboot_header(required)
        + f'''echo This updates an existing houji HyperOS 4 port without erasing data.
set /p "CONFIRM=Type UPDATE to continue: "
if /i not "%CONFIRM%"=="UPDATE" exit /b 0

call :run "%FASTBOOT%" set_active a || goto :fail
{chunks}
call :run "%FASTBOOT%" flash vbmeta_ab "images\\vbmeta.img" || goto :fail
call :run "%FASTBOOT%" flash vbmeta_system_ab "images\\vbmeta_system.img" || goto :fail
call :run "%FASTBOOT%" reboot || goto :fail
echo UPDATE COMPLETED.
pause
exit /b 0
'''
        + windows_run_footer()
    )


def unix_fastboot_header(required_images: tuple[str, ...], platform: str) -> str:
    bundled = "bin/macos/fastboot" if platform == "macos" else "bin/linux/fastboot"
    checks = "\n".join(f'[ -f "images/{name}" ] || die "Missing images/{name}"' for name in required_images)
    return f'''#!/bin/sh
set -eu
cd "$(dirname "$0")"

die() {{ echo "ERROR: $*" >&2; exit 1; }}
run() {{ echo; echo "RUN: $*"; "$@" || die "fastboot failed; flashing stopped"; }}

if [ -f "{bundled}" ]; then
  FASTBOOT="{bundled}"
  [ -x "$FASTBOOT" ] || chmod +x "$FASTBOOT" || die "Cannot make fastboot executable"
elif [ -f ./fastboot ]; then
  FASTBOOT=./fastboot
  [ -x "$FASTBOOT" ] || chmod +x "$FASTBOOT" || die "Cannot make fastboot executable"
elif command -v fastboot >/dev/null 2>&1; then
  FASTBOOT=fastboot
else
  die "fastboot was not found. Install Android Platform Tools or copy fastboot here"
fi
{checks}
DEVICE=$("$FASTBOOT" getvar product 2>&1 | sed -n 's/.*product:[[:space:]]*//p' | head -n 1)
[ "$DEVICE" = "houji" ] || die "Connected device is '$DEVICE'; this package is only for houji"
'''


def unix_first_install_script(chunk_count: int, platform: str, experimental: bool) -> str:
    required = tuple(f"super.img.{index}" for index in range(1, chunk_count + 1)) + tuple(
        f"{name}.img" for name in FIRMWARE_PARTITIONS
    )
    experimental_block = (
        '''[ -f images/modemfirmware_ww.img ] || die "Experimental modem is not included; nothing was flashed"
  echo
  echo "EXPERIMENTAL MODEM WARNING"
  echo "This modem works, but it has not been tested for a long period."
  printf "Type EXPERIMENTAL to use it: "
  read -r MODEM_CONFIRM
  [ "$MODEM_CONFIRM" = "EXPERIMENTAL" ] || exit 0
  MODEM_IMAGE=images/modemfirmware_ww.img'''
        if experimental
        else 'die "This is not a CN device and no experimental modem was included; nothing was flashed"'
    )
    flashes = []
    for name in FIRMWARE_PARTITIONS:
        image = "$MODEM_IMAGE" if name == "modemfirmware" else f"images/{name}.img"
        flashes.append(f'run "$FASTBOOT" flash {name}_ab {image}')
    chunks = "\n".join(
        f'run "$FASTBOOT" flash super images/super.img.{index}'
        for index in range(1, chunk_count + 1)
    )
    return unix_fastboot_header(required, platform) + f'''HWC=$("$FASTBOOT" oem hwid 2>&1 | sed -n 's/.*HwCountry:[[:space:]]*//p' | head -n 1)
MODEM_IMAGE=images/modemfirmware.img
if [ "$HWC" != "CN" ]; then
  {experimental_block}
fi

echo
echo "FIRST INSTALL: userdata and metadata will be erased."
echo "All apps, settings and internal-storage files will be deleted."
printf "Type ERASE to continue: "
read -r CONFIRM
[ "$CONFIRM" = "ERASE" ] || exit 0

run "$FASTBOOT" set_active a
{chr(10).join(flashes)}
{chunks}
run "$FASTBOOT" erase metadata
run "$FASTBOOT" erase userdata
run "$FASTBOOT" reboot
echo "FIRST INSTALL COMPLETED."
'''


def unix_update_script(chunk_count: int, platform: str) -> str:
    required = tuple(f"super.img.{index}" for index in range(1, chunk_count + 1)) + (
        "vbmeta.img",
        "vbmeta_system.img",
    )
    chunks = "\n".join(
        f'run "$FASTBOOT" flash super images/super.img.{index}'
        for index in range(1, chunk_count + 1)
    )
    return unix_fastboot_header(required, platform) + f'''echo "This updates an existing houji HyperOS 4 port without erasing data."
printf "Type UPDATE to continue: "
read -r CONFIRM
[ "$CONFIRM" = "UPDATE" ] || exit 0

run "$FASTBOOT" set_active a
{chunks}
run "$FASTBOOT" flash vbmeta_ab images/vbmeta.img
run "$FASTBOOT" flash vbmeta_system_ab images/vbmeta_system.img
run "$FASTBOOT" reboot
echo "UPDATE COMPLETED."
'''


def add_text(archive: zipfile.ZipFile, name: str, content: str, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, (2026, 8, 21, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    archive.writestr(info, content.encode("utf-8"))


def build_info_text(
    kind: str,
    base: Path,
    donor: Path,
    base_version: str,
    donor_version: str,
    profile_mode: str,
    warnings: list[str],
    experimental: bool,
) -> str:
    warning_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- none"
    return f'''HyperOS 4 China port for Xiaomi 14 (houji)
Package: {kind}
Base OTA: {base.name}
Base version: {base_version}
Donor OTA: {donor.name}
Donor version: {donor_version}
Compatibility mode: {profile_mode}
Experimental WW modem included: {"yes" if experimental else "no"}
Root: no
Custom recovery: no
AVB: algorithm NONE, flags 3

Warnings:
{warning_text}

This is an unofficial fastboot package. It cannot be installed through Xiaomi Updater or stock recovery.
The first-install package erases userdata. The update package does not erase userdata or metadata.
'''


def build_package_zip(
    output: Path,
    kind: str,
    base_images: Path,
    avb_images: Path,
    chunks: list[Path],
    fastboot_files: dict[str, Path],
    experimental_modem: Path | None,
    info_text: str,
) -> None:
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        for chunk in chunks:
            archive.write(chunk, f"images/{chunk.name}", compress_type=zipfile.ZIP_STORED)
        archive.write(avb_images / "vbmeta.img", "images/vbmeta.img", compress_type=zipfile.ZIP_STORED)
        archive.write(
            avb_images / "vbmeta_system.img",
            "images/vbmeta_system.img",
            compress_type=zipfile.ZIP_STORED,
        )
        if kind == "first-install":
            for name in FIRMWARE_PARTITIONS:
                if name in {"vbmeta", "vbmeta_system"}:
                    continue
                archive.write(
                    base_images / f"{name}.img",
                    f"images/{name}.img",
                    compress_type=zipfile.ZIP_STORED,
                )
            if experimental_modem:
                archive.write(
                    experimental_modem,
                    "images/modemfirmware_ww.img",
                    compress_type=zipfile.ZIP_STORED,
                )
            add_text(
                archive,
                "FLASH_FIRST_INSTALL_AND_ERASE.bat",
                windows_first_install_script(len(chunks), experimental_modem is not None),
            )
            add_text(
                archive,
                "linux_flash_first_install_and_erase.sh",
                unix_first_install_script(len(chunks), "linux", experimental_modem is not None),
                True,
            )
            add_text(
                archive,
                "macos_flash_first_install_and_erase.sh",
                unix_first_install_script(len(chunks), "macos", experimental_modem is not None),
                True,
            )
        else:
            add_text(archive, "FLASH_UPDATE_NO_WIPE.bat", windows_update_script(len(chunks)))
            add_text(
                archive,
                "linux_flash_update_no_wipe.sh",
                unix_update_script(len(chunks), "linux"),
                True,
            )
            add_text(
                archive,
                "macos_flash_update_no_wipe.sh",
                unix_update_script(len(chunks), "macos"),
                True,
            )
        for archive_name, source in fastboot_files.items():
            archive.write(source, archive_name, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        add_text(archive, "BUILD_INFO.txt", info_text)


def verify_zip(path: Path, kind: str, chunk_count: int, full_crc: bool) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        expected_chunks = {f"images/super.img.{index}" for index in range(1, chunk_count + 1)}
        actual_chunks = {name for name in names if re.fullmatch(r"images/super\.img\.\d+", name)}
        if actual_chunks != expected_chunks:
            raise RuntimeError(f"Wrong super chunk list in {path.name}")
        required = {"images/vbmeta.img", "images/vbmeta_system.img", "BUILD_INFO.txt"}
        if kind == "first-install":
            required.update(f"images/{name}.img" for name in FIRMWARE_PARTITIONS)
            required.add("FLASH_FIRST_INSTALL_AND_ERASE.bat")
        else:
            required.add("FLASH_UPDATE_NO_WIPE.bat")
            forbidden = [name for name in names if "erase" in name.lower() or "modem" in name.lower()]
            if forbidden:
                raise RuntimeError(f"Update package contains destructive or modem entries: {forbidden}")
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"ZIP is missing: {', '.join(missing)}")
        if full_crc:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC verification failed: {bad}")


def write_sidecars(
    output: Path,
    kind: str,
    base: Path,
    donor: Path,
    base_version: str,
    donor_version: str,
    profile_mode: str,
    chunks: list[Path],
    warnings: list[str],
    experimental: bool,
) -> None:
    digest = sha256(output)
    report = output.with_suffix(".report.txt")
    lines = [
        "HyperOS 4 houji port build report",
        f"package={kind}",
        f"output={output.name}",
        f"size={output.stat().st_size}",
        f"sha256={digest}",
        f"base={base.name}",
        f"base_version={base_version}",
        f"donor={donor.name}",
        f"donor_version={donor_version}",
        f"compatibility_mode={profile_mode}",
        f"super_chunks={len(chunks)}",
        f"userdata_erased={'yes' if kind == 'first-install' else 'no'}",
        f"metadata_erased={'yes' if kind == 'first-install' else 'no'}",
        f"experimental_ww_modem={'yes' if experimental else 'no'}",
        "root=no",
        "custom_recovery=no",
        "avb_algorithm=NONE",
        "avb_flags=3",
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


def clean_published(outputs: list[Path]) -> None:
    for output in outputs:
        for path in (
            output,
            output.with_suffix(".report.txt"),
            output.parent / f"{output.name}.sha256",
        ):
            if path.exists():
                path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a HyperOS 4 China port for Xiaomi 14 from two official full OTAs"
    )
    parser.add_argument("base", nargs="?", help="official houji OS3.0.305 full OTA ZIP")
    parser.add_argument("donor", nargs="?", help="official pudding HyperOS 4 full OTA ZIP")
    parser.add_argument(
        "--package",
        choices=("both", "first-install", "update"),
        default="both",
        help="which fastboot package to create",
    )
    parser.add_argument(
        "--experimental-modem",
        help="optional verified modemfirmware_ww.img or a ZIP containing it",
    )
    parser.add_argument("--keep-work", action="store_true", help="keep temporary build files")
    parser.add_argument(
        "--quick-verify",
        action="store_true",
        help="skip the final full ZIP CRC read (structure and hashes are still checked)",
    )
    args = parser.parse_args()

    config = load_config()
    manifest = load_json(MANIFEST_PATH)
    base, donor = choose_otas(config, args.base, args.donor)
    base_metadata, donor_metadata, base_version, donor_version = validate_otas(
        config, manifest, base, donor
    )
    del base_metadata, donor_metadata
    tools = tool_paths(config)
    check_environment(config, tools)
    check_free_space(config, ROOT)

    work_root = ROOT / "work"
    work = work_root / "current"
    work_root.mkdir(exist_ok=True)
    safe_remove_tree(work, work_root)
    work.mkdir()
    output_dir = resolve_from(ROOT, config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", base_version)
    safe_donor = re.sub(r"[^A-Za-z0-9._-]+", "_", donor_version)
    stem = f"houji_HyperOS4_CN_{safe_donor}_on_{safe_base}"
    requested = (
        ("first-install", "update")
        if args.package == "both"
        else (args.package,)
    )
    outputs = [
        output_dir
        / (f"{stem}_first-install_erase.zip" if kind == "first-install" else f"{stem}_update-no-wipe.zip")
        for kind in requested
    ]
    clean_published(outputs)

    try:
        log(f"Base:  {base}")
        log(f"Donor: {donor}")
        base_images = work / "base_images"
        donor_images = work / "donor_images"
        trees = work / "trees"
        base_assets = work / "base_assets"
        repacked = work / "repacked"
        avb_images = work / "avb"

        extract_payload(base, base_images, BASE_PAYLOAD_PARTITIONS, work)
        extract_payload(donor, donor_images, DONOR_PARTITIONS, work)
        extract_erofs_full(tools["extract_erofs"], donor_images, trees, DONOR_PARTITIONS)
        extract_erofs_full(tools["extract_erofs"], base_images, trees, ("vendor",))
        extract_base_product_files(tools["extract_erofs"], base_images / "product.img", base_assets)
        verify_base_assets(base_assets, manifest)

        profile_mode, warnings = apply_port_changes(
            trees, base_assets, donor_version, config, manifest
        )
        for warning in warnings:
            log("WARNING: " + warning)
        repack_erofs(tools["mkfs_erofs"], trees, repacked)
        patch_vbmeta(tools["avbtool"], base_images, avb_images, manifest)

        super_image = work / "super.sparse.img"
        build_super(config, tools, base_images, repacked, super_image)
        validate_super(config, tools, super_image, work / "lpdump.txt")
        chunks = split_super(config, super_image, work / "chunks", work)
        log(f"Sparse super chunks: {len(chunks)}")

        if "first-install" in requested:
            experimental = prepare_experimental_modem(
                args.experimental_modem, config, work, manifest
            )
        else:
            experimental = None
        if experimental:
            log("Experimental WW modem: included; installer confirmation is required")
        elif "first-install" in requested:
            log("Experimental WW modem: not included (CN-only first install)")
        else:
            log("Experimental WW modem: not used by no-wipe update packages")
        bundled_fastboot = fastboot_candidates(resolve_from(ROOT, config["tools_directory"]))

        for kind, output in zip(requested, outputs):
            includes_experimental_modem = (
                experimental is not None and kind == "first-install"
            )
            info = build_info_text(
                kind,
                base,
                donor,
                base_version,
                donor_version,
                profile_mode,
                warnings,
                includes_experimental_modem,
            )
            build_package_zip(
                output,
                kind,
                base_images,
                avb_images,
                chunks,
                bundled_fastboot,
                experimental,
                info,
            )
            verify_zip(output, kind, len(chunks), not args.quick_verify)
            write_sidecars(
                output,
                kind,
                base,
                donor,
                base_version,
                donor_version,
                profile_mode,
                chunks,
                warnings,
                includes_experimental_modem,
            )
            log(f"DONE: {output}")
            log(f"SHA-256: {sha256(output)}")
    except Exception:
        clean_published(outputs)
        raise
    finally:
        if not args.keep_work:
            safe_remove_tree(work, work_root)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Cancelled")
        raise SystemExit(130)
    except Exception as error:
        log(f"ERROR: {error}")
        raise SystemExit(1)
