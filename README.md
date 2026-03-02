<div align="center">

<img src="assets/logo.svg" alt="porkill logo" width="740"/>

**Process & Port Monitor // Kill with Precision**

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

### Option A — AppImage (recommended, no install needed)

Download the latest release and run:

```bash
wget https://github.com/a-issaoui/porkill/releases/latest/download/porkill-x86_64.AppImage
chmod +x porkill-x86_64.AppImage
sudo ./porkill-x86_64.AppImage
```

To install system-wide:

```bash
sudo cp porkill-x86_64.AppImage /usr/local/bin/porkill
sudo chmod +x /usr/local/bin/porkill
porkill   # available everywhere
```

### Option B — Run directly from source

```bash
git clone https://github.com/a-issaoui/porkill.git
cd porkill
sudo python3 porkill.py
```

**Prerequisites** — only `python3-tk` (tkinter):

| Distro | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora / RHEL | `sudo dnf install python3-tkinter` |
| Arch Linux | `sudo pacman -S tk` |
| openSUSE | `sudo zypper install python3-tk` |
| Alpine | `sudo apk add python3-tkinter` |
| Gentoo | `USE=tk emerge dev-lang/python` |

> **Why sudo?** Reading `/proc/net/` works without root, but sending signals to privileged processes requires it. Run without sudo to view all ports; kills on system processes will fall back to `sudo -n` internally.

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

## Notes

- **Wayland** — porkill uses tkinter (X11). On Wayland, XWayland must be running, or set `GDK_BACKEND=x11` before launching.
- **ARM** — the default build targets `x86_64`. Add an `aarch64` runner in the GitHub Actions workflow for ARM builds.
- **AppImage size** — ~17 MB compressed. It bundles a full CPython runtime so no Python installation is required on the target machine.

---

## Author

Built by [a-issaoui](https://github.com/a-issaoui)

---

<div align="center">
<sub>[ Process & Port Monitor // Kill with Precision ]</sub>
</div>