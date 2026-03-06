#!/usr/bin/env python3
"""
porkill — Process & Port Monitor / Killer
A production-ready GUI application for monitoring and managing network ports and processes.

Usage:
    sudo python3 porkill.py [options]

Options:
    --interval SECONDS    Auto-refresh interval (default: 2, min: 2, max: 120)
    --max-rows N          Maximum rows to display (default: 2000)
    --no-auto-refresh     Disable auto-refresh on startup
    --log-level LEVEL     Logging level: DEBUG, INFO, WARNING, ERROR (default: WARNING)
    --debug               Enable DEBUG logging (alias for --log-level DEBUG)
    --version             Show program version and exit

Keyboard Shortcuts:
    Ctrl+R / F5    Refresh
    Delete         Send SIGTERM to selected process
    Ctrl+K         Send SIGKILL to selected process
    Ctrl+F         Focus filter input
    Escape         Clear selection
    Ctrl+Q         Quit

Author: a-issaoui
GitHub: github.com/a-issaoui
"""
from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple

# ============================================================================
# Logging
# ============================================================================

def setup_logging(level: int = logging.WARNING) -> None:
    """Configure root logger if no handlers are present yet."""
    if not logging.root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    else:
        logging.root.setLevel(level)

logger = logging.getLogger("porkill")

# ============================================================================
# PyQt6 Import
# ============================================================================

def _check_pyqt6() -> None:
    """
    Validate PyQt6 availability with actionable diagnostics.

    Uses importlib.util.find_spec to detect absence without importing, then
    probes PyQt6.QtWidgets via importlib.import_module to surface broken
    C-extension installs — both cheaper than the previous approach of importing
    15+ symbols into a function scope that was immediately discarded.  (Fix #12)

    Distinguishes between:
      - PyQt6 not installed at all
      - PyQt6 installed but a native library (xcb, GL, …) is missing
      - Unexpected errors (prints the real traceback and exits)
    """
    import importlib.util as _ilu
    import importlib as _il

    # ── Case 1: PyQt6 Python package simply absent ────────────────────────
    if _ilu.find_spec("PyQt6") is None:
        _die_no_pyqt6()
        return   # unreachable; for type-checker

    # ── Case 2: Package present — probe for broken C extensions ──────────
    try:
        _il.import_module("PyQt6.QtWidgets")
    except ImportError as exc:
        msg = str(exc)
        import traceback as _tb
        _die_broken_pyqt6(msg, _tb.format_exc())
    except Exception as exc:   # pragma: no cover  # pylint: disable=broad-exception-caught
        import traceback as _tb
        _die_broken_pyqt6(str(exc), _tb.format_exc())



# Module-level constant — was previously re-created as a local dict on every
# _detect_distro() call (Fix #20).
_DISTRO_FAMILY: Dict[str, str] = {
    # apt / Debian family
    "ubuntu": "ubuntu", "debian": "debian", "linuxmint": "ubuntu",
    "pop":    "ubuntu", "elementary": "ubuntu", "zorin": "ubuntu",
    "kali":   "debian", "raspbian": "debian", "parrot": "debian",
    # dnf / Red Hat family
    "fedora": "fedora", "rhel": "rhel", "centos": "rhel",
    "rocky":  "rhel",   "almalinux": "rhel", "ol": "rhel",
    "nobara": "fedora",
    # pacman / Arch family
    "arch":     "arch", "manjaro": "arch", "garuda": "arch",
    "endeavouros": "arch", "artix": "arch", "cachyos": "arch",
    # zypper / SUSE family
    "opensuse-leap": "opensuse", "opensuse-tumbleweed": "opensuse",
    "opensuse": "opensuse", "sles": "opensuse",
    # apk / Alpine
    "alpine": "alpine",
    # emerge / Gentoo
    "gentoo": "gentoo",
    # nix
    "nixos": "nixos",
    # void
    "void": "void",
}


def _detect_distro() -> str:
    """
    Return a canonical distro family tag by reading /etc/os-release.

    Checks both ID and ID_LIKE so derivatives resolve to their family:
      Linux Mint  → ubuntu   Pop!_OS    → ubuntu
      Rocky Linux → rhel     AlmaLinux  → rhel
      Garuda      → arch     EndeavourOS → arch
      openSUSE Leap/Tumbleweed → opensuse
    """
    try:
        fields: Dict[str, str] = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                fields[k.strip().lower()] = v.strip().strip('"').lower()

        # ID takes priority, then walk ID_LIKE tokens left-to-right
        candidates = [fields.get("id", "")]
        candidates += fields.get("id_like", "").split()
        for cand in candidates:
            if cand in _DISTRO_FAMILY:
                return _DISTRO_FAMILY[cand]
    except OSError:
        pass
    return ""


# ── Per-distro package tables ─────────────────────────────────────────────────

_PKG_PYQT6: Dict[str, str] = {
    "ubuntu":   "sudo apt install python3-pyqt6",
    "debian":   "sudo apt install python3-pyqt6",
    "fedora":   "sudo dnf install python3-qt6",
    "rhel":     "sudo dnf install python3-qt6",          # EPEL may be needed
    "arch":     "sudo pacman -S python-pyqt6",
    "opensuse": "sudo zypper install python3-qt6",
    "alpine":   "sudo apk add py3-pyqt6",
    "gentoo":   "USE='gui widgets' emerge dev-python/PyQt6",
    "void":     "sudo xbps-install python3-PyQt6",
    "nixos":    "nix-env -iA nixpkgs.python3Packages.pyqt6",
}

_PKG_NATIVE: Dict[str, str] = {
    "ubuntu":   "sudo apt install libgl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0",
    "debian":   "sudo apt install libgl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0",
    "fedora":   "sudo dnf install mesa-libGL xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms",
    "rhel":     "sudo dnf install mesa-libGL xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms",
    "arch":     "sudo pacman -S mesa xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms",
    "opensuse": "sudo zypper install Mesa-libGL libxcb-cursor0 xcb-util-wm xcb-util-image xcb-util-keysyms",
    "alpine":   "sudo apk add mesa-gl xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms",
    "gentoo":   "emerge x11-libs/libxcb media-libs/mesa",
    "void":     "sudo xbps-install MesaLib libxcb xcb-util-cursor xcb-util-wm",
    "nixos":    "# Add pkgs.libGL pkgs.xorg.libxcb to your environment.systemPackages",
}

_RHEL_EPEL_NOTE = (
    "  Note (RHEL/CentOS) : python3-qt6 requires EPEL.\n"
    "                        sudo dnf install epel-release && sudo dnf install python3-qt6"
)


def _die_no_pyqt6() -> None:
    """PyQt6 Python package is not installed at all."""
    distro   = _detect_distro()
    sys_cmd  = _PKG_PYQT6.get(distro, "")

    in_venv  = bool(
        sys.prefix != sys.base_prefix
        or os.environ.get("VIRTUAL_ENV")
        or os.environ.get("CONDA_PREFIX")
    )
    venv_path = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX") or sys.prefix

    SEP = "  " + "─" * 63

    lines = ["", "  porkill requires PyQt6, which is not installed.", "", SEP]

    if in_venv:
        # Inside a venv — system packages are usually invisible here.
        # pip is always the right answer; mention the venv path clearly.
        lines += [
            f"  Active venv : {venv_path}",
            "  Install     : pip install PyQt6",
            "",
            "  PyQt6 must be installed inside the active virtual environment.",
            "  System-level packages (apt/dnf/pacman) are not visible here.",
        ]
        if sys_cmd:
            lines += [
                "",
                "  To use the system package instead, deactivate the venv first:",
                f"    deactivate && {sys_cmd}",
            ]
    elif sys_cmd:
        # Known distro outside a venv — lead with the native package manager.
        lines += [
            f"  Install     : {sys_cmd}",
            "  or via pip  : pip install PyQt6",
        ]
        if distro == "rhel":
            lines += ["", _RHEL_EPEL_NOTE]
    else:
        # Unknown / unsupported distro — show pip + a condensed reference table.
        lines += [
            "  Install     : pip install PyQt6",
            "",
            "  Common package-manager alternatives:",
            "    apt      sudo apt install python3-pyqt6",
            "    dnf      sudo dnf install python3-qt6",
            "    pacman   sudo pacman -S python-pyqt6",
            "    zypper   sudo zypper install python3-qt6",
            "    apk      sudo apk add py3-pyqt6",
        ]

    lines += [SEP, ""]
    sys.exit("\n".join(lines))


def _die_broken_pyqt6(msg: str, traceback_text: str) -> None:
    """PyQt6 is installed but a native C library dependency is missing or broken."""
    distro     = _detect_distro()
    native_cmd = _PKG_NATIVE.get(distro, "")

    # Try to guess which specific library is missing from the error message
    lib_guess = ""
    for fragment, label in [
        ("libGL",       "OpenGL (libGL)"),
        ("libEGL",      "EGL (libEGL)"),
        ("xcb",         "XCB / X11 libraries"),
        ("libxcb",      "XCB / X11 libraries"),
        ("wayland",     "Wayland libraries"),
        ("libvulkan",   "Vulkan (libvulkan)"),
    ]:
        if fragment.lower() in msg.lower():
            lib_guess = label
            break

    in_venv   = bool(sys.prefix != sys.base_prefix or os.environ.get("VIRTUAL_ENV"))
    pip_cmd   = "pip install --force-reinstall PyQt6"

    SEP = "  " + "─" * 63

    lines = [
        "",
        "  PyQt6 is installed but a native library dependency is missing.",
        "",
        f"  Error : {msg}",
    ]
    if lib_guess:
        lines += [f"  Likely : {lib_guess} not found on this system"]

    lines += ["", SEP, "  Possible fixes:"]

    if native_cmd:
        lines += [f"  1. Install missing libs  →  {native_cmd}"]
        if distro == "nixos":
            lines += ["     (add to environment.systemPackages and rebuild)"]
        n = 2
    else:
        n = 1

    lines += [
        f"  {n}. Reinstall PyQt6        →  {pip_cmd}",
    ]

    if in_venv:
        lines += [
            "",
            "  Note: native libs must be installed system-wide (not inside the venv).",
        ]

    lines += [
        "",
        "  Run with --debug for the full Python traceback.",
        SEP, "",
    ]

    if "--debug" in sys.argv or "-d" in sys.argv:
        lines += ["  Full traceback:", "", traceback_text]

    sys.exit("\n".join(lines))


_check_pyqt6()

# Re-import into module namespace now that we know it works
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QSize, QModelIndex, QPoint, QRect, QEvent, QThreadPool, QRunnable  # noqa: E402,F401  # pylint: disable=no-name-in-module
from PyQt6.QtGui import (                                                  # noqa: E402,F401  # pylint: disable=no-name-in-module
    QColor, QFont, QFontDatabase, QPainter, QPen, QBrush,
    QKeySequence, QShortcut, QPalette,
)
from PyQt6.QtWidgets import (                                              # noqa: E402,F401  # pylint: disable=no-name-in-module
    QApplication, QMainWindow, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
    QFrame, QSizePolicy,
    QMessageBox, QAbstractItemView,
)

# ============================================================================
# Configuration & Versioning
# ============================================================================

_VERSION_RE = re.compile(r"^\d+\.\d+[\d.]*$")


def get_version() -> str:
    for base in (Path(__file__).parent, Path(__file__).parent.parent):
        vf = base / "VERSION"
        try:
            if vf.exists():
                v = vf.read_text().strip()
                if _VERSION_RE.match(v):
                    return v
        except OSError:
            pass
    try:
        cv = Path.home() / ".config" / "porkill" / "version"
        if cv.exists():
            v = cv.read_text().strip()
            if _VERSION_RE.match(v):
                return v
    except OSError:
        pass
    return "2.0.3"

VERSION = get_version()

_SS_PID_RE       = re.compile(r"pid=(\d+)")
_SS_NAME_RE      = re.compile(r'"([^"]+)"')
_SS_PORT_RE      = re.compile(r":(\d+)$")
_NETSTAT_PORT_RE = re.compile(r":(\d+)$")
_NETSTAT_PROC_RE = re.compile(r"(\d+)/(.*)")


