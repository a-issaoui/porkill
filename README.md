<div align="center">
  <img src="logo.svg" width="740" alt="porkill logo">

  <br>

  **Process & Port Monitor // Kill with Precision**

  <br>

[![Python](https://img.shields.io/badge/Python-3.9%2B-39ff14?style=flat-square&logo=python&logoColor=white&labelColor=080c08)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux-39ff14?style=flat-square&logo=linux&logoColor=white&labelColor=080c08)](https://kernel.org/)
[![License](https://img.shields.io/badge/License-MIT-39ff14?style=flat-square&labelColor=080c08)](LICENSE)
[![AppImage](https://img.shields.io/badge/AppImage-ready-00ffcc?style=flat-square&labelColor=080c08)](https://appimage.org/)

*A cyberpunk-themed GUI for monitoring and killing processes by port — zero dependencies, pure stdlib.*

[Installation](#installation) · [Usage](#usage) · [Keyboard Shortcuts](#keyboard-shortcuts) · [Build from Source](#build-from-source)

</div>

---

## What is porkill?

`porkill` is a Linux desktop application for visualising every open network port alongside the process that owns it — and killing it with one click. It reads directly from `/proc/net/` with no external tools required, though it falls back to `ss` or `netstat` when available. The UI is built with `tkinter` and styled in a neon cyberpunk aesthetic with a live matrix-rain animation header.

No pip packages. No Electron. No telemetry. Just Python stdlib.

---

## Features

- **Live port table** — PID, process name, protocol (TCP/UDP), local address, port, and connection state
- **Process grouping** — ports are grouped by their parent process; kill the whole group in one action
- **Container awareness** — detects Docker, Podman, containerd, and related runtimes; labels ports accordingly
- **Dual kill signals** — send `SIGTERM` (graceful) or `SIGKILL -9` (force) with confirmation dialog
- **Real-time filter** — debounced live search across all columns
- **Auto-refresh** — configurable interval (2–120 s) with a live countdown; toggle on/off at any time
- **Sortable columns** — click any column header to sort ascending/descending; port column sorts numerically
- **Stats bar** — live counters for total ports, LISTEN sockets, and UDP entries
- **Sudo escalation** — gracefully retries kills with `sudo -n` when permission is denied
- **Animated header** — matrix rain, pulsing neon logo, and corner HUD rendered on a `tk.Canvas`
- **Zero third-party deps** — pure Python stdlib; only `python3-tk` is needed

---

## Installation

### Option A — One-Command Repository Setup (Professional)

The recommended way for seamless `apt` or `dnf` updates. Run one command to add the **Cloudsmith** repository, then install normally:

#### Debian / Ubuntu / Mint
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.deb.sh' | sudo -E bash
sudo apt install porkill
```

#### Fedora / RHEL / CentOS / AlmaLinux
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/a-issaoui/porkill/setup.rpm.sh' | sudo -E bash
sudo dnf install porkill
```

### Option B — Manual Native Packages (.deb / .rpm)

Download from [Releases](https://github.com/a-issaoui/porkill/releases/latest):

```bash
# Ubuntu / Debian / Mint
sudo apt install ./porkill_1.0.8_amd64.deb

# Fedora / RHEL / CentOS
sudo dnf install ./porkill-1.0.8-1.x86_64.rpm
```

### Option C — Snap Store

Instant install on Ubuntu and any distro with `snapd`:

```bash
sudo snap install porkill
```

### Option D — Flathub (Flatpak)

Coming soon to Flathub! You can build it locally using the provided manifest:

```bash
flatpak-builder --user --install --force-clean build-dir com.github.a_issaoui.porkill.yml
```

### Option E — AppImage (no install needed)

Download the latest release and run:

```bash
wget https://github.com/a-issaoui/porkill/releases/latest/download/porkill-v1.0.8-x86_64.AppImage
chmod +x porkill-v1.0.8-x86_64.AppImage
./porkill-v1.0.8-x86_64.AppImage
```

### Option F — Run directly from source

```bash
git clone https://github.com/a-issaoui/porkill.git
cd porkill
python3 porkill.py
```

**Prerequisites** (only for source/AppImage manual runs) — `python3-tk`:

| Distro | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora / RHEL | `sudo dnf install python3-tkinter` |
| Arch Linux | `sudo pacman -S tk` |
| openSUSE | `sudo zypper install python3-tk` |

> **Security Note:** Reading `/proc/net/` works without root, but sending signals to privileged processes requires it. Native packages handle this gracefully via internal escalation.

---

## Usage

```bash
sudo porkill [options]
```

| Flag | Default | Description |
|---|---|---|
| `--interval`, `-i` | `5` | Auto-refresh interval in seconds (min 2, max 120) |
| `--max-rows`, `-m` | `10000` | Maximum rows displayed in the table |
| `--no-auto-refresh`, `-n` | off | Start with auto-refresh disabled |
| `--log-level`, `-l` | `ERROR` | Logging verbosity: `DEBUG` `INFO` `WARNING` `ERROR` |

**Examples:**

```bash
sudo porkill                        # default — refresh every 5 s
sudo porkill --interval 2           # fastest refresh
sudo porkill --no-auto-refresh      # manual refresh only
sudo porkill --log-level DEBUG      # verbose output to terminal
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl + R` / `F5` | Refresh now |
| `Delete` | Send SIGTERM (graceful) to selected process |
| `Ctrl + K` | Send SIGKILL -9 (force) to selected process |
| `Ctrl + F` | Focus the filter input |
| `Escape` | Clear selection |
| `Ctrl + Q` | Quit |

---

## Build from Source

Build a self-contained AppImage locally:

```bash
# 1. Install appimagetool (one-time)
sudo wget -O /usr/local/bin/appimagetool \
  https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
sudo chmod +x /usr/local/bin/appimagetool

# 2. Build
chmod +x build.sh
./build.sh v1.0.0
```

Output: `porkill-v1.0.0-x86_64.AppImage` (~17 MB, bundles a full Python runtime)

**Build prerequisites:**

```bash
# Debian / Ubuntu
sudo apt install python3 python3-pip python3-tk libfuse2

# Fedora
sudo dnf install python3 python3-pip python3-tkinter fuse
```

### Automated GitHub Release

Push a version tag and GitHub Actions builds and publishes the AppImage automatically:

```bash
git tag v1.0.0
git push origin main --tags
```

Users can then download directly from the Releases page.

---

## Project Structure

```
porkill/
├── porkill.py              ← main application (single file, stdlib only)
├── entrypoint.py           ← AppImage entry script
├── AppRun                  ← custom AppImage launcher (bash)
├── porkill.desktop         ← desktop entry / AppImage metadata
├── porkill.png             ← icon (generated from SVG during build)
├── requirements.txt        ← empty — no third-party dependencies
├── build.sh                ← local AppImage build script
├── assets/
│   └── porkill.svg         ← source icon
└── .github/
    └── workflows/
        └── release.yml     ← CI: build + publish AppImage on git tag
```

---

## Compatibility Notes

- **Wayland** — `porkill` uses `tkinter` (X11). On Wayland, XWayland must be running, or set `GDK_BACKEND=x11` before launching.
- **ARM** — Multi-arch builds are supported. The GitHub Actions workflow automatically builds both `x86_64` and `aarch64` AppImages on every release.
- **Sudo** — Reading `/proc/net/` works without root, but sending signals to privileged processes requires it. Run without sudo to view all ports; kills on system processes will fall back to `sudo -n` internally.

---

## Author

Built by [a-issaoui](https://github.com/a-issaoui)

---

<div align="center">
  <sub>[ Process & Port Monitor // Kill with Precision ]</sub>
</div>
