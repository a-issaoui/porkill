# porkill — Packaging Guide

> Build and distribute `porkill` as AppImage, .deb, .rpm, Snap, or Flatpak.

---

## Repository Structure

```
porkill/
├── porkill.py                                  ← main application (PyQt6)
├── entrypoint.py                               ← AppImage / Flatpak entry script
├── porkill.desktop                             ← desktop entry
├── porkill.png                                 ← icon (256×256, auto-generated from SVG)
├── VERSION                                     ← single source of truth for version
├── requirements.txt                            ← PyQt6>=6.4.0
├── pyproject.toml                              ← pip / PyPI packaging
├── nfpm.yaml                                   ← .deb / .rpm via nfpm
├── snapcraft.yaml                              ← Snap package
├── com.github.a_issaoui.porkill.yml           ← Flatpak manifest
├── com.github.a_issaoui.porkill.metainfo.xml  ← AppStream metadata
├── build.sh                                    ← local AppImage build script
└── assets/
    └── porkill.svg                             ← source icon
```

---

## Prerequisites

### Runtime (end-user)
| Distro | Command |
|:-------|:--------|
| Debian / Ubuntu / Mint | `sudo apt install python3-pyqt6` |
| Fedora / RHEL | `sudo dnf install python3-qt6` |
| Arch / Manjaro | `sudo pacman -S python-pyqt6` |
| Any (pip) | `pip install PyQt6` |

If PyQt6 loads but native libraries are missing (`libGL`, `libxcb-*`):
```bash
# Debian / Ubuntu
sudo apt install libgl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 \
                 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0
```
porkill prints a distro-aware error with the exact fix command if this occurs.

### Build tools
```bash
# AppImage
pip install python-appimage cairosvg
# Download appimagetool from https://github.com/AppImage/AppImageKit/releases
# and place it on your PATH.

# .deb / .rpm
# Download nfpm from https://nfpm.goreleaser.com/install/

# Snap
sudo snap install snapcraft --classic

# Flatpak
sudo apt install flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

---

## Option A — AppImage (Automated GitHub Release)

Every version tag triggers a GitHub Actions workflow that builds the AppImage
on Ubuntu 22.04 and attaches it to a GitHub Release automatically.

```bash
# Bump VERSION, commit, then tag
echo "2.0.3" > VERSION
git add VERSION && git commit -m "chore: release v2.0.3"
git tag v2.0.3
git push origin main v2.0.3
```

Users download and run:
```bash
wget https://github.com/a-issaoui/porkill/releases/download/v2.0.3/porkill-v2.0.3-x86_64.AppImage
chmod +x porkill-v2.0.3-x86_64.AppImage
sudo ./porkill-v2.0.3-x86_64.AppImage
```

---

## Option B — AppImage (Local Build)

```bash
chmod +x build.sh
./build.sh              # reads version from VERSION file
./build.sh v2.0.3       # or pass explicitly
```

Output: `porkill-v2.0.3-x86_64.AppImage`

---

## Option C — .deb / .rpm via nfpm

```bash
# Set env vars nfpm.yaml references
export VERSION="2.0.3"
export ARCH="amd64"      # or arm64, x86_64 for rpm

nfpm package -p deb -f nfpm.yaml
nfpm package -p rpm -f nfpm.yaml
```

Output: `porkill_2.0.3_amd64.deb`, `porkill-2.0.3-1.x86_64.rpm`

---

## Option D — Snap

```bash
snapcraft                        # builds inside a VM/container
sudo snap install porkill_*.snap --dangerous --devmode
```

For release to the Snap Store:
```bash
snapcraft login
snapcraft upload porkill_*.snap --release=stable
```

---

## Option E — Flatpak

```bash
flatpak-builder --force-clean build-dir com.github.a_issaoui.porkill.yml
flatpak-builder --run build-dir com.github.a_issaoui.porkill.yml porkill-launcher

# Export for local install
flatpak-builder --repo=repo --force-clean build-dir com.github.a_issaoui.porkill.yml
flatpak --user remote-add --no-gpg-verify porkill-local repo
flatpak --user install porkill-local com.github.a_issaoui.porkill
```

---

## Running the AppImage

```bash
# Direct run
sudo ./porkill-v2.0.3-x86_64.AppImage

# Install system-wide
sudo cp porkill-v2.0.3-x86_64.AppImage /usr/local/bin/porkill
sudo chmod +x /usr/local/bin/porkill
porkill   # now available as a command
```

### CLI flags
```bash
sudo porkill --interval 3          # refresh every 3 seconds
sudo porkill --no-auto-refresh     # start paused
sudo porkill --log-level DEBUG     # verbose output
sudo porkill --max-rows 5000       # raise display limit
```

---

## Notes

- **AppImage size:** ~60–90 MB (bundles a full Python + PyQt6 runtime)
- **Architectures:** x86_64 by default; add an `aarch64` runner in the GitHub Actions
  workflow to produce ARM builds
- **Wayland:** porkill auto-detects Wayland sessions and forces `QT_QPA_PLATFORM=xcb`
  (XWayland) so window placement works correctly. XWayland is available on all major
  Wayland compositors (GNOME, KDE, Sway, Hyprland). No manual `GDK_BACKEND` override needed.
- **sudo:** Required for killing privileged processes. Without root, process names for
  system-owned sockets will be hidden. porkill prompts for elevation via pkexec/sudo
  on startup.