<div align="center">
  <img src="banner.svg" width="800" alt="porkill banner">

  <h1>⌬ PORKILL</h1>

  ### **Monitor Processes. Kill Ports. Precision Control.**

  <p align="center">
    <img src="https://img.shields.io/badge/VERSION-v1.8.0-39ff14?style=for-the-badge&labelColor=080c08" alt="Version">
    <img src="https://img.shields.io/badge/PLATFORM-LINUX-00ffcc?style=for-the-badge&labelColor=080c08" alt="Platform">
    <img src="https://img.shields.io/badge/LICENSE-MIT-ff00ff?style=for-the-badge&labelColor=080c08" alt="License">
  </p>

  *A high-performance, cyberpunk-themed GUI for Linux port management. Built with Python stdlib.*

  [🚀 Quick Start](#-installation) • [🕹️ Usage](#-usage) • [⌨️ Shortcuts](#-keyboard-shortcuts) • [🛠️ Build](#-build-from-source)

</div>

---

## ⚡ What is Porkill?

**Porkill** is a surgical tool for Linux developers and sysadmins. It provides a real-time visualization of every open network port alongside its owner process — allowing you to **identify and terminate** blocking services with a single click.

> [!TIP]
> **Zero Bloat Policy:** No `pip` install, no `npm` dependencies, no Electron. Just pure Python and a slick `tkinter` UI that feels like it belongs in 2077.

---

## 🔥 Key Features

| Feature                  | Description |
|:-------------------------| :--- |
| **🔍 Real-time Engine**  | Direct `/proc/net/` reads for sub-millisecond updates without external tools. |
| **📂 Process Grouping**  | Automatically groups child/parent port clusters for batch termination. |
| **📦 Container Aware**   | Native detection for **Docker**, **Podman**, and **Kubernetes** runtimes. |
| **💀 Dual-Mode Kill**    | Graceful `SIGTERM` or ruthless `SIGKILL -9` with safe confirmation. |
| **⚡ Smart Filtering**    | Debounced live search across PID, Name, Port, and Connection State. |
| **🎨 Matrix Aesthetics** | Animated rain, neon gauges, and a pulsing corner HUD. |
| **🛡️ Hybrid Elevation** | Styled "Yes/No" prompt for root access with seamless user-mode fallback. |
| **🌍 Universal Support** | Available via **APT**, **DNF**, **Snap**, **AppImage**, and **Flatpak**. |

---

## ✅ Development Status

- [x] Implement Elevation Confirmation Dialog (v1.6.x)
- [x] Refine Elevation UX (v1.7.0)
- [x] Centralize Project Versioning (v1.8.0)
    - [x] Create root `VERSION` source-of-truth
    - [x] Update `porkill.py` and dynamic packaging

---

## 🚀 Installation

### 🌐 Option 1: Official Repositories (Recommended)
Stay updated automatically via your system's package manager.

#### **Ubuntu / Debian / Mint**
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.deb.sh' | sudo -E bash
sudo apt install porkill
```

#### **Fedora / RHEL / CentOS**
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.rpm.sh' | sudo -E bash
sudo dnf install porkill
```

---

### 📦 Option 2: Universal Stores

## Current Version: v1.8.0

[Porkill v1.8.0](https://github.com/a-issaoui/porkill/releases/tag/v1.8.0) is now officially released with **Centralized Project Versioning**. Update once, deploy everywhere!

| Store | Command |
| :--- | :--- |
| **Snap Store** | `sudo snap install porkill` |
| **AppImage** | `wget https://github.com/a-issaoui/porkill/releases/download/v1.8.0/porkill-v1.8.0-x86_64.AppImage` |
| **Manual .deb** | `sudo apt install ./porkill_1.8.0_amd64.deb` |
| **Manual .rpm** | `sudo dnf install ./porkill-1.8.0-1.x86_64.rpm` |

---

### 🐍 Option 3: Run from Source
```bash
git clone https://github.com/a-issaoui/porkill.git
cd porkill && python3 porkill.py
```

---

## 🕹️ Usage

```bash
sudo porkill [options]
```

| Flag | Default | Effect |
| :--- | :---: | :--- |
| `--interval`, `-i` | `5` | Refresh rate in seconds (2s - 120s) |
| `--max-rows`, `-m` | `10000` | Max display limit for low-spec machines |
| `--no-auto`, `-n` | `off` | Disable the auto-refresh engine on startup |

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + F` | Focus Search Bar |
| `Esc` | Clear Search / Deselect |
| `Delete` | Kill selected process (SIGTERM) |
| `Shift + Delete` | Force Kill (SIGKILL -9) |
| `Ctrl + R` | Force Refresh |
| `Ctrl + Q` | Quit |

---

## 🛠️ Build from Source

Porkill uses `nfpm` for packaging and `shiv` for standalone binaries.

```bash
# Install build tools
pip install shiv self-elevate

# Build standalone executable
shiv -e porkill.main -o porkill .

# Generate .deb / .rpm (requires nfpm)
nfpm package -p deb
nfpm package -p rpm
```

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">
  <img src="banner.svg" width="400" alt="porkill logo bottom">
  <p><i>Precise Port Termination. Pure Python Power.</i></p>
</div>
