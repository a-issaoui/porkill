<div align="center">
 <h1>⌬ PORKILL</h1>

<p><b>Monitor Processes · Kill Ports · Precision Control</b></p>



[![Version](https://img.shields.io/badge/VERSION-v2.0.3-39ff14?style=for-the-badge&labelColor=080c08)](https://github.com/a-issaoui/porkill/releases)
[![Platform](https://img.shields.io/badge/PLATFORM-LINUX-00ffcc?style=for-the-badge&labelColor=080c08)](#)
[![UI](https://img.shields.io/badge/UI-PyQt6-00e5ff?style=for-the-badge&labelColor=080c08)](#-installation)
[![License](https://img.shields.io/badge/LICENSE-MIT-ff00ff?style=for-the-badge&labelColor=080c08)](LICENSE)

<br>

*A high-performance, cyberpunk-themed GUI for Linux port management.*<br>
*Built with Python 3 and PyQt6 — no Electron, no bloat.*

<br>

[🚀 Install](#-installation) · [🕹️ Usage](#-usage) · [⌨️ Shortcuts](#-keyboard-shortcuts) · [🛠️ Build](#-build-from-source)

<br>

</div>

---

## ⚡ What is Porkill?

**Porkill** is a surgical tool for Linux developers and sysadmins. It provides a real-time visualization of every open network port alongside its owner process — allowing you to **identify and terminate** blocking services with a single click.

> [!TIP]
> **Zero Bloat Policy:** No `npm`, no Electron. Just Python 3 + PyQt6 — install once, run anywhere on Linux.

---

## 🔥 Key Features

| Feature | Description |
|:--------|:------------|
| **🔍 Real-time Engine** | Direct `/proc/net/` reads with `ss` JSON / legacy / `netstat` fallbacks. Auto-selects the fastest available method and caches it. |
| **📂 Process Grouping** | Automatically groups related ports under their parent process for batch operations. |
| **📦 Container Aware** | Native detection for **Docker**, **Podman**, **containerd**, **crun**, **runc**, **buildah**, and more. |
| **💀 Dual-Mode Kill** | Graceful `SIGTERM` or ruthless `SIGKILL -9` with PID-reuse safety check before sending. |
| **⚡ Smart Filtering** | 150 ms debounced live search across PID, Name, Port, Protocol, Address, and State — runs on a background thread. |
| **🎨 Neon Aesthetics** | Full dark theme with neon green / cyan / amber semantic colour coding and per-protocol badge cells. |
| **🛡️ Hybrid Elevation** | Styled GUI prompt for root access; falls back to CLI; escalates via `pkexec` then `sudo`. |
| **🧵 Thread-safe Core** | Versioned fetch-generation IDs and filter-version counters prevent stale worker results from corrupting the UI. |
| **🌍 Distro Universal** | Packaged for **APT**, **DNF**, **Snap**, **AppImage**, and **Flatpak**. |

---




## 🚀 Installation

### Option 1 — Official Repositories *(Recommended)*

**Ubuntu / Debian / Mint**
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.deb.sh' | sudo -E bash
sudo apt install porkill
```

**Fedora / RHEL / CentOS**
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.rpm.sh' | sudo -E bash
sudo dnf install porkill
```

---

### Option 2 — Universal Stores

| Store | Command |
|:------|:--------|
| **Snap** | `sudo snap install porkill` |
| **AppImage** | `wget https://github.com/a-issaoui/porkill/releases/download/v2.0.3/porkill-v2.0.3-x86_64.AppImage` |
| **Manual .deb** | `sudo apt install ./porkill_2.0.3_amd64.deb` |
| **Manual .rpm** | `sudo dnf install ./porkill-2.0.3-1.x86_64.rpm` |

---

### Option 3 — Run from Source

**Requires:** Python 3.9+ and PyQt6.

```bash
# 1. Install PyQt6
sudo apt install python3-pyqt6      # Debian / Ubuntu / Mint
sudo dnf install python3-qt6        # Fedora / RHEL
sudo pacman -S python-pyqt6         # Arch / Manjaro
pip install PyQt6                   # any distro / venv

# 2. Clone and run
git clone https://github.com/a-issaoui/porkill.git
cd porkill && python3 porkill.py
```

> [!NOTE]
> If PyQt6 is installed but the app fails with a native library error (`libGL`, `libxcb-*`), run:
> ```bash
> sudo apt install libgl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 \
>                  libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0
> ```
> Porkill prints a precise, distro-aware error with the exact command if this occurs.

---

## 🕹️ Usage

```bash
sudo porkill [options]
```

| Flag | Default | Effect |
|:-----|:-------:|:-------|
| `--interval`, `-i` | `2` | Auto-refresh rate in seconds (2 – 120) |
| `--max-rows`, `-m` | `2000` | Maximum rows displayed (internal cap: 10 000) |
| `--no-auto-refresh`, `-n` | off | Start with auto-refresh disabled |
| `--log-level`, `-l` | `WARNING` | Verbosity: `DEBUG` `INFO` `WARNING` `ERROR` |
| `--debug`, `-d` | off | Shorthand for `--log-level DEBUG` |
| `--version`, `-v` | — | Print version and exit |

> [!IMPORTANT]
> For best responsiveness on lower-end hardware, keep `--max-rows` ≤ 3 000. Filtering and sorting run on a background thread; the initial UI redraw for large row counts is the main bottleneck.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+R` / `F5` | Refresh now |
| `Ctrl+F` | Focus filter input |
| `Delete` | Send SIGTERM to selected process |
| `Ctrl+K` | Send SIGKILL to selected process |
| `Escape` | Clear selection |
| `Ctrl+Q` | Quit |

---

## 🛠️ Build from Source

```bash
# Generate .deb / .rpm (requires nfpm)
nfpm package -p deb
nfpm package -p rpm
```

---

## 📜 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

<div align="center">
<br>
<sub>⌬ Precise Port Termination · Pure Python Power · <a href="https://github.com/a-issaoui">a-issaoui</a></sub>
</div>