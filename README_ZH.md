<p align="center">
  <a href="README.md">English</a> ·
  <a href="README_RU.md">Русский</a> ·
  <strong>简体中文</strong>
</p>

<h1 align="center">小米 14（houji）HyperOS 4 移植包构建器</h1>

<p align="center">
  <img src="assets/banner-zh.svg" alt="小米 14 的 HyperOS 4 移植包构建器" width="100%">
</p>

<p align="center">
  <strong>小米 14（houji）的 HyperOS 4 更新包构建器</strong><br>
  使用小米 17（pudding）的完整中国版 OTA，为已安装的移植系统生成更新包。
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%2F%2011-1673D2?logo=windows11&logoColor=white">
  <img alt="设备" src="https://img.shields.io/badge/device-houji-4b79d8">
</p>

## 这是什么

这是我为小米 14 的 HyperOS 4 移植系统制作的一键更新包构建器。脚本会校验 OTA、提取所需分区、应用 `houji` 补丁、重新构建 `super`，最后生成不会格式化 `userdata` 的更新 ZIP。

当前移植底包是中国版 `OS3.0.305.0.WNCCNXM`。供体必须是小米 17（`pudding`）基于 Android 17 的完整 Recovery OTA。

构建结果不包含 Root，也不加入第三方 Recovery。小米中国版服务和功能不会被特意删除。

## 重要说明

这不是小米官方固件，也不是通用 ROM 转换工具。构建器只适用于 `houji` + `pudding`，并且需要已经准备好的第一版移植包。

- 刷机前请备份重要数据。
- 不要把 `pudding` 的原始 OTA 直接刷入小米 14。
- 更新包的设计目标是不清除用户数据，但移植系统始终存在风险。
- 如果设备、Android SDK、补丁哈希或 ZIP 结构不匹配，构建会立即停止。

## 快速开始

如果此文件夹与我们原来的 `_port_automation` 工作目录位于同一级：

1. 运行 `LINK_LOCAL_FILES.bat`。它会通过 NTFS junction 连接大型本地文件，不会重复复制。
2. 安装 Python 依赖：

   ```powershell
   py -m pip install -r requirements.txt
   ```

3. 将一个新的 `pudding` 完整 OTA 放入 `input`，或者把 ZIP 拖到 `BUILD_UPDATE.bat` 上。
4. 运行 `BUILD_UPDATE.bat`。
5. 更新 ZIP、构建报告和 SHA-256 文件会出现在 `output` 中。

也可以手动启动构建：

```powershell
python build_port_update.py "D:\ROMs\pudding-ota_full-OS4.x.x.x.zip"
```

如果是从 GitHub 普通克隆的仓库，需要先准备下方列出的本地文件。

## 环境要求

- Windows 10 或 11；
- Python 3.11 或更高版本；
- 安装了 `Ubuntu-22.04` 发行版的 WSL；
- WSL 内已安装 `simg2simg`；
- 构建期间约 32 GiB 可用空间；
- 完整 Recovery OTA，不能使用小型增量更新包。

还需要以下本地文件：

- 已验证的第一版移植包 ZIP；
- 小米 14 的四个基础镜像：`odm`、`system_dlkm`、`vendor` 和 `vendor_dlkm`；
- 从已准备移植包中提取的补丁文件；
- `extract.erofs.exe`、`mkfs.erofs.exe` 和 Linux 版 `lpmake`。

可以在 `config.local.json` 中覆盖本地路径。请参考 `config.example.json`。

## 固件下载

不同固件网站的更新时间可能不同。下载前请核对设备代号、地区和完整版本号。

### 提供 HyperOS 4 Beta 的来源

- **[Mi Firmware — HyperOS 4](https://mifirmware.com/xiaomi-hyperos-4/)** — 单独列出 HyperOS 4，包含中国 Beta 和 Recovery ROM。
- **[Xiaomi Miui Hellas — HyperOS 4 ROM 列表](https://xiaomi-miui.gr/hyperos-4-full-changelog-new-features/)** — 提供早期 HyperOS 4 中国 Beta 版本和下载链接。
- **[HyperOS Download by Tech Mukul](https://t.me/miui_hyperos_download)** — 发布新的 Stable/Beta 版本和镜像链接。建议尽量与小米官方 OTA 服务器地址进行核对。

### 稳定版和固件归档

- [MIUIROM — 小米 14（houji）](https://miuirom.org/phones/xiaomi-14) — Recovery、Fastboot 和 OTA，包括中国版 `OS3.0.305.0.WNCCNXM`。
- [XM Firmware Updater — houji](https://xmfirmwareupdater.com/archive/hyperos/houji/) — 未经修改的官方 HyperOS ROM 归档。
- [XiaomiROM — houji 中国版](https://xiaomirom.com/en/rom/xiaomi-14-houji-china-fastboot-recovery-rom/) — Stable 和较早的 Weekly/Beta 版本。

本构建器只接受 **`pudding` 的完整 Recovery OTA**。Fastboot ROM 或小型增量 OTA 无法使用。

## 为什么仓库里没有固件

ROM 压缩包、`super.img`、补丁、本地工具和构建结果可能占用数十 GB，并且可能包含小米的文件，因此它们已通过 `.gitignore` 排除。

Git 只跟踪构建器源码、哈希清单、文档和小型图片。本地 pre-commit hook 还会拒绝固件压缩包以及大于 5 MiB 的跟踪文件。

普通克隆后可使用以下命令启用它：

```powershell
git config core.hooksPath .githooks
```

## 许可证

你可以为个人、非商业用途学习、修改并使用此代码。未经书面许可，不得重新发布项目、出售构建结果、删除署名或将本项目冒充为自己的作品。完整条款请参阅 [LICENSE](LICENSE)。

本项目采用 source-available 许可证，并非标准开源许可证。

## 免责声明

本项目与小米无关。Xiaomi 和 HyperOS 商标归其各自所有者。刷入任何自定义软件均由用户自行承担风险。