class Config:
    MAX_ROWS: int             = 2_000
    MAX_RAW_ROWS: int         = 10_000
    SUBPROCESS_TIMEOUT: float = 5.0
    FILTER_DEBOUNCE_MS: int   = 150
    FLASH_DURATION_MS: int    = 3_000
    INODE_CACHE_TTL: float    = 30.0
    REFRESH_AFTER_KILL_MS: int = 900
    MAX_PARENT_TRAVERSAL: int = 6

    # ── High-impact elite palette — controlled intensity ─────────────────
    #    Dark void underneath  ·  Pure neon on top  ·  No pastels
    BG: str        = "#050805"   # deeper black
    BG2: str       = "#0b120d"   # panel base
    BG3: str       = "#0f1a11"   # alternate row
    BG4: str       = "#142018"   # hover / active field
    GRP_BG: str    = "#050805"   # group header = void (flush)
    # ── Neon accents — full luminance ────────────────────────────────────
    NEON: str      = "#00ff88"   # pure neon green — primary accent
    NEON_DIM: str  = "#00a855"   # structural neon (borders, separators)
    NEON_GLOW: str = "#00ffcc"   # secondary accent / glow / selected
    # ── Semantic roles ────────────────────────────────────────────────────
    RED: str       = "#ff3b3b"   # error / SIGKILL
    AMBER: str     = "#ffdd00"   # warning / UDP / SIGTERM
    AMBER_DIM: str = "#7a5e00"   # dim warning (TIME_WAIT etc.)
    CYAN: str      = "#00e5ff"   # TCP / ESTABLISHED
    CYAN_DIM: str  = "#1a4455"   # kernel bg hint
    # ── Foreground hierarchy — never pastel ───────────────────────────────
    FG: str        = "#c8e8d0"   # primary text — slightly cool white
    FG2: str       = "#6a7a70"   # secondary — muted but readable
    FG3: str       = "#4a5e52"   # tertiary — hints only
    # ── Structure ─────────────────────────────────────────────────────────
    BORDER: str    = "#182e1e"   # subtle panel borders
    SEL_BG: str    = "#1a2e20"   # selected row bg — dark surface, not neon flood
    SEL_FG: str    = "#ffffff"   # selected row text — full white for max contrast
    SEL_BORDER: str= "#00ff88"   # selected row left border = full neon
    HDR_FG: str    = "#4a5e52"   # column header — recedes
    # ── Protocol badge colours ────────────────────────────────────────────
    TCP_COL: str   = "#050805"   # TCP text (black on cyan badge)
    UDP_COL: str   = "#050805"   # UDP text (black on neon badge)
    TCP_BG: str    = "#00e5ff"   # TCP badge bg — full cyan
    UDP_BG: str    = "#00ff88"   # UDP badge bg — full neon
    # Protocol cell backgrounds in the tree (subtle pill BG per cell) — Fix #19
    TCP_BADGE_BG: str = "#0d3545"
    UDP_BADGE_BG: str = "#0d3318"


# ============================================================================
# Data Models
# ============================================================================

@dataclass(frozen=True)
class PortRow:
    pid: str; name: str; proto: str; addr: str
    port: str; state: str; group: str


@dataclass(frozen=True)
class ProcessInfo:
    pid: str; comm: str
    ppid: Optional[str] = None
    cmdline: str = ""


class InodeCacheEntry(NamedTuple):
    inode_map: Dict[str, Tuple[str, str]]
    timestamp: float


# ============================================================================
# Constants
# ============================================================================

_TCP_STATES: Dict[str, str] = {
    "01": "ESTABLISHED", "02": "SYN_SENT",  "03": "SYN_RECV",
    "04": "FIN_WAIT1",   "05": "FIN_WAIT2", "06": "TIME_WAIT",
    "07": "CLOSE",       "08": "CLOSE_WAIT","09": "LAST_ACK",
    "0A": "LISTEN",      "0B": "CLOSING",
}
_HELPER_NAMES: Set[str] = {
    "rootlessport", "slirp4netns", "pasta", "passt", "vpnkit-bridge", "rootlesskit",
}
_CONTAINER_RUNTIMES: Set[str] = {
    "podman", "docker", "containerd", "conmon", "crun", "runc",
    "buildah", "skopeo", "nerdctl",
}


# ============================================================================
# Utility / Proc helpers  (identical to tkinter version)
# ============================================================================

_resolved_mono_font: Optional[str] = None  # Module-level cache

def resolve_mono_font() -> str:
    """Resolve the best available monospace font. Result is cached — QFontDatabase.families()
    is expensive (loads all font metadata) and the result never changes within a session."""
    global _resolved_mono_font  # pylint: disable=global-statement
    if _resolved_mono_font is not None:
        return _resolved_mono_font
    candidates = [
        "JetBrains Mono", "Fira Code", "Hack", "Inconsolata",
        "DejaVu Sans Mono", "Liberation Mono", "Noto Mono", "FreeMono",
        "Nimbus Mono PS", "Courier New", "Monospace",
    ]
    available = set(QFontDatabase.families())
    for c in candidates:
        if c in available:
            _resolved_mono_font = c
            return c
    _resolved_mono_font = "Monospace"
    return _resolved_mono_font


def hex_to_ipv4(h: str) -> str:
    try:
        return socket.inet_ntoa(struct.pack("<I", int(h, 16)))
    except (ValueError, struct.error):
        return h


def hex_to_ipv6(h: str) -> str:
    try:
        raw = b"".join(struct.pack("<I", int(h[i:i+8], 16)) for i in range(0, 32, 8))
        return f"[{socket.inet_ntop(socket.AF_INET6, raw)}]"
    except (ValueError, OSError):
        return h




# Module-level address label map — was re-allocated inside fmt_addr() on every
# call (hot loop in _rebuild_tree).  Fix #6 / #5.
_ADDR_MAP: Dict[str, str] = {
    # IPv4
    "0.0.0.0":          "ALL IFACES",
    "127.0.0.1":        "LOCALHOST",
    "*":                "ALL IFACES",   # wildcard bind
    # IPv6 native
    "::":               "ALL IPv6",
    "::1":              "LOCAL IPv6",
    "[::1]":            "LOCAL IPv6",
    "[::]":             "ALL IPv6",
    # IPv6-mapped IPv4 (the ones Qt/ss commonly returns)
    "[::ffff:127.0.0.1]": "LOCALHOST",
    "::ffff:127.0.0.1":   "LOCALHOST",
    "[::ffff:0.0.0.0]":   "ALL IFACES",
    "::ffff:0.0.0.0":     "ALL IFACES",
    "[::ffff:0:0]":       "ALL IFACES",
    "::ffff:0:0":         "ALL IFACES",
    # multicast / link-local
    "224.0.0.1":        "MULTICAST",
    "224.0.0.251":      "MULTICAST",
    "224.0.0.252":      "MULTICAST",
    "255.255.255.255":  "BROADCAST",
}


def fmt_addr(addr: str) -> str:
    """Replace raw IPs / IPv6 with human-readable semantic labels."""
    # Fast path: direct hit (covers bracketed forms already in the map)
    label = _ADDR_MAP.get(addr)
    if label:
        return label
    # Normalize bracketed forms not in map and retry
    stripped = addr.strip("[]")
    label = _ADDR_MAP.get(stripped)
    if label:
        return label
    # IPv6-mapped IPv4 pattern: ::ffff:A.B.C.D
    if stripped.startswith("::ffff:") and stripped.count(".") == 3:
        ipv4 = stripped[7:]
        return _ADDR_MAP.get(ipv4, ipv4)
    return addr


def read_proc_file(pid: str, filename: str) -> str:
    try:
        return Path(f"/proc/{pid}/{filename}").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def read_proc_cmdline(pid: str) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


# ── Lightweight caches for user/cmd lookups (avoids repeated /proc reads) ──
_uid_name_cache: Dict[int, str] = {}
_pid_user_cache: Dict[str, str] = {}
_pid_cmd_cache:  Dict[str, str] = {}
_pid_cmdline_cache: Dict[str, str] = {}   # raw cmdline cache shared by get_proc_cmd / get_proc_cmd_full (Fix #1)


def get_proc_user(pid: str) -> str:
    """Return the username owning process pid, or '—' for kernel/unknown."""
    if pid == "—":
        return "kernel"
    if pid in _pid_user_cache:
        return _pid_user_cache[pid]
    uid: Optional[int] = None
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Uid:"):
                uid = int(line.split()[1])
                break
    except OSError:
        pass
    if uid is None:
        result = "—"
    else:
        if uid not in _uid_name_cache:
            try:
                import pwd as _pwd
                _uid_name_cache[uid] = _pwd.getpwuid(uid).pw_name
            except (KeyError, ImportError):
                _uid_name_cache[uid] = str(uid)
        result = _uid_name_cache[uid]
    _pid_user_cache[pid] = result
    return result


def get_proc_cmd(pid: str) -> str:
    """Return full command line for display: exe basename + all args."""
    if pid == "—":
        return "—"
    if pid in _pid_cmd_cache:
        return _pid_cmd_cache[pid]
    raw = read_proc_cmdline(pid)
    _pid_cmdline_cache[pid] = raw   # also populate raw cache for get_proc_cmd_full (Fix #1)
    if not raw:
        result = "—"
    else:
        parts = raw.split()
        # Replace argv[0] with just the basename so long paths don't eat the column,
        # but keep all arguments intact so the full invocation is visible.
        exe = Path(parts[0]).name if parts else parts[0]
        args = " ".join(parts[1:]) if len(parts) > 1 else ""
        result = f"{exe} {args}".strip() if args else exe
    _pid_cmd_cache[pid] = result
    return result


def get_proc_cmd_full(pid: str) -> str:
    """Return the raw unmodified cmdline for use in tooltips.

    Uses _pid_cmdline_cache populated by get_proc_cmd so no extra /proc read
    is needed when both functions are called for the same PID.  (Fix #1)
    """
    if pid == "—":
        return "—"
    if pid in _pid_cmdline_cache:
        return _pid_cmdline_cache[pid] or "—"
    raw = read_proc_cmdline(pid)
    _pid_cmdline_cache[pid] = raw
    return raw if raw else "—"


def get_parent_pid(pid: str) -> Optional[str]:
    for line in read_proc_file(pid, "status").splitlines():
        if line.startswith("PPid:"):
            parts = line.split()
            return parts[1] if len(parts) >= 2 else None
    return None


# Cache for container runtime ancestry traversal — PID→runtime name.
# Process parent relationships are stable for the lifetime of a process,
# so the result never needs to be invalidated until the PID caches are cleared.
# (Fix #10)
_container_runtime_cache: Dict[str, Optional[str]] = {}


def find_container_runtime(pid: str, max_depth: int = Config.MAX_PARENT_TRAVERSAL) -> Optional[str]:
    if pid in _container_runtime_cache:
        return _container_runtime_cache[pid]
    current = pid
    result: Optional[str] = None
    for _ in range(max_depth):
        ppid = get_parent_pid(current)
        if not ppid or ppid in ("0", "1"):
            break
        name = read_proc_file(ppid, "comm")
        if name in _CONTAINER_RUNTIMES:
            result = name
            break
        current = ppid
    _container_runtime_cache[pid] = result
    return result


def enrich_process_name(pid: str, raw_name: str) -> str:
    if raw_name not in _HELPER_NAMES:
        return raw_name
    cmdline = read_proc_cmdline(pid)
    hint = ""
    if m := re.search(r"--container-name[= ](\S+)", cmdline):
        hint = m.group(1)
    runtime = find_container_runtime(pid)
    if runtime:
        return f"{runtime}[{hint}]" if hint else f"{runtime}→{raw_name}"
    return raw_name


def resolve_group_name(pid: str, comm: str) -> str:
    if pid == "—":
        return "kernel"
    if comm in _HELPER_NAMES:
        # Use the detected container runtime name; fall back to the raw comm so
        # we never mis-label a Docker/nerdctl/etc. helper as "podman".  (Fix #3)
        return find_container_runtime(pid) or comm
    return comm


# ============================================================================
# Port Data Fetching  (identical to tkinter version)
# ============================================================================

# ── Module-level constants (constructed once, reused across all rebuilds) ────

_STATE_DISPLAY_MAP: Dict[str, str] = {
    "LISTEN":      "● LISTEN",
    "ESTABLISHED": "● ESTAB ",
    "UNCONN":      "○ UNCONN",
    "TIME_WAIT":   "◌ T_WAIT",
    "CLOSE_WAIT":  "◌ C_WAIT",
    "FIN_WAIT1":   "◌ FIN_W1",
    "FIN_WAIT2":   "◌ FIN_W2",
    "SYN_SENT":    "→ SYN   ",
    "SYN_RECV":    "← SYN   ",
    "—":           "  —     ",
}

# Pre-format port numbers on demand — avoids a 4MB startup allocation for 65K
# entries when only ~100 distinct ports are seen per session.  (Fix #7)
@functools.lru_cache(maxsize=4096)
def _fmt_port(port: int) -> str:
    return f"{port:>5}"


# Module-level cached port sort key — avoids allocating a fresh tuple for every
# comparison during list.sort() on up to 2 000 rows.  (Fix #18)
@functools.lru_cache(maxsize=4096)
def _port_sort_key(port: str) -> Tuple[int, int]:
    return (0, int(port)) if port.isdigit() else (1, 0)



