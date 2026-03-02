#!/usr/bin/env bash
# build.sh — Build porkill AppImage locally
# Usage: ./build.sh [version]
# Example: ./build.sh v1.0.0

set -euo pipefail

VERSION="${1:-v1.0.0}"
ARCH="${ARCH:-$(uname -m)}"
OUTPUT="porkill-${VERSION}-${ARCH}.AppImage"
APPDIR_WORK="porkill.AppDir"

echo "==> Building porkill AppImage ${VERSION} for ${ARCH}"

# ── Check dependencies ─────────────────────────────────────────────────────────
check_dep() {
  command -v "$1" &>/dev/null || { echo "ERROR: '$1' not found. $2"; exit 1; }
}

check_dep python3    "Install Python 3.9+"
check_dep pip3       "Install pip"

# tkinter check
python3 -c "import tkinter" 2>/dev/null || {
  echo "ERROR: tkinter not found."
  echo "  Debian/Ubuntu: sudo apt install python3-tk"
  echo "  Fedora:        sudo dnf install python3-tkinter"
  echo "  Arch:          sudo pacman -S tk"
  exit 1
}

# appimagetool is required for the repack step
check_dep appimagetool "Download from https://github.com/AppImage/AppImageKit/releases"

# ── Install python-appimage ────────────────────────────────────────────────────
echo "==> Installing python-appimage..."
pip3 install --quiet python-appimage cairosvg

# ── Generate PNG icon ──────────────────────────────────────────────────────────
echo "==> Generating icon..."
python3 -c "
import cairosvg
cairosvg.svg2png(
    url='assets/porkill.svg',
    write_to='porkill.png',
    output_width=256, output_height=256
)
"

# ── Build AppImage via python-appimage ─────────────────────────────────────────
echo "==> Building AppImage (this may take a minute)..."
PYTHON_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -m python_appimage build app --python-version "${PYTHON_VER}" .

BUILT=$(ls ./*.AppImage 2>/dev/null | head -1)
if [[ -z "${BUILT}" ]]; then
  echo "ERROR: No AppImage was created by python-appimage. Check output above."
  exit 1
fi

# ── Extract and patch AppRun ───────────────────────────────────────────────────
# python-appimage's generated AppRun can be misidentified as a Python script,
# causing the SyntaxError: "if [ -z "${APPIMAGE}" ]" read by the Python interpreter.
# We extract the AppImage, replace AppRun with a clean bash launcher, then repack.

echo "==> Extracting AppImage for patching..."
rm -rf "${APPDIR_WORK}"
"${BUILT}" --appimage-extract
mv squashfs-root "${APPDIR_WORK}"
chmod +x "${BUILT}"      # keep original around temporarily

echo "==> Injecting custom AppRun..."
cat > "${APPDIR_WORK}/AppRun" <<'APPRUN'
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
export LD_LIBRARY_PATH="${APPDIR}/usr/lib:${APPDIR}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${APPDIR}:${PYTHONPATH:-}"
export TCL_LIBRARY="${APPDIR}/usr/lib/tcl8.6"
export TK_LIBRARY="${APPDIR}/usr/lib/tk8.6"

exec "${PYTHON}" "${APPDIR}/entrypoint.py" "$@"
APPRUN

chmod +x "${APPDIR_WORK}/AppRun"

# ── Also ensure entrypoint.py and porkill.py are inside the AppDir ─────────────
echo "==> Copying application files into AppDir..."
cp entrypoint.py porkill.py porkill.png "${APPDIR_WORK}/"

# ── Repack the patched AppDir into a new AppImage ─────────────────────────────
echo "==> Repacking AppImage..."
rm -f "${BUILT}"                        # remove the unpatched one
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
