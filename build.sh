#!/usr/bin/env bash
# build.sh — Build porkill AppImage locally
# Usage: ./build.sh [version]
# Example: ./build.sh v2.0.3
# Default version is read from the VERSION file in the repo root.

set -euo pipefail

VERSION="${1:-v$(cat VERSION 2>/dev/null || echo "0.0.0")}"
ARCH="${ARCH:-$(uname -m)}"
OUTPUT="porkill-${VERSION}-${ARCH}.AppImage"
APPDIR_WORK="porkill.AppDir"

echo "==> Building porkill AppImage ${VERSION} for ${ARCH}"

# ── Check dependencies ────────────────────────────────────────────────────────
check_dep() {
  command -v "$1" &>/dev/null || { echo "ERROR: '$1' not found. $2"; exit 1; }
}

check_dep python3      "Install Python 3.9+"
check_dep pip3         "Install pip"
check_dep appimagetool "Download from https://github.com/AppImage/AppImageKit/releases"

# Verify PyQt6 is available (replaces the old tkinter check)
python3 -c "import PyQt6.QtWidgets" 2>/dev/null || {
  echo "ERROR: PyQt6 not found."
  echo "  Debian/Ubuntu: sudo apt install python3-pyqt6"
  echo "  Fedora:        sudo dnf install python3-qt6"
  echo "  Arch:          sudo pacman -S python-pyqt6"
  echo "  Any distro:    pip install PyQt6"
  exit 1
}

# ── Install python-appimage + cairosvg ────────────────────────────────────────
echo "==> Installing python-appimage..."
pip3 install --quiet python-appimage cairosvg

# ── Generate PNG icon ─────────────────────────────────────────────────────────
echo "==> Generating icon..."
python3 - <<'PYEOF'
import cairosvg
cairosvg.svg2png(
    url="assets/porkill.svg",
    write_to="porkill.png",
    output_width=256, output_height=256,
)
PYEOF

# ── Build AppImage via python-appimage ────────────────────────────────────────
echo "==> Building AppImage (this may take a minute)..."
PYTHON_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -m python_appimage build app --python-version "${PYTHON_VER}" .

BUILT=$(ls ./*.AppImage 2>/dev/null | head -1)
if [[ -z "${BUILT}" ]]; then
  echo "ERROR: No AppImage was created by python-appimage. Check output above."
  exit 1
fi

# ── Extract and patch AppRun ──────────────────────────────────────────────────
# python-appimage's generated AppRun can be misidentified as a Python script,
# causing a SyntaxError when the Python interpreter reads the bash shebang line.
# We extract, replace AppRun with a clean bash launcher, then repack.

echo "==> Extracting AppImage for patching..."
rm -rf "${APPDIR_WORK}"
"${BUILT}" --appimage-extract
mv squashfs-root "${APPDIR_WORK}"

echo "==> Injecting custom AppRun..."
cat > "${APPDIR_WORK}/AppRun" << 'APPRUN'
#!/usr/bin/env bash
# porkill AppRun — sets up environment and launches via bundled Python

APPDIR="$(dirname "$(readlink -f "$0")")"

PYTHON="${APPDIR}/usr/bin/python3"
if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="$(command -v python3 2>/dev/null)" || {
        echo "ERROR: python3 not found inside AppImage or on PATH" >&2
        exit 1
    }
fi

export PATH="${APPDIR}/usr/bin:${PATH}"

# Include all lib subdirs so PyQt6 .so files are found on any architecture
export LD_LIBRARY_PATH="${APPDIR}/usr/lib:$(find "${APPDIR}/usr/lib" -maxdepth 1 -type d | tr '\n' ':')${LD_LIBRARY_PATH:-}"

export PYTHONPATH="${APPDIR}:${PYTHONPATH:-}"

# Force XCB/XWayland so window placement (move()) works correctly.
# XWayland is available on all major Wayland compositors.
if [[ -z "${QT_QPA_PLATFORM:-}" ]]; then
    SESSION="${XDG_SESSION_TYPE:-}"
    WAYLAND="${WAYLAND_DISPLAY:-}"
    if [[ "${SESSION}" == "wayland" || -n "${WAYLAND}" ]]; then
        export QT_QPA_PLATFORM=xcb
    fi
fi

exec "${PYTHON}" "${APPDIR}/entrypoint.py" "$@"
APPRUN

chmod +x "${APPDIR_WORK}/AppRun"

# ── Copy application files into AppDir ────────────────────────────────────────
echo "==> Copying application files into AppDir..."
cp entrypoint.py porkill.py porkill.png "${APPDIR_WORK}/"

# ── Repack ────────────────────────────────────────────────────────────────────
echo "==> Repacking AppImage..."
rm -f "${BUILT}"
ARCH="${ARCH}" appimagetool "${APPDIR_WORK}" "${OUTPUT}"
chmod +x "${OUTPUT}"

# ── Clean up ──────────────────────────────────────────────────────────────────
rm -rf "${APPDIR_WORK}"

echo ""
echo "✓ Built: ${OUTPUT}"
echo ""
echo "  Run locally:    sudo ./${OUTPUT}"
echo "  Install system: sudo cp ${OUTPUT} /usr/local/bin/porkill"
echo "                  sudo chmod +x /usr/local/bin/porkill"