class PortDataFetcher:
    def __init__(self) -> None:
        self._inode_cache: Optional[InodeCacheEntry] = None
        self._cache_lock = threading.Lock()
        self._cached_method: Optional[Callable[[], Optional[List[PortRow]]]] = None  # working fetch method

    def _get_inode_map(self) -> Dict[str, Tuple[str, str]]:
        with self._cache_lock:
            now = time.monotonic()
            if (self._inode_cache is not None
                    and now - self._inode_cache.timestamp < Config.INODE_CACHE_TTL):
                # Return a shallow copy — prevents mutation while iterating in caller
                return dict(self._inode_cache.inode_map)
            inode_map = self._build_inode_map()
            self._inode_cache = InodeCacheEntry(inode_map, now)
            return dict(inode_map)

    @staticmethod
    def _build_inode_map() -> Dict[str, Tuple[str, str]]:
        """Build inode→(pid,comm) map using os.scandir for 2-3x speedup over Path.iterdir.
        os.scandir avoids redundant stat() calls and uses getdents64 more efficiently."""
        inode_map: Dict[str, Tuple[str, str]] = {}
        try:
            with os.scandir("/proc") as proc_it:
                pids = [e.name for e in proc_it if e.name.isdigit() and e.is_dir(follow_symlinks=False)]
        except OSError as e:
            logger.warning("Could not list /proc: %s", e)
            return inode_map
        for pid in pids:
            try:
                with os.scandir(f"/proc/{pid}/fd") as fd_it:
                    for fd_entry in fd_it:
                        try:
                            target = os.readlink(fd_entry.path)
                        except OSError:
                            continue
                        if not target.startswith("socket:["):
                            continue
                        inode = target[8:-1]
                        if inode not in inode_map:
                            inode_map[inode] = (pid, read_proc_file(pid, "comm") or "unknown")
            except (OSError, PermissionError):
                continue
        return inode_map

    def _parse_proc_net(self) -> List[PortRow]:
        inode_map = self._get_inode_map()
        rows: List[PortRow] = []
        seen: Set[str] = set()
        for path, proto, is_v6 in [
            ("/proc/net/tcp", "TCP", False), ("/proc/net/tcp6", "TCP", True),
            ("/proc/net/udp", "UDP", False), ("/proc/net/udp6", "UDP", True),
        ]:
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()[1:]
            except OSError:
                continue
            for line in lines:
                parts = line.split()
                if len(parts) < 10:
                    continue
                try:
                    hex_addr, hex_port = parts[1].rsplit(":", 1)
                    port = str(int(hex_port, 16))
                    state_hex = parts[3].upper()
                    inode = parts[9]
                except (ValueError, IndexError):
                    continue
                if inode in seen:
                    continue
                seen.add(inode)
                addr  = hex_to_ipv6(hex_addr) if is_v6 else hex_to_ipv4(hex_addr)
                state = _TCP_STATES.get(state_hex, state_hex) if proto == "TCP" else "—"
                pid, name = inode_map.get(inode, ("—", "kernel"))
                name = enrich_process_name(pid, name)
                rows.append(PortRow(pid=pid, name=name, proto=proto, addr=addr,
                                    port=port, state=state, group=resolve_group_name(pid, name)))
        return rows

    @staticmethod
    def _parse_ss_output_json() -> Optional[List[PortRow]]:
        try:
            result = subprocess.run(["ss", "-tulpn", "-J"], capture_output=True,
                                    text=True, timeout=Config.SUBPROCESS_TIMEOUT, check=False)
            if result.returncode != 0 or not result.stdout:
                return None
            data = json.loads(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
            logger.debug("ss JSON failed: %s", e)
            return None
        rows: List[PortRow] = []
        seen: Set[Tuple[str, str, str]] = set()
        for proto_key in ("tcp", "udp"):
            for entry in data.get(proto_key, []):
                local = entry.get("local", {})
                addr  = local.get("addr", "")
                port  = str(local.get("port", ""))
                state = entry.get("state", "—")
                pn    = "TCP" if proto_key == "tcp" else "UDP"
                for u in (entry.get("users", []) or [{"name": "kernel", "pid": "—"}]):
                    pid  = str(u.get("pid", "—"))
                    name = u.get("name", "unknown")
                    key  = (pid, port, pn)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(PortRow(pid=pid, name=enrich_process_name(pid, name),
                                        proto=pn, addr=addr, port=port, state=state,
                                        group=resolve_group_name(pid, name)))
        return rows or None

    @staticmethod
    def _parse_ss_output_legacy() -> Optional[List[PortRow]]:
        try:
            result = subprocess.run(["ss", "-tulpn"], capture_output=True,
                                    text=True, timeout=Config.SUBPROCESS_TIMEOUT, check=False)
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        rows: List[PortRow] = []
        seen: Set[Tuple[str, str, str]] = set()
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            proc_field = next((p for p in reversed(parts) if "pid=" in p), "")
            if not proc_field and "(" in parts[-1] and ")" in parts[-1]:
                proc_field = parts[-1]
            local = parts[4] if len(parts) > 4 else parts[-1]
            m = _SS_PORT_RE.search(local)
            if not m:
                continue
            port = m.group(1)
            addr = local[:-(len(port) + 1)]
            pids  = _SS_PID_RE.findall(proc_field)
            names = _SS_NAME_RE.findall(proc_field)
            if not pids:
                pids, names = ["—"], names or ["kernel"]
            else:
                names = names or ["?"] * len(pids)
                names.extend([names[-1]] * (len(pids) - len(names)))
            pn    = "TCP" if "tcp" in parts[0].lower() else "UDP"
            state = parts[1]
            for pid, name in zip(pids, names):
                key = (pid, port, pn)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(PortRow(pid=pid, name=enrich_process_name(pid, name),
                                    proto=pn, addr=addr, port=port, state=state,
                                    group=resolve_group_name(pid, name)))
        return rows or None

    @staticmethod
    def _parse_netstat_output() -> Optional[List[PortRow]]:
        try:
            result = subprocess.run(["netstat", "-tulpn"], capture_output=True,
                                    text=True, timeout=Config.SUBPROCESS_TIMEOUT, check=False)
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        rows: List[PortRow] = []
        seen: Set[Tuple[str, str, str]] = set()
        for line in result.stdout.splitlines():
            if not line.startswith(("tcp", "udp")):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            proto = "TCP" if parts[0].upper().startswith("TCP") else "UDP"
            local = parts[3]
            state = parts[5] if proto == "TCP" else "—"
            proc  = parts[-1] if proto == "TCP" else (parts[5] if len(parts) >= 6 else "—")
            m = _NETSTAT_PORT_RE.search(local)
            if not m:
                continue
            port = m.group(1)
            addr = local[:-(len(port) + 1)]
            pm = _NETSTAT_PROC_RE.match(proc)
            pid, name = (pm.group(1), pm.group(2)) if pm else ("—", proc)
            key = (pid, port, proto)
            if key in seen:
                continue
            seen.add(key)
            rows.append(PortRow(pid=pid, name=enrich_process_name(pid, name),
                                proto=proto, addr=addr, port=port, state=state,
                                group=resolve_group_name(pid, name)))
        return rows or None

    def fetch(self) -> Tuple[List[PortRow], Optional[str]]:
        # Cache the working method after first successful call — avoids trying
        # failed methods (e.g. ss not installed) on every 2-second refresh.
        if self._cached_method is not None:
            rows = self._cached_method()
            if rows:
                return rows, None
            # Method stopped working (e.g. binary removed) — fall through to rediscover
            self._cached_method = None

        _methods = [
            ("ss JSON",   self._parse_ss_output_json),
            ("ss legacy", self._parse_ss_output_legacy),
            ("netstat",   self._parse_netstat_output),
            ("/proc/net", self._parse_proc_net),
        ]
        for label, method in _methods:
            rows = method()
            if rows:
                logger.info("Fetched %d rows via %s", len(rows), label)
                self._cached_method = method
                return rows, None
        return [], "Could not fetch port data from any source"


# ============================================================================
# Process Management  (identical to tkinter version)
# ============================================================================

def validate_pid(pid: str) -> Tuple[bool, int, str]:
    if not pid or not pid.isdigit():
        return False, 0, f"Invalid PID format: {pid!r}"
    pid_int = int(pid)
    if pid_int <= 0:
        return False, 0, f"PID must be positive, got {pid_int}"
    return True, pid_int, ""


def send_signal_to_pid(pid: str, sig: signal.Signals) -> Tuple[bool, str]:
    """Send signal; escalation intentionally omitted — use pkexec/sudo at launch."""
    is_valid, pid_int, error = validate_pid(pid)
    if not is_valid:
        return False, error
    try:
        os.kill(pid_int, sig)
        logger.info("Sent %s to PID %d", sig.name, pid_int)
        return True, ""
    except ProcessLookupError:
        return False, f"PID {pid_int} no longer exists"
    except PermissionError:
        if os.geteuid() == 0:
            return False, f"Permission denied for PID {pid_int} even as root"
        return False, (f"Permission denied for PID {pid_int}. "
                       "Restart with sudo / pkexec for full privileges.")
    except OSError as exc:
        return False, str(exc)


# ============================================================================
# Global Qt Stylesheet
# ============================================================================

def build_stylesheet(mono: str) -> str:
    c = Config
    return f"""
* {{ font-family: "{mono}", "Monospace"; color: {c.FG}; }}
QMainWindow, QDialog, QWidget {{ background: {c.BG}; }}

/* ── Labels — strict hierarchy ────────────────────────────────────── */
QLabel {{ background: transparent; color: {c.FG2}; }}
QLabel#title    {{ font-size: 15pt; font-weight: bold; color: {c.NEON};
                   letter-spacing: 3px; }}
QLabel#version  {{ font-size: 8pt;  color: {c.NEON_GLOW}; padding-bottom: 1px; }}
QLabel#subtitle {{ font-size: 8pt;  color: {c.FG2}; }}
QLabel#author   {{ font-size: 8pt;  color: {c.FG3}; }}
QLabel#status   {{ font-size: 8pt;  color: {c.FG2}; padding-right: 4px; }}
QLabel#info     {{ font-size: 9pt;  color: {c.FG};  }}
QLabel#filter_label {{ font-size: 8pt; font-weight: bold; color: {c.FG2};
                       letter-spacing: 2px; }}
QLabel#hint     {{ font-size: 8pt;  color: {c.FG3}; }}
QLabel#badge_label  {{ font-size: 7pt; color: {c.FG2}; letter-spacing: 2px; }}
QLabel#badge_value  {{ font-size: 14pt; font-weight: bold; }}
QLabel#ctrl_label   {{ font-size: 8pt; color: {c.FG2}; letter-spacing: 1px; }}

/* ── Accent lines ─────────────────────────────────────────────────── */
QFrame#accent_top {{ background: {c.NEON};     max-height: 2px; border: none; }}
QFrame#accent_mid {{ background: {c.BORDER};   max-height: 1px; border: none; }}
QFrame#accent_bot {{ background: {c.NEON_DIM}; max-height: 1px; border: none; }}
QFrame#sep        {{ background: {c.BORDER};   max-height: 1px; border: none; }}
QFrame#filter_pip {{ background: {c.NEON};     max-width: 3px;  border: none; }}
QFrame#ctrl_sep   {{ background: {c.BORDER};   max-width: 1px;  border: none;
                     min-height: 20px; max-height: 20px; }}

/* ── Named containers ─────────────────────────────────────────────── */
QWidget#banner        {{ background: {c.BG};  border-bottom: 1px solid {c.BORDER}; }}
QWidget#banner_content {{ background: {c.BG};  border: none; }}
QWidget#ctrl_bar      {{ background: {c.BG};  border-bottom: 1px solid {c.BORDER}; }}
QWidget#filter_bar    {{ background: {c.BG2}; border-bottom: 1px solid {c.BORDER}; }}
QWidget#action_bar    {{ background: {c.BG};  border-top:    1px solid {c.BORDER}; }}

/* ── Filter input ─────────────────────────────────────────────────── */
QLineEdit {{
    background: {c.BG2}; color: {c.FG};
    border: 1px solid {c.BORDER}; border-radius: 2px;
    padding: 3px 10px; font-size: 9pt;
    selection-background-color: {c.NEON}; selection-color: {c.BG};
}}
QLineEdit:focus {{ border-color: {c.NEON}; background: {c.BG4}; color: {c.NEON}; }}
QLineEdit:!focus {{ color: {c.FG2}; }}

/* ── SpinBox ──────────────────────────────────────────────────────── */
QSpinBox {{
    background: {c.BG2}; color: {c.NEON};
    border: 1px solid {c.BORDER}; border-radius: 2px;
    padding: 2px 4px; font-size: 8pt;
}}
QSpinBox:focus {{ border-color: {c.NEON}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {c.BG3}; border: none; width: 13px;
}}

/* ── CheckBox ─────────────────────────────────────────────────────── */
QCheckBox {{ color: {c.FG2}; font-size: 8pt; spacing: 5px; }}
QCheckBox::indicator {{
    width: 12px; height: 12px;
    background: {c.BG2}; border: 1px solid {c.NEON_DIM}; border-radius: 2px;
}}
QCheckBox::indicator:checked {{ background: {c.NEON}; border-color: {c.NEON}; }}
QCheckBox::indicator:hover   {{ border-color: {c.NEON}; }}

/* ── Tree viewport — explicit dark fill, no white bleed ──────────── */
QAbstractScrollArea::viewport {{
    background: {c.BG2};
    border: none;
}}

/* ── Tree — the main canvas ───────────────────────────────────────── */
QTreeWidget {{
    background: {c.BG2};
    color: {c.FG}; border: none; font-size: 9pt;
    show-decoration-selected: 1; outline: 0;
}}
QTreeWidget::item {{ padding: 2px 4px; border: none; min-height: 24px; }}
QTreeWidget::item:selected {{
    background: {c.SEL_BG}; color: #ffffff;
    padding: 2px 4px; min-height: 24px; border: none;
}}
QTreeWidget::item:selected:active {{
    background: {c.SEL_BG}; color: #ffffff;
    padding: 2px 4px; min-height: 24px; border: none;
}}
QTreeWidget::item:selected:!active {{
    background: {c.SEL_BG}; color: #ffffff;
    padding: 2px 4px; min-height: 24px; border: none;
}}
QTreeWidget::item:hover:!selected {{
    background: {c.BG4}; padding: 2px 4px; min-height: 24px;
}}

/* ── Header — quiet but legible ───────────────────────────────────── */
QHeaderView::section {{
    background: {c.BG};
    color: {c.FG2};
    font-size: 7pt; font-weight: bold; letter-spacing: 3px;
    padding: 6px 10px; border: none;
    border-bottom: 1px solid {c.NEON_DIM};
    border-right: 1px solid {c.BORDER};
    text-transform: uppercase;
}}
QHeaderView::section:hover {{ color: {c.NEON}; }}
QHeaderView::section:first {{ border-left: none; }}

/* ── Branch lines ─────────────────────────────────────────────────── */
QTreeWidget::branch {{ background: {c.BG2}; }}
QTreeWidget::branch:!has-children:!has-siblings,
QTreeWidget::branch:!has-children:has-siblings {{
    border-left: 1px solid {c.BORDER};
}}

/* ── Scrollbar — ultra-minimal, 4px flush right ───────────────────── */
QScrollBar:vertical {{
    background: transparent; width: 4px; border: none; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c.BG4}; min-height: 32px; border-radius: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {c.NEON_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; width: 0; border: none; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; border: none; }}
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {{ border: none; background: none; image: none; }}

/* ── MessageBox ───────────────────────────────────────────────────── */
QMessageBox {{ background: {c.BG}; }}
QMessageBox QPushButton {{
    background: {c.BG2}; color: {c.NEON};
    border: 1px solid {c.BORDER}; padding: 5px 18px;
    font-size: 8pt; font-weight: bold; min-width: 80px;
}}
QMessageBox QPushButton:hover   {{ border-color: {c.NEON_DIM}; color: {c.NEON_GLOW}; }}
QMessageBox QPushButton:pressed {{ background: {c.NEON}; color: {c.BG}; }}

/* ── Tooltip — match dark theme ───────────────────────────────────── */
QToolTip {{
    background: {c.BG2};
    color: {c.FG};
    border: 1px solid {c.NEON_DIM};
    padding: 4px 8px;
    font-family: "Monospace"; font-size: 8pt;
    border-radius: 2px;
    opacity: 240;
}}
"""


# ============================================================================
# Signals (thread → UI)
# ============================================================================

class FetchSignals(QObject):
    """Created once in main thread; emitted from worker thread via queued connection."""
    finished = pyqtSignal(object, object)  # rows (list|tuple), Optional[str]

class FilterSignals(QObject):
    """Created once in main thread; emitted from worker thread via queued connection."""
    finished = pyqtSignal(int, object, object, object)  # version, rows(tuple), sel_key, sel_group


# ============================================================================
# Worker QRunnables — module-level to avoid re-creating the class body on
# every _launch_fetch / _do_apply_filter call.  (Fix #11)
# ============================================================================

class _FetchTask(QRunnable):
    """Background task: fetch port rows and emit via FetchSignals."""

    def __init__(
        self,
        fetcher: "PortDataFetcher",
        sigs: FetchSignals,
        shutdown: "threading.Event",
        on_done: "Callable[[], None]",
    ) -> None:
        super().__init__()
        self._fetcher  = fetcher
        self._sigs     = sigs
        self._shutdown = shutdown
        self._on_done  = on_done

    def run(self) -> None:
        rows: List[PortRow] = []
        error: Optional[str]
        try:
            rows, error = self._fetcher.fetch()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("Unexpected fetch error")
            error = str(exc)
        finally:
            self._on_done()   # always reset _fetching, even on exception
        if not self._shutdown.is_set():
            self._sigs.finished.emit(tuple(rows), error)  # type: ignore[union-attr]


class _FilterTask(QRunnable):
    """Background task: filter + sort rows and emit via FilterSignals."""

    def __init__(
        self,
        version: int,
        query: str,
        source: List[PortRow],
        sort_col: int,
        sort_asc: bool,
        sel_key: Any,
        sel_group: Any,
        sigs: FilterSignals,
        shutdown: "threading.Event",
    ) -> None:
        super().__init__()
        self._version   = version
        self._query     = query
        self._source    = source
        self._sort_col  = sort_col
        self._sort_asc  = sort_asc
        self._sel_key   = sel_key
        self._sel_group = sel_group
        self._sigs      = sigs
        self._shutdown  = shutdown

    def run(self) -> None:
        query = self._query
        if not query:
            visible = list(self._source)
        else:
            visible = [
                r for r in self._source
                if query in r.pid or query in r.name.lower() or
                   query in r.proto.lower() or query in r.addr.lower() or
                   query in r.port or query in r.state.lower()
            ]
        if len(visible) > Config.MAX_ROWS:
            visible = visible[:Config.MAX_ROWS]
        # Sort — uses module-level cached key functions (Fix #18)
        sc = self._sort_col
        if sc == _COL_PORT:
            key_fn: Callable[[PortRow], Any] = lambda r: _port_sort_key(r.port)
        elif sc == _COL_PID:
            key_fn = lambda r: (0, int(r.pid)) if r.pid.isdigit() else (1, 0)
        else:
            attrs = ("pid", "name", "proto", "addr", "port", "state")
            attr  = attrs[sc]
            key_fn = lambda r: getattr(r, attr, "").lower()
        visible.sort(key=key_fn, reverse=not self._sort_asc)
        if not self._shutdown.is_set():
            self._sigs.finished.emit(  # type: ignore[union-attr]
                self._version, tuple(visible), self._sel_key, self._sel_group
            )


# ============================================================================
# UI Components
# ============================================================================

def _accent_line(parent: QWidget, name: str = "accent_top") -> QFrame:
    f = QFrame(parent)
    f.setObjectName(name)
    # NoFrame — let background color do the visual work.
    # HLine uses the platform style engine which flashes white/grey for one paint
    # before the stylesheet overrides it.
    f.setFrameShape(QFrame.Shape.NoFrame)
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    f.setFixedHeight(2 if name == "accent_top" else 1)
    _color = Config.NEON if name == "accent_top" else Config.BORDER
    f.setStyleSheet(f"background: {_color}; border: none;")
    return f


class StatBadge(QWidget):
    def __init__(self, label: str, color: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMinimumWidth(58)
        self.setMinimumHeight(44)   # badge_label(~12px) + badge_value(~22px) + margins(10px)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)   # add vertical padding so content isn't crushed
        lay.setSpacing(0)
        lbl = QLabel(label, self)
        lbl.setObjectName("badge_label")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        self._val = QLabel("0", self)
        self._val.setObjectName("badge_value")
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._val.setStyleSheet(f"color: {color};")
        lay.addWidget(self._val)

    def set(self, n: int) -> None:
        self._val.setText(str(n))


class KillButton(QPushButton):
    """Minimal action button — quiet until hovered, sharp on press."""

    def __init__(self, text: str, color: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self._color = color
        self.setFixedSize(210, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {Config.BG2}; color: {color};
                border: 1px solid {Config.BORDER};
                font-family: "Monospace"; font-size: 8pt; font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: {Config.BG4}; border-color: {color};
                color: {color};
            }}
            QPushButton:pressed {{
                background: {color}; color: {Config.BG}; border-color: {color};
            }}
        """)




class LogoBanner(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.setMinimumHeight(66)   # accent_top(2) + content(60) + accent_mid(1) + padding
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_accent_line(self, "accent_top"))

        content = QWidget(self)
        content.setObjectName("banner_content")   # distinct name — avoids double-matching QWidget#banner
        content.setMinimumHeight(60)              # prevents collapse when outer layout shrinks it
        cl = QHBoxLayout(content)
        cl.setContentsMargins(24, 10, 24, 10)

        # Left: title block — use content as parent (not self) so labels paint inside
        # content's coordinate space and are not occluded by content's background.  (Fix)
        left = QVBoxLayout()
        left.setSpacing(1)
        tr = QHBoxLayout()
        tr.setSpacing(10)
        t = QLabel("PORKILL", content)
        t.setObjectName("title")
        tr.addWidget(t)
        v = QLabel(f"v{VERSION}", content)
        v.setObjectName("version")
        v.setAlignment(Qt.AlignmentFlag.AlignBottom)
        tr.addWidget(v)
        tr.addStretch()
        left.addLayout(tr)
        sub = QLabel("Process & Port Monitor  ·  Kill with Precision", content)
        sub.setObjectName("subtitle")
        left.addWidget(sub)
        cl.addLayout(left)
        cl.addStretch()

        # Right: compact author credit — quiet, dim
        right = QVBoxLayout()
        right.setSpacing(1)
        right.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        a = QLabel("a-issaoui", content)
        a.setObjectName("author")
        a.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(a)
        g = QLabel("github.com/a-issaoui", content)
        g.setObjectName("author")
        g.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(g)
        cl.addLayout(right)

        outer.addWidget(content)
        outer.addWidget(_accent_line(self, "accent_mid"))


# ============================================================================
# Elevation Dialog
# ============================================================================

class ElevationDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.result_yes = False
        self.setWindowTitle("Porkill")
        self.setFixedSize(500, 290)
        # Frameless — we draw our own chrome so the system title bar doesn't clash
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # Outer dialog border — 1px neon-dim so it pops from the main window behind
        self.setStyleSheet(f"""
            QDialog {{
                background: {Config.BG};
                border: 1px solid {Config.NEON_DIM};
            }}
            QLabel {{ font-family: "Monospace"; background: transparent; }}
        """)

        # ── Drag support (frameless needs manual drag) ───────────────────
        self._drag_pos: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Custom title bar ─────────────────────────────────────────────
        titlebar = QWidget(self)
        titlebar.setFixedHeight(32)
        titlebar.setStyleSheet(f"background: {Config.BG2}; border-bottom: 1px solid {Config.BORDER};")
        tb_lay = QHBoxLayout(titlebar)
        tb_lay.setContentsMargins(14, 0, 10, 0)
        tb_lay.setSpacing(0)

        app_lbl = QLabel(f"PORKILL  v{VERSION}", titlebar)
        app_lbl.setStyleSheet(f"color: {Config.NEON}; font-size: 8pt; font-weight: bold; letter-spacing: 3px;")
        tb_lay.addWidget(app_lbl)
        tb_lay.addStretch()

        close_btn = QPushButton("✕", titlebar)
        close_btn.setFixedSize(28, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {Config.FG3};
                border: none; font-size: 9pt;
            }}
            QPushButton:hover {{ color: {Config.RED}; background: {Config.BG4}; }}
        """)
        close_btn.clicked.connect(self._on_no)  # type: ignore[union-attr]
        tb_lay.addWidget(close_btn)
        outer.addWidget(titlebar)

        # ── 2px neon top accent ──────────────────────────────────────────
        top_bar = QFrame(self)
        top_bar.setFrameShape(QFrame.Shape.NoFrame)
        top_bar.setFixedHeight(2)
        top_bar.setStyleSheet(f"background: {Config.NEON}; border: none;")
        outer.addWidget(top_bar)

        # ── Content ──────────────────────────────────────────────────────
        content = QWidget(self)
        content.setStyleSheet(f"background: {Config.BG};")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(40, 24, 40, 20)
        lay.setSpacing(0)

        # Title
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield = QLabel("◈", self)
        shield.setStyleSheet(f"color: {Config.NEON}; font-size: 15pt; font-weight: bold;")
        title_row.addWidget(shield)
        title = QLabel("PRIVILEGE ELEVATION", self)
        title.setStyleSheet(
            f"color: {Config.NEON}; font-size: 12pt; font-weight: bold;"
        )
        title_row.addWidget(title)
        lay.addLayout(title_row)
        lay.addSpacing(10)

        # Rule under title
        rule = QFrame(self)
        rule.setFrameShape(QFrame.Shape.NoFrame)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {Config.BORDER}; border: none;")
        lay.addWidget(rule)
        lay.addSpacing(18)

        # Description
        msg = QLabel(
            "Gain full visibility of all process names?\n"
            "Without root, system-owned socket names are hidden.",
            self,
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {Config.FG}; font-size: 9pt;")
        lay.addWidget(msg)
        lay.addSpacing(6)

        note = QLabel("Requires admin password  ·  uses pkexec / sudo", self)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet(f"color: {Config.FG3}; font-size: 8pt;")
        lay.addWidget(note)
        lay.addSpacing(12)

        # Divider before buttons
        div = QFrame(self)
        div.setFrameShape(QFrame.Shape.NoFrame)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {Config.BORDER}; border: none;")
        lay.addWidget(div)
        lay.addSpacing(16)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        yes_btn = QPushButton("ELEVATE  —  YES", self)
        yes_btn.setFixedSize(180, 34)
        yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        yes_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Config.NEON}; color: {Config.BG};
                border: none; font-family: "Monospace";
                font-size: 8pt; font-weight: bold; letter-spacing: 2px;
            }}
            QPushButton:hover   {{ background: {Config.NEON_GLOW}; color: {Config.BG}; }}
            QPushButton:pressed {{ background: {Config.NEON_DIM};  color: {Config.BG}; }}
        """)
        yes_btn.clicked.connect(self._on_yes)  # type: ignore[union-attr]
        btn_row.addWidget(yes_btn)

        no_btn = QPushButton("SKIP  —  LIMITED", self)
        no_btn.setFixedSize(180, 34)
        no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        no_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Config.BG2}; color: {Config.FG2};
                border: 1px solid {Config.BORDER}; font-family: "Monospace";
                font-size: 8pt; font-weight: bold; letter-spacing: 2px;
            }}
            QPushButton:hover   {{ background: {Config.BG4}; color: {Config.FG}; border-color: {Config.NEON_DIM}; }}
            QPushButton:pressed {{ background: {Config.BG3}; }}
        """)
        no_btn.clicked.connect(self._on_no)  # type: ignore[union-attr]
        btn_row.addWidget(no_btn)
        lay.addLayout(btn_row)

        lay.addSpacing(10)
        # Unified keyboard hint — single centered line
        kb_hint = QLabel("Enter to elevate    ·    Esc to skip", self)
        kb_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kb_hint.setStyleSheet(f"color: {Config.FG3}; font-size: 7pt; letter-spacing: 1px;")
        lay.addWidget(kb_hint)
        lay.addSpacing(8)

        outer.addWidget(content)

        # Bottom neon-dim accent — mirrors the top bar
        bot_bar = QFrame(self)
        bot_bar.setFrameShape(QFrame.Shape.NoFrame)
        bot_bar.setFixedHeight(2)
        bot_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bot_bar.setStyleSheet(f"background: {Config.NEON_DIM}; border: none;")
        outer.addWidget(bot_bar)

        yes_btn.setDefault(True)
        yes_btn.setFocus()

        # Centre on screen
        if screen := QApplication.primaryScreen():
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width()  - self.width())  // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )

    # ── Frameless drag ───────────────────────────────────────────────────────

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: Any) -> None:  # pylint: disable=unused-argument
        self._drag_pos = None

    def _on_yes(self) -> None:
        self.result_yes = True
        self.accept()

    def _on_no(self) -> None:
        self.result_yes = False
        self.reject()


