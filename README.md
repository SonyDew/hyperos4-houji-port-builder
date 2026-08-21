<p align="center">
  <strong>English</strong> ·
  <a href="README_RU.md">Русский</a> ·
  <a href="README_ZH.md">简体中文</a>
</p>

<h1 align="center">HyperOS 4 Port Builder for Xiaomi 14</h1>

<p align="center">
  <img src="assets/banner-en.svg" alt="HyperOS 4 Houji Port Builder" width="100%">
</p>

<p align="center">
  <strong>Two official full OTAs in. A flashable China ROM port out.</strong><br>
  Xiaomi 14 <code>houji</code> base + Xiaomi 17 <code>pudding</code> donor, without a ready-made port.
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%2F%2011-1673D2?logo=windows11&logoColor=white">
  <img alt="Device" src="https://img.shields.io/badge/device-houji-4b79d8">
  <img alt="Input" src="https://img.shields.io/badge/input-2_official_OTAs-16a34a">
</p>

## What it does

This is a real one-click HyperOS 4 port builder for Xiaomi 14. It does **not** ask for an existing port ZIP.

The builder validates and extracts both official Recovery OTAs, combines the Xiaomi 14 hardware side with the Xiaomi 17 HyperOS 4 userspace, applies the verified `houji` compatibility profile, rebuilds EROFS and `super`, reconstructs AVB metadata, and checks every finished ZIP.

Required input:

- Xiaomi 14 China full OTA: `OS3.0.305.0.WNCCNXM` (`houji`, Android 16);
- Xiaomi 17 China full HyperOS 4 OTA (`pudding`, Android 17).

The build stays close to the China ROM. It does not add root or a custom recovery, and it does not intentionally remove Xiaomi China services, AI features, or applications.

## Output packages

One normal run produces two archives in `output`:

- `first-install_erase.zip` — the first installation. It flashes the Xiaomi 14 firmware and port, then erases `userdata` and `metadata`;
- `update-no-wipe.zip` — updates an already installed port without erasing user data. It never flashes a modem.

Use the update package only after the first package from this project is already running on the phone. Keep a backup even when using the no-wipe package.

## Modem modes

The first-install script reads the phone hardware region before flashing anything.

1. **China device** — uses the official modem from the selected Xiaomi 14 China OTA. No extra prompt is needed.
2. **Non-China device** — can use an optional experimental modem. It works, but it has not been tested for a long period. The script explains the risk and flashes nothing unless the user types `EXPERIMENTAL`.

The experimental modem is not published in this repository. Import a locally verified IMG or ZIP by dragging it onto `ADD_EXPERIMENTAL_MODEM.bat`, or pass it as the third file to `BUILD_PORT.bat`. If it is missing or declined on a non-China device, the first installation stops before any partition is changed.

## Quick start

1. Install [Python 3.11 or newer](https://www.python.org/downloads/) and WSL with Ubuntu 22.04:

   ```powershell
   wsl --install -d Ubuntu-22.04
   ```

2. Install the sparse-image helper inside Ubuntu:

   ```bash
   sudo apt update
   sudo apt install android-sdk-libsparse-utils
   ```

3. Install the Python dependencies:

   ```powershell
   py -m pip install -r requirements.txt
   ```

4. Prepare this local tool layout:

   ```text
   tools/
   ├─ avbtool.py
   ├─ erofs-utils/
   │  ├─ extract.erofs.exe
   │  └─ mkfs.erofs.exe
   └─ android-tools-static/android-tools-static/
      ├─ lpmake
      ├─ lpdump
      └─ simg2img
   ```

   Useful upstream projects: [erofs-utils](https://github.com/erofs/erofs-utils), [android-tools-static](https://github.com/meator/android-tools-static), and [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools). If the tools already exist elsewhere, run `LINK_LOCAL_FILES.bat "D:\path\to\tools"` to create a local junction.

5. Put the two official full OTA ZIPs in `input` and run `BUILD_PORT.bat`. You can also drag both ZIPs onto the batch file.

6. Extract the resulting package and run `FLASH_FIRST_INSTALL_AND_ERASE.bat` while the unlocked Xiaomi 14 is in Fastboot mode. Put the official `fastboot.exe` beside the script, or add Platform Tools to `PATH`.

Allow at least **48 GiB of free disk space** while building. Paths and WSL distribution can be overridden in `config.local.json`; use `config.example.json` as a reference.

## Version support

`OS4.0.0.9.XPCCNXM` has an exact, hash-checked compatibility profile. Its camera, framework and services deltas are applied only when every source hash matches.

A newer `pudding` full OTA can be tried without an existing port: the builder falls back to the stock `houji` camera and keeps the new donor framework unchanged. It prints a prominent warning because a structurally valid package is not the same as a device-tested port. New releases should be tested before public distribution and can later receive their own verified profile.

The Xiaomi 14 base is intentionally locked to `OS3.0.305.0.WNCCNXM` for now.

## Firmware downloads

Always verify the codename, region, full version and OTA type before building.

### Sources that publish HyperOS 4 Beta packages

- **[Mi Firmware — HyperOS 4](https://mifirmware.com/xiaomi-hyperos-4/)**
- **[Xiaomi Miui Hellas — HyperOS 4 list](https://xiaomi-miui.gr/hyperos-4-full-changelog-new-features/)**
- **[HyperOS Download channel](https://t.me/miui_hyperos_download)** — community mirrors; prefer an official Xiaomi OTA-server link when available.

### Xiaomi 14 firmware archives

- [MIUIROM — Xiaomi 14 (houji)](https://miuirom.org/phones/xiaomi-14)
- [XM Firmware Updater — houji archive](https://xmfirmwareupdater.com/archive/hyperos/houji/)
- [XiaomiROM — houji China](https://xiaomirom.com/en/rom/xiaomi-14-houji-china-fastboot-recovery-rom/)

Only full Recovery OTA packages work. Fastboot ROMs and small incremental updates are rejected.

## Safety notes

- An unlocked bootloader is required. The builder disables AVB verification in the generated `vbmeta` images; relocking the bootloader with this port can brick the device.
- Never flash the original `pudding` OTA directly on Xiaomi 14.
- First installation permanently erases apps, settings and internal-storage files.
- The scripts verify the connected product, required images and every fastboot command. A failed command stops the sequence immediately.
- This project is unofficial and device-specific. You accept the flashing risk.

## Repository size and license

OTA archives, extracted partitions, tools, modem images and build output are excluded by `.gitignore`. Git tracks only the builder, small binary deltas, hash manifests, documentation and graphics. Enable the included size guard after cloning:

```powershell
git config core.hooksPath .githooks
```

The code is source-available for personal, non-commercial use. Reuploading the project, selling builds, removing attribution, or claiming the work as your own is not allowed without written permission. See [LICENSE](LICENSE).

This project is not affiliated with Xiaomi. Xiaomi and HyperOS are trademarks of their respective owners.
