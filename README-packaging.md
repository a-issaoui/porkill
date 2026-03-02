# porkill — Packaging

> Build and distribute `porkill` as a self-contained AppImage that runs on any Linux distro.

---

## Repository Structure

```
porkill/
├── porkill.py              ← main application
├── entrypoint.py           ← AppImage entry script
├── porkill.desktop         ← desktop entry (AppImage metadata)
├── porkill.png             ← icon (auto-generated from SVG)
├── requirements.txt        ← no third-party deps (stdlib only)
├── build.sh                ← local build script
├── assets/
│   └── porkill.svg         ← source icon
└── .github/
    └── workflows/
        └── release.yml     ← auto-build + release on git tag
```

---

## Option A — Automated GitHub Release (recommended)

Every time you push a version tag, GitHub Actions will:
1. Build the AppImage on Ubuntu 22.04
2. Create a GitHub Release with the `.AppImage` attached

```bash
# Tag and push a release
git tag v1.0.0
git push origin v1.0.0
```

That's it. Users can then download and run:

```bash
wget https://github.com/YOUR_USER/porkill/releases/download/v1.0.0/porkill-v1.0.0-x86_64.AppImage
chmod +x porkill-v1.0.0-x86_64.AppImage
sudo ./porkill-v1.0.0-x86_64.AppImage
```

---

## Option B — Build Locally

```bash
chmod +x build.sh
./build.sh v1.0.0
```

Output: `porkill-v1.0.0-x86_64.AppImage`

**Prerequisites:**
- `python3` + `pip3`
- `python3-tk` (tkinter)
- `libfuse2` (to run AppImages on the build machine)

```bash
# Debian/Ubuntu
sudo apt install python3-tk libfuse2

# Fedora
sudo dnf install python3-tkinter fuse

# Arch
sudo pacman -S tk fuse2
```

---

## Running the AppImage

```bash
# Direct run
sudo ./porkill-v1.0.0-x86_64.AppImage

# Optional: install system-wide
sudo cp porkill-v1.0.0-x86_64.AppImage /usr/local/bin/porkill
sudo chmod +x /usr/local/bin/porkill
porkill  # now available as a command
```

### CLI flags (passed through to porkill)
```bash
sudo porkill --interval 3          # refresh every 3 seconds
sudo porkill --no-auto-refresh     # start paused
sudo porkill --log-level DEBUG
```

---

## Notes

- **Arch size:** ~30–60 MB (bundles a full Python runtime)
- **Architectures:** x86_64 by default; add `aarch64` runner in the workflow for ARM
- **Wayland:** porkill uses tkinter (X11). On Wayland, ensure `XWayland` is running or set `GDK_BACKEND=x11`
- **sudo:** Required for killing privileged processes. Running without sudo will still show all ports, but kills may fail and fall back to `sudo -n` internally