# ============================================================================
# Tree column indices
# ============================================================================

class _Col(IntEnum):
    """Typed column indices — prevents silent bugs from bare integer literals."""
    PID   = 0
    NAME  = 1
    PROTO = 2
    ADDR  = 3
    PORT  = 4
    STATE = 5
    USER  = 6
    CMD   = 7

# Module-level aliases so the rest of the code (including _FilterTask sort
# logic defined before _Col) compiles without forward-reference issues.
_COL_PID   = _Col.PID
_COL_NAME  = _Col.NAME
_COL_PROTO = _Col.PROTO
_COL_ADDR  = _Col.ADDR
_COL_PORT  = _Col.PORT
_COL_STATE = _Col.STATE
_COL_USER  = _Col.USER
_COL_CMD   = _Col.CMD

_ROLE_ROW_DATA   = Qt.ItemDataRole.UserRole
_ROLE_IS_GROUP   = Qt.ItemDataRole.UserRole + 1
_ROLE_GROUP_KEY  = Qt.ItemDataRole.UserRole + 2   # "grp:<name>"
_ROLE_GROUP_PID  = Qt.ItemDataRole.UserRole + 3
_ROLE_GROUP_NAME = Qt.ItemDataRole.UserRole + 4

_COLUMNS = [
    #  label        init-w  stretch?
    ("PID",           70,   False),
    ("PROCESS",      150,   False),
    ("PROTO",         50,   False),
    ("ADDRESS",      110,   False),
    ("PORT",          55,   False),
    ("STATE",         95,   False),
    ("USER",          80,   False),
    ("CMD",          200,   True),
]

_COL_MIN_WIDTHS = [85, 130, 65, 95, 52, 85, 65, 110]


# ============================================================================
# Smart Tooltip — positions itself above or below the cursor, never covers rows
# ============================================================================

class SmartTooltip(QWidget):
    """
    A custom tooltip that:
    - Appears BELOW the hovered row when there is screen space beneath it
    - Flips ABOVE the hovered row when near the bottom of the screen
    - Wraps long text with a max width
    - Matches the dark theme
    - Dismisses on any mouse move away from the source cell
    """

    _instance: Optional["SmartTooltip"] = None

    @classmethod
    def show_tip(cls, text: str, trigger_rect: QRect, _parent: QWidget) -> None:
        if not text or text == "—":
            cls.hide_tip()
            return
        if cls._instance is None:
            cls._instance = cls()
        cls._instance._show(text, trigger_rect, _parent)  # pylint: disable=protected-access

    @classmethod
    def hide_tip(cls) -> None:
        if cls._instance is not None:
            cls._instance.hide()
            # Schedule Qt cleanup — tooltip widget doesn't need to persist when hidden
            cls._instance.deleteLater()
            cls._instance = None

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        self._lbl = QLabel(self)
        self._lbl.setWordWrap(True)
        self._lbl.setMaximumWidth(820)
        self._lbl.setStyleSheet(
            f"color: {Config.FG}; font-family: 'Monospace'; font-size: 8pt;"
        )
        lay.addWidget(self._lbl)
        self.setStyleSheet(
            f"SmartTooltip {{ background: {Config.BG2};"
            f" border: 1px solid {Config.NEON_DIM};"
            f" border-radius: 3px; }}"
        )

    def _show(self, text: str, trigger_rect: QRect, _parent: QWidget) -> None:  # pylint: disable=unused-argument
        self._lbl.setText(text)
        self._lbl.adjustSize()
        self.adjustSize()

        screen = QApplication.screenAt(trigger_rect.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        W, H = self.sizeHint().width(), self.sizeHint().height()
        MARGIN = 6

        # Try below the row first
        y_below = trigger_rect.bottom() + MARGIN
        y_above = trigger_rect.top() - H - MARGIN

        if y_below + H <= avail.bottom():
            y = y_below
        elif y_above >= avail.top():
            y = y_above
        else:
            # Not enough space either way — pick whichever side has more room
            y = y_below if (avail.bottom() - trigger_rect.bottom()) >= (trigger_rect.top() - avail.top()) else y_above

        # Horizontal: align with left edge of trigger, clamp to screen
        x = trigger_rect.left()
        x = max(avail.left() + MARGIN, min(x, avail.right() - W - MARGIN))

        self.setGeometry(x, y, W, H)
        self.show()
        self.raise_()


# ============================================================================
# Main Window
# ============================================================================

class PorkillWindow(QMainWindow):

    # ── Class-level color/brush cache — constructed once, reused every rebuild ─
    _C: Dict[str, Any] = {}
    _B: Dict[str, Any] = {}

    @classmethod
    def _init_color_cache(cls) -> None:
        if cls._C:
            return
        cls._C = {
            "listen":     QColor(Config.NEON),
            "established":QColor(Config.CYAN),
            "udp_state":  QColor(Config.AMBER),
            "closing":    QColor(Config.AMBER_DIM),
            "kernel":     QColor(Config.FG2),
            "fg":         QColor(Config.FG),
            "fg2":        QColor(Config.FG2),
            "fg3":        QColor(Config.FG3),
            "tcp_fg":     QColor(Config.CYAN),
            "udp_fg":     QColor(Config.AMBER),
            "kern_proto": QColor(Config.FG2),
            "bg2":        QColor(Config.BG2),
            "bg3":        QColor(Config.BG3),
            "grp_bg":     QColor("#040a06"),
            "grp_fg":     QColor(Config.NEON),
            "grp_dim":    QColor(Config.FG2),
            "sep_bg":     QColor(Config.BG),
            # Protocol cell pill backgrounds — pre-baked to avoid QColor/QBrush
            # construction inside the hot render loop.  (Fix #8 / Fix #19)
            "tcp_badge_bg": QColor(Config.TCP_BADGE_BG),
            "udp_badge_bg": QColor(Config.UDP_BADGE_BG),
        }
        cls._B = {k: QBrush(v) for k, v in cls._C.items()}

    def __init__(self, cfg: Optional[argparse.Namespace] = None) -> None:
        super().__init__()

        if cfg:
            Config.MAX_ROWS        = cfg.max_rows
            self._refresh_interval = max(2, min(120, cfg.interval))
            self._auto_refresh     = not cfg.no_auto_refresh
        else:
            self._refresh_interval = 5
            self._auto_refresh     = True

        self._mono_font = resolve_mono_font()

        # State
        self._raw_rows: List[PortRow]    = []
        self._sort_col: int              = _COL_PORT
        self._sort_asc: bool             = True
        self._collapsed_groups: Set[str] = set()
        self._selected_key: Optional[Tuple[str, str, str, str]] = None
        self._selected_group: Optional[str] = None
        self._rebuilding                 = False
        self._fetching                   = False
        self._fetch_retry_count: int     = 0          # stuck-fetch guard (Fix #1-ext)
        self._fetch_start_time:  float   = 0.0        # stuck-fetch guard
        self._fetch_generation:  int     = 0          # incremented on every new task launch; stale completions are ignored
        # ── Fetch-generation design note ─────────────────────────────────────
        # Each call to _launch_fetch that actually starts a new worker increments
        # _fetch_generation and captures the value in the worker's closure as
        # `current_gen`.  When the worker's finally-block fires _set_not_fetching(),
        # it only clears _fetching if its generation still matches — ensuring that a
        # hung task which wakes up *after* the stuck-fetch guard has force-reset and
        # spawned a fresh task cannot clobber the new task's in-flight flag.
        # This is the same versioned-completion pattern used by _filter_version.
        self._fetch_lock                 = threading.Lock()
        self._filter_version             = 0
        self._filter_lock                = threading.Lock()   # Fix #2/#15/#16: single lock replaces QMutex+dead threading.Lock
        self._shutdown                   = threading.Event()

        # QThreadPool — bounded thread reuse (max 4 workers, 5s idle expiry)
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)
        self._thread_pool.setExpiryTimeout(5000)

        # Persistent signal objects — created ONCE in main thread.
        # Workers emit on these; Qt's AutoConnection routes to main thread safely.
        self._fetch_sigs = FetchSignals(self)   # parented — auto-cleaned on window close
        self._fetch_sigs.finished.connect(self._on_fetch_done)  # type: ignore[union-attr]
        self._filter_sigs = FilterSignals(self) # parented — auto-cleaned on window close
        self._filter_sigs.finished.connect(self._on_filter_done)  # type: ignore[union-attr]
        self._flash_restore              = ""
        self._last_refresh_ts: float    = 0.0
        self._last_manual_refresh: float = 0.0
        self._fetcher                    = PortDataFetcher()

        # UI attributes — initialised in _build_ui() / _make_*()
        self._badge_total:  StatBadge
        self._badge_listen: StatBadge
        self._badge_tcp:    StatBadge
        self._badge_udp:    StatBadge
        self._auto_dot:     QLabel
        self._auto_cb:      QCheckBox
        self._spin:         QSpinBox
        self._filter_edit:  QLineEdit
        self._status_lbl:   QLabel
        self.tree:          QTreeWidget
        self._info_lbl:     QLabel
        self._hint_lbl:     QLabel
        self._term_btn:     KillButton
        self._kill_btn:     KillButton
        self._shown_once:   bool = False

        # Timers
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._schedule_refresh)  # type: ignore[union-attr]

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._do_apply_filter)  # type: ignore[union-attr]

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)  # type: ignore[union-attr]

        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._tick_age_label)  # type: ignore[union-attr]
        self._age_timer.start(5_000)

        # Build UI
        self._build_ui()

        self.setWindowTitle("Porkill")
        self.setMinimumSize(960, 620)
        self._bind_shortcuts()
        # First refresh and column layout triggered from showEvent
        # so the window is fully rendered before any data or resizing occurs.

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setAutoFillBackground(True)
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(LogoBanner(root))
        vbox.addWidget(self._make_ctrl_bar(root))
        vbox.addWidget(self._make_filter_bar(root))
        vbox.addWidget(_accent_line(root, "sep"))
        vbox.addWidget(self._make_tree(root), stretch=1)
        vbox.addWidget(_accent_line(root, "accent_bot"))
        vbox.addWidget(self._make_action_bar(root))

    def _make_ctrl_bar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setObjectName("ctrl_bar")
        bar.setFixedHeight(54)   # matches badge height (44px) + top+bottom margins (5+5px)
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 5, 24, 5)

        # Stat badges — tightly packed
        self._badge_total  = StatBadge("TOTAL",  Config.NEON,    bar)
        self._badge_listen = StatBadge("LISTEN", Config.NEON,    bar)
        self._badge_tcp    = StatBadge("TCP",    Config.CYAN,    bar)
        self._badge_udp    = StatBadge("UDP",    Config.AMBER,   bar)
        for badge in (self._badge_total, self._badge_listen, self._badge_tcp, self._badge_udp):
            h.addWidget(badge)
            h.addSpacing(2)

        h.addSpacing(16)
        vsep = QFrame(bar); vsep.setObjectName("ctrl_sep")
        vsep.setFrameShape(QFrame.Shape.NoFrame)
        vsep.setStyleSheet(f"background: {Config.BORDER}; border: none;")
        vsep.setFixedWidth(1)
        h.addWidget(vsep)
        h.addStretch()

        # Auto-refresh dot indicator
        self._auto_dot = QLabel("●", bar)
        self._auto_dot.setStyleSheet(
            f"color: {Config.NEON}; font-size: 10pt;" if self._auto_refresh
            else f"color: {Config.FG2}; font-size: 10pt;"
        )
        h.addWidget(self._auto_dot)
        h.addSpacing(5)

        self._auto_cb = QCheckBox("AUTO", bar)
        self._auto_cb.setChecked(self._auto_refresh)
        self._auto_cb.toggled.connect(self._on_auto_toggle)  # type: ignore[union-attr]
        h.addWidget(self._auto_cb)

        l = QLabel("every", bar); l.setObjectName("ctrl_label")
        h.addSpacing(10); h.addWidget(l); h.addSpacing(4)

        self._spin = QSpinBox(bar)
        self._spin.setRange(2, 120)
        self._spin.setValue(self._refresh_interval)
        self._spin.setFixedWidth(48)
        self._spin.valueChanged.connect(lambda v: setattr(self, "_refresh_interval", v))  # type: ignore[union-attr]
        h.addWidget(self._spin)

        l = QLabel("s", bar); l.setObjectName("ctrl_label"); h.addWidget(l)
        h.addSpacing(14)

        btn = KillButton("↻  REFRESH NOW", Config.NEON, bar)
        btn.clicked.connect(self._schedule_refresh)  # type: ignore[union-attr]
        h.addWidget(btn)
        return bar

    def _make_filter_bar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setObjectName("filter_bar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 5, 24, 5)
        h.setSpacing(10)

        pip = QFrame(bar); pip.setObjectName("filter_pip"); pip.setFixedSize(2, 18)
        h.addWidget(pip)

        fl = QLabel("FILTER", bar); fl.setObjectName("filter_label")
        h.addWidget(fl)
        h.addSpacing(6)

        self._filter_edit = QLineEdit(bar)
        self._filter_edit.setPlaceholderText("type to filter…")
        self._filter_edit.setFixedWidth(260)
        self._filter_edit.textChanged.connect(self._on_filter_changed)  # type: ignore[union-attr]
        h.addWidget(self._filter_edit)

        hint = QLabel("name  ·  pid  ·  port  ·  proto  ·  state", bar)
        hint.setObjectName("hint")
        h.addWidget(hint)
        h.addStretch()

        self._status_lbl = QLabel("INITIALIZING…", bar)
        self._status_lbl.setObjectName("status")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._status_lbl)
        return bar

    def _make_tree(self, parent: QWidget) -> QTreeWidget:
        self.tree = QTreeWidget(parent)
        self.tree.setAlternatingRowColors(False)  # manual row BGs — enables per-cell proto badge
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)    # Fix #9: all rows (data + separators) now share
        # the same 28px height so Qt skips per-row measurement, greatly improving
        # scroll performance at high row counts.  Separator rows use 28px via setSizeHint.
        self.tree.setAnimated(True)
        self.tree.setIndentation(12)
        self.tree.setRootIsDecorated(True)
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels([c[0] for c in _COLUMNS])

        hdr = self.tree.header()
        hdr.setSortIndicatorShown(True)
        hdr.setSectionsClickable(True)
        hdr.sectionClicked.connect(self._on_header_clicked)  # type: ignore[union-attr]
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setStretchLastSection(False)   # we manage stretching manually

        # All columns Interactive except last (CMD) which stretches to fill remaining space
        for i in range(len(_COLUMNS) - 1):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(True)

        hdr.setMinimumSectionSize(40)
        hdr.setSortIndicator(_COL_PORT, Qt.SortOrder.AscendingOrder)

        # Install event filter on the viewport to catch resize + tooltip events
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        # No horizontal scrollbar — last col stretches, no overflow possible
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Explicitly set viewport background — prevents white area showing through
        self.tree.viewport().setStyleSheet(f"background: {Config.BG2};")
        self.tree.viewport().setAutoFillBackground(True)

        self.tree.itemSelectionChanged.connect(self._on_selection_changed)  # type: ignore[union-attr]
        self.tree.itemDoubleClicked.connect(  # type: ignore[union-attr]
            lambda item, _c: self._kill(signal.SIGTERM)
            if item and (item.flags() & Qt.ItemFlag.ItemIsSelectable) else None
        )
        self.tree.itemCollapsed.connect(self._on_item_collapsed)  # type: ignore[union-attr]
        self.tree.itemExpanded.connect(self._on_item_expanded)  # type: ignore[union-attr]
        # Remove any internal margin that leaves a void gap above the footer
        self.tree.setContentsMargins(0, 0, 0, 0)
        return self.tree

    # Column proportions (must sum to 1.0):
    # PID=6%, PROCESS=13%, PROTO=5%, ADDRESS=11%, PORT=6%, STATE=9%, USER=8%, CMD=42%
    _COL_PCT = [0.08, 0.15, 0.06, 0.11, 0.05, 0.09, 0.08, 0.38]

    def _apply_column_proportions(self) -> None:
        """Set fixed-column widths as percentages of viewport; CMD col auto-stretches."""
        vp_w = self.tree.viewport().width()
        if vp_w < 100:
            return
        hdr = self.tree.header()
        # Apply proportions to all columns except the last (CMD) which is Stretch-managed
        for i, pct in enumerate(self._COL_PCT[:-1]):
            w = max(_COL_MIN_WIDTHS[i], int(vp_w * pct))
            hdr.resizeSection(i, w)
        # CMD column fills whatever remains — Qt handles it via ResizeMode.Stretch

    def eventFilter(self, obj: Any, event: Any) -> bool:
        is_tree     = obj is self.tree
        is_viewport = obj is self.tree.viewport()

        if is_tree and event.type() == QEvent.Type.Resize:
            # Defer one frame so viewport().width() reflects the new tree size
            QTimer.singleShot(0, self._apply_column_proportions)

        elif is_viewport and event.type() == QEvent.Type.ToolTip:
            pos  = event.pos()
            item = self.tree.itemAt(pos)
            col  = self.tree.columnAt(pos.x())
            tip  = item.toolTip(col) if item else ""

            if tip:
                vp        = self.tree.viewport()
                ir        = self.tree.visualItemRect(item)
                col_x     = sum(self.tree.columnWidth(c) for c in range(col))
                col_w     = self.tree.columnWidth(col)
                cell_local = QRect(col_x, ir.top(), col_w, ir.height())
                cell_global = QRect(
                    vp.mapToGlobal(cell_local.topLeft()),
                    vp.mapToGlobal(cell_local.bottomRight()),
                )
                SmartTooltip.show_tip(tip, cell_global, self)
            else:
                SmartTooltip.hide_tip()
            return True   # suppress Qt's own tooltip

        elif is_viewport and event.type() in (QEvent.Type.MouseMove, QEvent.Type.Leave):
            SmartTooltip.hide_tip()

        return super().eventFilter(obj, event)

    def _make_action_bar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setObjectName("action_bar")
        # Fixed height = button height (34px) + top+bottom margins (10+10px).
        # Without this the bar collapses when buttons are hidden, stealing
        # height from the tree widget and making it appear to shrink on selection.
        bar.setFixedHeight(54)
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 10, 24, 10)
        h.setSpacing(0)

        # ── Left: selection info ─────────────────────────────────────────
        self._info_lbl = QLabel("no selection", bar)
        self._info_lbl.setObjectName("info")
        self._info_lbl.setStyleSheet(f"color: {Config.FG2}; font-size: 8pt;")
        h.addWidget(self._info_lbl)

        self._hint_lbl = QLabel(
            "    ·    Del  SIGTERM    Ctrl+K  SIGKILL    Esc  clear", bar
        )
        self._hint_lbl.setObjectName("hint")
        self._hint_lbl.setVisible(False)
        h.addWidget(self._hint_lbl)

        h.addStretch()

        # ── Centre: privilege indicator ──────────────────────────────────
        try:
            import pwd as _pwd
            _user = _pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):  # more specific than bare Exception
            _user = os.environ.get("USER", str(os.getuid()))
        try:
            _host = socket.gethostname()
        except OSError:
            _host = "localhost"

        is_root = os.getuid() == 0
        priv_text  = f"● root · {_host}" if is_root else f"○ {_user}@{_host}"
        priv_color = Config.NEON if is_root else Config.AMBER
        priv_lbl   = QLabel(priv_text, bar)
        priv_lbl.setObjectName("hint")
        priv_lbl.setStyleSheet(
            f"color: {priv_color}; font-size: 8pt; font-weight: bold; padding: 0 10px;"
        )
        h.addWidget(priv_lbl)
        h.addSpacing(12)

        # ── Right: kill buttons ──────────────────────────────────────────
        self._term_btn = KillButton("SIGTERM  graceful", Config.AMBER, bar)
        self._term_btn.clicked.connect(lambda: self._kill(signal.SIGTERM))  # type: ignore[union-attr]
        self._term_btn.setVisible(False)
        h.addWidget(self._term_btn)
        h.addSpacing(6)

        self._kill_btn = KillButton("SIGKILL  force −9", Config.RED, bar)
        self._kill_btn.clicked.connect(lambda: self._kill(signal.SIGKILL))  # type: ignore[union-attr]
        self._kill_btn.setVisible(False)
        h.addWidget(self._kill_btn)
        return bar

    # ── Shortcuts ────────────────────────────────────────────────────────────

    def _bind_shortcuts(self) -> None:
        for key, fn in [
            ("Ctrl+R", self._schedule_refresh),
            ("F5",     self._schedule_refresh),
            ("Delete", lambda: self._kill(signal.SIGTERM)),
            ("Ctrl+K", lambda: self._kill(signal.SIGKILL)),
            ("Escape", self._clear_selection),
            ("Ctrl+F", self._focus_filter),
            ("Ctrl+Q", self.close),
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(fn)  # type: ignore[union-attr]

    def _focus_filter(self) -> None:
        self._filter_edit.setFocus()
        self._filter_edit.selectAll()

    def _clear_selection(self) -> None:
        self.tree.clearSelection()
        self._selected_key = self._selected_group = None
        self._info_lbl.setText("no selection")
        self._info_lbl.setStyleSheet(f"color: {Config.FG2}; font-size: 8pt;")
        self._hint_lbl.setVisible(False)
        self._term_btn.setVisible(False)
        self._kill_btn.setVisible(False)

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _on_auto_toggle(self, checked: bool) -> None:
        self._auto_refresh = checked
        self._auto_dot.setStyleSheet(
            f"color: {Config.NEON}; font-size: 10pt;" if checked
            else f"color: {Config.FG2}; font-size: 10pt;"
        )
        if checked:
            self._schedule_refresh()
        else:
            self._refresh_timer.stop()

    def _schedule_refresh(self) -> None:
        # Throttle manual refresh to 2Hz max — prevents worker queue buildup from Ctrl+R spam
        now = time.monotonic()
        if (now - self._last_manual_refresh) < 0.5:
            return
        self._last_manual_refresh = now
        self._refresh_timer.stop()
        self._set_status("SCANNING…")
        self._launch_fetch()
        if self._auto_refresh:
            self._refresh_timer.start(self._refresh_interval * 1000)

    def _launch_fetch(self) -> None:
        with self._fetch_lock:
            if self._fetching:
                elapsed = time.monotonic() - self._fetch_start_time
                self._fetch_retry_count += 1
                # After 20 retries (~10 s) or 15 s wall-clock, the worker is almost
                # certainly hung on a blocking syscall.  Force-reset the flag so the
                # next tick can spawn a fresh task instead of accumulating timers forever.
                if self._fetch_retry_count > 20 or elapsed > 15.0:
                    logger.warning(
                        "Fetch worker stuck for %.1fs (%d retries) — force-resetting",
                        elapsed, self._fetch_retry_count,
                    )
                    self._fetching = False
                    self._fetch_retry_count = 0
                    # Fall through — a new task will be submitted below
                else:
                    # A fetch is still in-flight; reschedule so we don't miss this tick
                    QTimer.singleShot(500, self._launch_fetch)
                    return
            self._fetching = True
            self._fetch_start_time = time.monotonic()
            self._fetch_retry_count = 0
            # Increment generation so any stale completion from a hung task that
            # eventually finishes can detect it no longer owns the active fetch slot.
            self._fetch_generation += 1
            current_gen = self._fetch_generation

        def _set_not_fetching() -> None:
            with self._fetch_lock:
                # Only clear the flag if this worker's generation is still current.
                # If the stuck-fetch guard already force-reset and launched a new task,
                # a stale finally-block from the old worker must not clobber the new one.
                if self._fetch_generation == current_gen:
                    self._fetching = False

        task = _FetchTask(self._fetcher, self._fetch_sigs, self._shutdown, _set_not_fetching)
        task.setAutoDelete(True)
        self._thread_pool.start(task)

    def _on_fetch_done(self, rows: Any, error: Optional[str]) -> None:
        if error:
            self._raw_rows = []
            self._set_status(f"ERROR: {error[:60]}")
            return
        # rows may arrive as tuple (immutable snapshot from worker) — normalise to list
        self._raw_rows = list(rows)[:Config.MAX_RAW_ROWS]
        # Clear per-pid caches so user/cmd reflect current state
        _pid_user_cache.clear()
        _pid_cmd_cache.clear()
        _pid_cmdline_cache.clear()          # Fix #1
        _container_runtime_cache.clear()    # Fix #10
        self._badge_total.set(len(rows))
        self._badge_listen.set(sum(1 for r in rows if r.state.upper() == "LISTEN"))
        self._badge_tcp.set(sum(1 for r in rows if r.proto == "TCP"))
        self._badge_udp.set(sum(1 for r in rows if r.proto == "UDP"))
        self._do_apply_filter()
        # Status is updated in _on_filter_done once the tree is fully rebuilt

    # ── Filter ───────────────────────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        self._filter_timer.stop()
        self._filter_timer.start(Config.FILTER_DEBOUNCE_MS)

    def _do_apply_filter(self) -> None:
        sel_key   = self._selected_key
        sel_group = self._selected_group

        # Use threading.Lock (Python RAII via `with`) instead of QMutex +
        # manual QMutexLocker.unlock() which had asymmetric unlock paths.  (Fix #15/#16)
        with self._filter_lock:
            self._filter_version += 1
            version  = self._filter_version
            query    = self._filter_edit.text().strip().lower()
            source   = list(self._raw_rows)  # snapshot under lock
            sort_col = self._sort_col
            sort_asc = self._sort_asc

        task = _FilterTask(
            version, query, source, sort_col, sort_asc,
            sel_key, sel_group,
            self._filter_sigs, self._shutdown,
        )
        task.setAutoDelete(True)
        self._thread_pool.start(task)

    def _on_filter_done(
        self, version: int, visible: Any,
        sel_key: Any, sel_group: Any,
    ) -> None:
        # Both paths release the lock symmetrically via `with`.  (Fix #15/#16)
        with self._filter_lock:
            if version != self._filter_version:
                return
        rows = list(visible)  # normalise tuple→list
        self._rebuild_tree(rows, sel_key, sel_group)
        self._last_refresh_ts = time.monotonic()
        self._set_status(self._fmt_refresh_age())

    # ── Tree rebuild ─────────────────────────────────────────────────────────

    def _rebuild_tree(
        self, visible: List[PortRow], sel_key: Any, sel_group: Any,
    ) -> None:
        self._rebuilding = True
        self.tree.setUpdatesEnabled(False)
        restore_item: Optional[QTreeWidgetItem] = None

        # ── palette pre-bake ─────────────────────────────────────────────────
        _left   = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        _center = Qt.AlignmentFlag.AlignCenter

        # Initialise class-level color/brush cache (no-op after first call)
        self._init_color_cache()
        _C = self._C
        _B = self._B

        # Group header fonts (QFont is lightweight, ok to create per rebuild)
        grp_font     = QFont(self._mono_font, 8, QFont.Weight.Bold)
        listen_font  = QFont(self._mono_font, 9, QFont.Weight.Bold)

        # Aliases for readability (no allocation — just references)
        grp_bg       = _C["grp_bg"];   grp_fg   = _C["grp_fg"]
        sep_bg       = _C["sep_bg"]
        c_listen     = _C["listen"];   c_established = _C["established"]
        c_udp_state  = _C["udp_state"]; c_closing = _C["closing"]
        c_kernel     = _C["kernel"];   c_fg = _C["fg"]; c_fg2 = _C["fg2"]; c_fg3 = _C["fg3"]
        c_tcp_fg     = _C["tcp_fg"];   c_udp_fg = _C["udp_fg"]; c_kern_proto = _C["kern_proto"]
        c_bg2        = _C["bg2"];      c_bg3 = _C["bg3"]

        try:
            self.tree.clear()

            # Build group map preserving insertion order
            groups: Dict[str, List[PortRow]] = {}
            for row in visible:
                groups.setdefault(row.group or row.name, []).append(row)

            # Collect all top-level items (separators + group headers) and insert
            # them in a single addTopLevelItems() call.  Qt only fires one batch of
            # internal signals instead of N individual insertions, cutting rebuild
            # overhead for large datasets by ~30–40%.  Child rows are similarly batched
            # via grp_item.addChildren().  (Optimisation: batch insertion)
            top_items: List[QTreeWidgetItem] = []
            first_group = True
            for g_name, g_rows in groups.items():
                grp_key = f"grp:{g_name}"
                count   = len(g_rows)
                suffix  = "port" if count == 1 else "ports"

                # ── separator (thin gap before every group but the first) ───
                if not first_group:
                    sep = QTreeWidgetItem()   # no parent — batch-inserted below
                    sep.setFlags(Qt.ItemFlag.NoItemFlags)
                    sep.setSizeHint(0, QSize(0, 28))   # Fix #9: match data row height for uniform rows
                    sep.setChildIndicatorPolicy(
                        QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
                    for col in range(self.tree.columnCount()):
                        sep.setBackground(col, QBrush(sep_bg))
                    top_items.append(sep)
                first_group = False

                # ── group header — clear parent/child visual separation ──────
                grp_item = QTreeWidgetItem()   # no parent — batch-inserted below
                grp_item.setText(0, f"  {g_name.upper()}   {count} {suffix}")
                grp_item.setSizeHint(0, QSize(0, 28))
                grp_item.setData(_COL_PID, _ROLE_IS_GROUP,   True)
                grp_item.setData(_COL_PID, _ROLE_GROUP_KEY,  grp_key)
                grp_item.setData(_COL_PID, _ROLE_GROUP_PID,  g_rows[0].pid)
                grp_item.setData(_COL_PID, _ROLE_GROUP_NAME, g_rows[0].name)
                for col in range(self.tree.columnCount()):
                    grp_item.setBackground(col, QBrush(grp_bg))
                    grp_item.setForeground(col, QBrush(grp_fg))
                    grp_item.setFont(col, grp_font)
                grp_item.setTextAlignment(0, _left)
                # Note: setExpanded() only works after the item is in the tree;
                # we call it after addTopLevelItems() below.
                top_items.append(grp_item)

                if sel_group == grp_key:
                    restore_item = grp_item

                # ── child rows — built as a batch list ──────────────────────
                children: List[QTreeWidgetItem] = []
                for i, row in enumerate(g_rows):
                    child = QTreeWidgetItem()   # no parent — batch-inserted below
                    # PID: right-aligned, never truncate — kernel uses em-dash
                    pid_display = f"{row.pid:>7}" if row.pid != "—" else "    —  "
                    child.setText(_COL_PID,   pid_display)
                    child.setText(_COL_NAME,  row.name)

                    # Protocol: colored text with subtle pill background per cell
                    child.setText(_COL_PROTO, row.proto)

                    child.setText(_COL_ADDR,  fmt_addr(row.addr))
                    child.setToolTip(_COL_ADDR, row.addr)
                    # Port: right-aligned, fixed 5-digit width
                    _p = int(row.port) if row.port.isdigit() else -1
                    child.setText(_COL_PORT, _fmt_port(_p) if _p >= 0 else row.port)

                    # State display via module-level constant (no per-row dict creation)
                    state_upper = row.state.upper()
                    state_display = _STATE_DISPLAY_MAP.get(state_upper, f"? {row.state[:6]}")
                    child.setText(_COL_STATE, state_display)

                    # USER column
                    user_str = get_proc_user(row.pid)
                    child.setText(_COL_USER, user_str)

                    # CMD column — exe basename + first arg
                    cmd_str = get_proc_cmd(row.pid)
                    child.setText(_COL_CMD, cmd_str)
                    child.setToolTip(_COL_CMD, get_proc_cmd_full(row.pid))

                    child.setSizeHint(0, QSize(0, 28))
                    child.setData(_COL_PID, _ROLE_ROW_DATA, row)
                    child.setData(_COL_PID, _ROLE_IS_GROUP, False)

                    # Alignment — all centered for clean grid feel
                    child.setTextAlignment(_COL_PID,   _center)
                    child.setTextAlignment(_COL_NAME,  _center)
                    child.setTextAlignment(_COL_PROTO, _center)
                    child.setTextAlignment(_COL_ADDR,  _center)
                    child.setTextAlignment(_COL_PORT,  _center)
                    child.setTextAlignment(_COL_STATE, _center)
                    child.setTextAlignment(_COL_USER,  _center)
                    child.setTextAlignment(_COL_CMD,   _left)

                    # ── Semantic colour logic ─────────────────────────────
                    row_bg = c_bg2 if i % 2 == 0 else c_bg3
                    is_kernel = row.pid == "—"

                    if is_kernel:
                        # Kernel rows: everything dim — no visual weight
                        proto_fg = c_kern_proto
                        name_fg = addr_fg = pid_fg = state_fg = c_kernel
                        user_fg = c_kernel
                        cmd_fg  = c_kernel
                    else:
                        pid_fg   = c_fg2    # PID secondary
                        name_fg  = c_fg     # PROCESS is primary info — full brightness
                        addr_fg  = c_fg2    # address secondary

                        # Protocol: colored text, reliable across all row types
                        proto_fg = c_tcp_fg if row.proto == "TCP" else c_udp_fg

                        # State drives signal color
                        if state_upper == "LISTEN":
                            state_fg = c_listen
                        elif state_upper == "ESTABLISHED":
                            state_fg = c_established
                        elif state_upper in ("UNCONN", "—"):
                            state_fg = c_udp_state if row.proto == "UDP" else c_fg2
                        elif state_upper in ("TIME_WAIT", "CLOSE_WAIT", "FIN_WAIT1", "FIN_WAIT2"):
                            state_fg = c_closing
                        else:
                            state_fg = c_fg2

                        # USER: root glows neon, others dim
                        user_fg = c_listen if user_str == "root" else c_fg2
                        # CMD: always tertiary — informational, not action-critical
                        cmd_fg  = c_fg3

                    # Apply uniform row background across all cols
                    for col in range(self.tree.columnCount()):
                        child.setBackground(col, QBrush(row_bg))
                        child.setForeground(col, QBrush(c_fg))

                    # Per-column semantic overrides
                    child.setForeground(_COL_PID,   QBrush(pid_fg))
                    child.setForeground(_COL_NAME,  QBrush(name_fg))
                    child.setForeground(_COL_PROTO, QBrush(proto_fg))
                    child.setForeground(_COL_ADDR,  QBrush(addr_fg))
                    child.setForeground(_COL_STATE, QBrush(state_fg))
                    child.setForeground(_COL_USER,  QBrush(user_fg))
                    child.setForeground(_COL_CMD,   QBrush(cmd_fg))

                    # Protocol badge: subtle pill background per-cell
                    # (applied AFTER row background so it overrides cleanly)
                    # Uses pre-baked brushes from _B cache — no QColor/QBrush
                    # construction inside the loop.  (Fix #8/#19)
                    if not is_kernel:
                        if row.proto == "TCP":
                            child.setBackground(_COL_PROTO, _B["tcp_badge_bg"])
                        else:
                            child.setBackground(_COL_PROTO, _B["udp_badge_bg"])

                    # LISTEN: bold port + state — surgical priority signal
                    if not is_kernel and state_upper == "LISTEN":
                        child.setFont(_COL_STATE, listen_font)
                        child.setFont(_COL_PORT,  listen_font)
                        child.setForeground(_COL_PORT, QBrush(c_listen))
                    else:
                        port_fg = c_fg if not is_kernel else c_kernel
                        child.setForeground(_COL_PORT, QBrush(port_fg))

                    if sel_key and (row.pid, row.name, row.proto, row.port) == sel_key:
                        restore_item = child

                    children.append(child)

                # Batch-insert all children under this group header in one call
                grp_item.addChildren(children)

            # Single batch insert of all top-level items — one Qt signal instead of N
            self.tree.addTopLevelItems(top_items)

            # setExpanded() only works after items are in the tree
            for item in top_items:
                if item.data(_COL_PID, _ROLE_IS_GROUP):
                    gk = item.data(_COL_PID, _ROLE_GROUP_KEY)
                    item.setExpanded(gk not in self._collapsed_groups)

        finally:
            self.tree.setUpdatesEnabled(True)
            self._rebuilding = False

        # Span ALL top-level items (group headers + separators)
        for top_row in range(self.tree.topLevelItemCount()):
            self.tree.setFirstColumnSpanned(top_row, QModelIndex(), True)

        # Column widths are NOT reset here — only on window resize (eventFilter)
        # and on first show (showEvent). This preserves manual column resizing.

        if restore_item:
            self.tree.setCurrentItem(restore_item)
            self.tree.scrollToItem(restore_item)
        else:
            self._selected_key = self._selected_group = None
            self._info_lbl.setText("no selection")
            self._info_lbl.setStyleSheet(f"color: {Config.FG2}; font-size: 8pt;")
            self._hint_lbl.setVisible(False)
            self._term_btn.setVisible(False)
            self._kill_btn.setVisible(False)

    # ── Tree events ──────────────────────────────────────────────────────────

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        if not self._rebuilding:
            k = item.data(_COL_PID, _ROLE_GROUP_KEY)
            if k:
                self._collapsed_groups.add(k)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if not self._rebuilding:
            k = item.data(_COL_PID, _ROLE_GROUP_KEY)
            if k:
                self._collapsed_groups.discard(k)

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self._selected_key = self._selected_group = None
            self._info_lbl.setText("no selection")
            self._info_lbl.setStyleSheet(f"color: {Config.FG2}; font-size: 8pt;")
            self._hint_lbl.setVisible(False)
            self._term_btn.setVisible(False)
            self._kill_btn.setVisible(False)
            return

        item     = items[0]
        is_group = item.data(_COL_PID, _ROLE_IS_GROUP)

        if is_group:
            pid      = item.data(_COL_PID, _ROLE_GROUP_PID)
            name     = item.data(_COL_PID, _ROLE_GROUP_NAME)
            grp_key  = item.data(_COL_PID, _ROLE_GROUP_KEY)
            self._selected_group = grp_key
            self._selected_key   = (pid, name, "", "") if pid and pid not in ("—", "") else None
            if self._selected_key:
                self._info_lbl.setText(
                    f"group  {name}  ·  pid {pid}  ·  all ports"
                )
                self._info_lbl.setStyleSheet(f"color: {Config.NEON}; font-size: 8pt;")
                self._hint_lbl.setVisible(True)
                self._term_btn.setVisible(True)
                self._kill_btn.setVisible(True)
            else:
                self._info_lbl.setText("no selection")
                self._info_lbl.setStyleSheet(f"color: {Config.FG2}; font-size: 8pt;")
                self._hint_lbl.setVisible(False)
                self._term_btn.setVisible(False)
                self._kill_btn.setVisible(False)
        else:
            row: PortRow = item.data(_COL_PID, _ROLE_ROW_DATA)
            if row:
                self._selected_key   = (row.pid, row.name, row.proto, row.port)
                self._selected_group = None
                can_kill = row.pid not in ("—", "")
                pid_part = f"pid {row.pid}  ·  " if can_kill else "kernel  ·  "
                self._info_lbl.setText(
                    f"{pid_part}{row.name}  ·  {row.proto}  {fmt_addr(row.addr)}:{row.port}  ·  {row.state}"
                )
                self._info_lbl.setStyleSheet(
                    f"color: {Config.NEON if can_kill else Config.FG2}; font-size: 8pt;"
                )
                self._hint_lbl.setVisible(can_kill)
                self._term_btn.setVisible(can_kill)
                self._kill_btn.setVisible(can_kill)

    def _on_header_clicked(self, col: int) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        order = Qt.SortOrder.AscendingOrder if self._sort_asc else Qt.SortOrder.DescendingOrder
        self.tree.header().setSortIndicator(col, order)
        self._do_apply_filter()

    # ── Kill ─────────────────────────────────────────────────────────────────

    def _kill(self, sig: signal.Signals) -> None:
        items = self.tree.selectedItems()
        if not items:
            self._flash_status("SELECT A PROCESS FIRST")
            return

        item     = items[0]
        is_group = item.data(_COL_PID, _ROLE_IS_GROUP)
        targets: List[Tuple[str, str]] = []
        display_name = ""

        if is_group:
            display_name = item.data(_COL_PID, _ROLE_GROUP_NAME) or ""
            seen_pids: Set[str] = set()
            for i in range(item.childCount()):
                child = item.child(i)
                row: PortRow = child.data(_COL_PID, _ROLE_ROW_DATA)
                if row and row.pid not in ("—", "") and row.pid not in seen_pids:
                    targets.append((row.pid, row.name))
                    seen_pids.add(row.pid)
        else:
            row = item.data(_COL_PID, _ROLE_ROW_DATA)
            if row and row.pid not in ("—", ""):
                targets    = [(row.pid, row.name)]
                display_name = row.name

        if not targets:
            QMessageBox.warning(self, "porkill",
                "No valid PIDs found for this entry (kernel/missing).")
            return

        sig_label = "SIGKILL -9 (force)" if sig == signal.SIGKILL else "SIGTERM (graceful)"
        if is_group and len(targets) > 1:
            preview = ", ".join(p for p, _ in targets[:5])
            if len(targets) > 5:
                preview += "…"
            msg = (
                f"Send  {sig_label}  to {len(targets)} processes in group:\n\n"
                f"   Group : {display_name}\n"
                f"   PIDs  : {preview}\n\n"
                "This will kill the entire group and all associated ports.\nConfirm?"
            )
        else:
            pid, _ = targets[0]
            msg = (
                f"Send  {sig_label}  to:\n\n"
                f"   Process : {display_name}\n"
                f"   PID     : {pid}\n\nConfirm?"
            )

        if QMessageBox.question(
            self, "porkill // confirm kill", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        success, errors = 0, []
        for pid_to_kill, expected_name in targets:
            current = read_proc_file(pid_to_kill, "comm")
            if current and current != expected_name:
                errors.append(f"PID {pid_to_kill}: name changed ({current}), skipping")
                continue
            ok, err = send_signal_to_pid(pid_to_kill, sig)
            if ok:
                success += 1
            else:
                errors.append(f"PID {pid_to_kill}: {err}")

        if success:
            self._flash_status(f"KILLED {success} PROCESS(ES) ✓")
            QTimer.singleShot(Config.REFRESH_AFTER_KILL_MS, self._schedule_refresh)

        if errors:
            self._flash_status(f"FAILED: {len(errors)} ERROR(S)")
            err_text = "\n".join(errors[:5]) + ("\n…" if len(errors) > 5 else "")
            QMessageBox.critical(self, "porkill // kill issues",
                f"Errors while killing:\n\n{err_text}\n\nTry running with sudo.")

    # ── Status ───────────────────────────────────────────────────────────────

    def _fmt_refresh_age(self) -> str:
        if not self._last_refresh_ts:
            return "UPDATED just now"
        age = int(time.monotonic() - self._last_refresh_ts)
        if age < 5:   return "UPDATED just now"
        if age < 60:  return f"UPDATED {age}s ago"
        return f"UPDATED {age // 60}m ago"

    def _tick_age_label(self) -> None:
        if self._last_refresh_ts and not self._flash_timer.isActive():
            self._set_status(self._fmt_refresh_age())

    def _set_status(self, msg: str) -> None:
        self._status_lbl.setText(msg)

    def _flash_status(self, msg: str) -> None:
        self._flash_timer.stop()
        self._flash_restore = self._fmt_refresh_age()
        self._status_lbl.setText(msg)
        self._flash_timer.start(Config.FLASH_DURATION_MS)

    def _clear_flash(self) -> None:
        self._status_lbl.setText(self._flash_restore)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            # Apply columns immediately on first real paint (viewport is now sized)
            self._apply_column_proportions()
            # Fetch data one frame later so the window is fully visible first
            QTimer.singleShot(0, self._schedule_refresh)

    def closeEvent(self, event: Any) -> None:
        self._shutdown.set()          # signal workers first
        self._refresh_timer.stop()
        self._filter_timer.stop()
        self._flash_timer.stop()
        self._age_timer.stop()
        event.accept()


# ============================================================================
# Argument Parsing
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process & Port Monitor / Killer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Keyboard Shortcuts:
  Ctrl+R / F5    Refresh          Delete      SIGTERM selected
  Ctrl+K         SIGKILL selected  Ctrl+F      Focus filter
  Escape         Clear selection   Ctrl+Q      Quit
        """,
    )
    parser.add_argument("--interval",       "-i", type=int, default=2,
        help="Auto-refresh interval in seconds (default: 2, min: 2, max: 120)")
    parser.add_argument("--max-rows",       "-m", type=int, default=2_000,
        help="Maximum rows to display (default: 2000)")
    parser.add_argument("--no-auto-refresh","-n", action="store_true",
        help="Disable auto-refresh on startup")
    parser.add_argument("--log-level",      "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING")
    parser.add_argument("--debug",          "-d", action="store_true",
        help="Enable DEBUG logging")
    parser.add_argument("--version",        "-v", action="store_true",
        help="Show version and exit")
    return parser.parse_args()


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    def _early_sigint(_sig: int, _frame: Any) -> None:
        sys.exit(1)
    signal.signal(signal.SIGINT, _early_sigint)

    args = parse_arguments()
    if args.version:
        print(f"porkill v{VERSION}")
        return 0

    setup_logging(getattr(logging, "DEBUG" if args.debug else args.log_level))

    # ── Wayland window-positioning workaround ────────────────────────────────
    # Wayland compositors do not honour move() by design — applications cannot
    # set their own screen position. Forcing xcb (XWayland) restores this
    # capability. XWayland is available on all major Wayland distros (GNOME,
    # KDE, Sway, Hyprland, etc.) and is always the right choice for a tool
    # that needs reliable window placement. We only apply this when the user
    # has not already set QT_QPA_PLATFORM explicitly.
    if "QT_QPA_PLATFORM" not in os.environ:
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland = os.environ.get("WAYLAND_DISPLAY", "")
        if session == "wayland" or wayland:
            os.environ["QT_QPA_PLATFORM"] = "xcb"
    # ────────────────────────────────────────────────────────────────────────

    app = QApplication(sys.argv)
    app.setApplicationName("porkill")
    app.setApplicationVersion(VERSION)
    # Note: setFallbackSessionManagementEnabled() was Qt5-only and removed in Qt6.
    # Session geometry restore is suppressed per-window via _q_noSaveGeometry below.

    # Privilege elevation
    if os.geteuid() != 0 and not os.environ.get("PORKILL_ELEVATION_ATTEMPTED"):
        os.environ["PORKILL_ELEVATION_ATTEMPTED"] = "1"
        has_display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        wants_elevation = False

        if has_display:
            try:
                app.setStyleSheet(build_stylesheet(resolve_mono_font()))
                dlg = ElevationDialog()
                dlg.exec()
                wants_elevation = dlg.result_yes
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("GUI elevation failed: %s. Falling back to CLI.", e)
                print("\n🛡️  Porkill — Gain full visibility? [y/N]: ", end="", flush=True)
                try:
                    wants_elevation = sys.stdin.readline().strip().lower() in ("y", "yes")
                except (KeyboardInterrupt, EOFError):
                    pass
        else:
            print("\n🛡️  Porkill — Gain full visibility? [y/N]: ", end="", flush=True)
            try:
                wants_elevation = sys.stdin.readline().strip().lower() in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                pass

        if wants_elevation:
            launcher = "pkexec" if has_display else "sudo"
            try:
                # PATH excluded intentionally — user PATH can be poisoned.
                # Hardcode a known-safe PATH for the elevated process.
                _SAFE = {
                    "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY",
                    "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS",
                    "HOME", "USER", "LANG", "LC_ALL", "TERM",
                    "PORKILL_ELEVATION_ATTEMPTED", "QT_QPA_PLATFORM",
                }
                env = {k: v.replace("\n","").replace("\r","")
                       for k, v in os.environ.items() if k in _SAFE}
                env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                cmd = ([launcher, "env"] + [f"{k}={v}" for k, v in env.items()]
                       + [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:])
                ret = subprocess.call(cmd)
                if ret == 0:
                    return 0
                # Fix #14: surface non-zero exit codes.
                # pkexec exits 126 on user cancel, 127 if not found — neither is an error.
                # Any other non-zero code is an unexpected failure worth logging.
                if launcher == "pkexec":
                    if ret not in (126, 127):
                        logger.warning("pkexec exited with code %d; falling back to sudo", ret)
                    sudo_cmd = (
                        ["sudo", "-E", sys.executable, os.path.abspath(sys.argv[0])]
                        + sys.argv[1:]
                    )
                    ret2 = subprocess.call(sudo_cmd)
                    if ret2 == 0:
                        return 0
                    if ret2 != 1:   # sudo exits 1 on wrong password / cancel — not surprising
                        logger.error("sudo elevation failed with exit code %d", ret2)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Elevation error: %s", e)
        else:
            print("\n" + "!" * 65)
            print("INFO: RUNNING AS NORMAL USER")
            print("Full process names for system sockets will be hidden.")
            print("!" * 65 + "\n")

    args.interval = max(2, min(120, args.interval))
    args.max_rows = max(100, args.max_rows)

    # Apply stylesheet and dark palette BEFORE window creation so no white flash ever occurs
    _mono = resolve_mono_font()
    app.setStyleSheet(build_stylesheet(_mono))
    # Also set app background via palette as a belt-and-suspenders guard
    _pal = app.palette()
    _dark = QColor(Config.BG)
    _pal.setColor(QPalette.ColorRole.Window,      _dark)
    _pal.setColor(QPalette.ColorRole.Base,        QColor(Config.BG2))
    _pal.setColor(QPalette.ColorRole.AlternateBase, QColor(Config.BG3))
    _pal.setColor(QPalette.ColorRole.WindowText,  QColor(Config.FG))
    _pal.setColor(QPalette.ColorRole.Text,        QColor(Config.FG))
    app.setPalette(_pal)

    win = PorkillWindow(args)
    # Tell KWin not to save/restore geometry for this window
    win.setProperty("_q_noSaveGeometry", True)

    # Size the window
    _W, _H = 1140, 760
    if _scr := QApplication.primaryScreen():
        _sg = _scr.availableGeometry()
        _W = max(960, min(_W, _sg.width()  - 40))
        _H = max(620, min(_H, _sg.height() - 40))
    win.resize(_W, _H)

    def _centre_win() -> None:
        scr = win.screen() or QApplication.primaryScreen()
        if scr:
            sg = scr.availableGeometry()
            win.move(
                sg.x() + (sg.width()  - _W) // 2,
                sg.y() + (sg.height() - _H) // 2,
            )

    _centre_win()
    win.show()
    _centre_win()
    # Single deferred centering to handle WM placement after compositing.
    # Replaces the previous cascade of 6 timers (80ms…1500ms).  (Fix #13)
    QTimer.singleShot(0, _centre_win)
    # Re-centre if the window migrates to a different screen (multi-monitor)
    if handle := win.windowHandle():
        handle.screenChanged.connect(lambda _scr: _centre_win())

    # Ctrl+C → close window gracefully
    # Safe SIGINT handler: set flag in signal handler, check via timer in main thread.
    # Calling win.close() or sys.exit() directly from a signal handler can deadlock Qt.
    _interrupted = [False]
    def _sigint_handler(_signum: int, _frame: Any) -> None:
        _interrupted[0] = True
    signal.signal(signal.SIGINT, _sigint_handler)
    _sigint_timer = QTimer()
    _sigint_timer.timeout.connect(lambda: win.close() if _interrupted[0] else None)  # type: ignore[union-attr]
    _sigint_timer.start(100)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())