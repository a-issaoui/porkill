#!/usr/bin/env python3
"""
porkill — Process & Port Monitor / Killer
A production-ready GUI application for monitoring and managing network ports and processes.

Usage:
    sudo python3 porkill_perfect.py [options]

Options:
    --interval SECONDS    Auto-refresh interval (default: 5, min: 2, max: 120)
    --max-rows N          Maximum rows to display (default: 10000)
    --no-auto-refresh     Disable auto-refresh on startup
    --log-level LEVEL     Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
"""

from __future__ import annotations

import argparse
import functools
import logging
import math
import os
import random
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, NamedTuple, Optional, Set, Tuple

# Configure logging before tkinter imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("porkill")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    import tkinter.font as tkfont

    _TK_AVAILABLE = True
except ImportError:
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]
    _TK_AVAILABLE = False

if not _TK_AVAILABLE:
    sys.exit(
        "porkill requires the tkinter package, which is not installed.\n\n"
        "Install it for your distribution:\n"
        "  Debian / Ubuntu : sudo apt install python3-tk\n"
        "  Fedora / RHEL   : sudo dnf install python3-tkinter\n"
        "  Arch Linux      : sudo pacman -S tk\n"
        "  Alpine Linux    : sudo apk add python3-tkinter\n"
        "  openSUSE        : sudo zypper install python3-tk\n"
        "  Gentoo          : USE=tk emerge dev-lang/python\n"
    )


# ============================================================================
# Configuration
# ============================================================================

class Config:
    """Application configuration with sensible defaults."""
    MAX_ROWS: int = 10_000
    SUBPROCESS_TIMEOUT: float = 5.0
    FILTER_DEBOUNCE_MS: int = 150
    FLASH_DURATION_MS: int = 3_000
    INODE_CACHE_TTL: float = 2.0
    MAX_PARENT_TRAVERSAL: int = 6
    ANIMATION_INTERVAL_MS: int = 40

    # Color scheme (cyberpunk dark)
    BG: str = "#080c08"
    BG2: str = "#0d140d"
    BG3: str = "#111a11"
    BG4: str = "#162016"
    NEON: str = "#39ff14"
    NEON_DIM: str = "#1a7a09"
    NEON_GLOW: str = "#7fff5a"
    RED: str = "#ff2a2a"
    AMBER: str = "#ffb300"
    CYAN: str = "#00ffcc"
    CYAN_DIM: str = "#006655"
    FG: str = "#c8e8c8"
    FG2: str = "#5a7a5a"
    BORDER: str = "#1e361e"
    SEL_BG: str = "#1a5c1a"


# ============================================================================
# Data Models
# ============================================================================

@dataclass(frozen=True, slots=True)
class PortRow:
    """Immutable data class representing a network port entry."""
    pid: str
    name: str
    proto: str
    addr: str
    port: str
    state: str
    group: str

    @property
    def sort_key_port(self) -> Tuple[int, int]:
        """Return sort key for port column (numeric first, then text)."""
        if self.port.isdigit():
            return 0, int(self.port)
        return 1, 0


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """Process information from /proc filesystem."""
    pid: str
    comm: str
    ppid: Optional[str] = None
    cmdline: str = ""


class InodeCacheEntry(NamedTuple):
    """Cached inode mapping with timestamp."""
    inode_map: Dict[str, Tuple[str, str]]
    timestamp: float


# ============================================================================
# Constants
# ============================================================================

_TCP_STATES: Dict[str, str] = {
    "01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV",
    "04": "FIN_WAIT1", "05": "FIN_WAIT2", "06": "TIME_WAIT",
    "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK",
    "0A": "LISTEN", "0B": "CLOSING",
}

_HELPER_NAMES: Set[str] = {
    "rootlessport", "slirp4netns", "pasta", "passt",
    "vpnkit-bridge", "rootlesskit",
}

_CONTAINER_RUNTIMES: Set[str] = {
    "podman", "docker", "containerd", "conmon", "crun", "runc",
    "buildah", "skopeo", "nerdctl",
}


# ============================================================================
# Utility Functions
# ============================================================================

def resolve_mono_font() -> str:
    """Return the best available monospace font family on this system."""
    try:
        available: Set[str] = set(tkfont.families())
        candidates = [
            "JetBrains Mono", "Fira Code", "Hack", "Inconsolata",
            "DejaVu Sans Mono", "Liberation Mono", "Noto Mono", "FreeMono",
            "Nimbus Mono PS", "Courier New", "Courier 10 Pitch", "Monospace",
        ]
        for candidate in candidates:
            if candidate in available:
                return candidate
    except OSError as e:
        logger.warning(f"Could not enumerate fonts: {e}")
    return "monospace"


def hex_to_ipv4(h: str) -> str:
    """Convert little-endian 32-bit hex string to dotted-quad IPv4 address."""
    try:
        return socket.inet_ntoa(struct.pack("<I", int(h, 16)))
    except (ValueError, struct.error) as e:
        logger.debug(f"Failed to convert IPv4 hex '{h}': {e}")
        return h


def hex_to_ipv6(h: str) -> str:
    """Convert four little-endian 32-bit words to a bracketed IPv6 address."""
    try:
        raw = b"".join(
            struct.pack("<I", int(h[i:i + 8], 16)) for i in range(0, 32, 8)
        )
        return f"[{socket.inet_ntop(socket.AF_INET6, raw)}]"
    except (ValueError, OSError) as e:
        logger.debug(f"Failed to convert IPv6 hex '{h}': {e}")
        return h


def read_proc_file(pid: str, filename: str) -> str:
    """Read a file from /proc/<pid>/ safely, returning empty string on error."""
    path = Path(f"/proc/{pid}/{filename}")
    try:
        return path.read_text().strip()
    except (OSError, IOError) as e:
        logger.debug(f"Could not read {path}: {e}")
        return ""


def read_proc_cmdline(pid: str) -> str:
    """Read process command line with null bytes replaced by spaces."""
    path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = path.read_bytes().replace(b"\x00", b" ")
        return raw.decode(errors="replace").strip()
    except (OSError, IOError) as e:
        logger.debug(f"Could not read cmdline for {pid}: {e}")
        return ""


def get_parent_pid(pid: str) -> Optional[str]:
    """Extract parent PID from /proc/<pid>/status."""
    status = read_proc_file(pid, "status")
    for line in status.splitlines():
        if line.startswith("PPid:"):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def find_container_runtime(pid: str, max_depth: int = Config.MAX_PARENT_TRAVERSAL) -> Optional[str]:
    """
    Walk up the process tree looking for a container runtime parent.

    Args:
        pid: Starting process ID
        max_depth: Maximum levels to traverse

    Returns:
        Name of container runtime if found, None otherwise
    """
    current = pid
    for _ in range(max_depth):
        ppid = get_parent_pid(current)
        if not ppid or ppid in ("0", "1"):
            break
        parent_name = read_proc_file(ppid, "comm")
        if parent_name in _CONTAINER_RUNTIMES:
            return parent_name
        current = ppid
    return None


def enrich_process_name(pid: str, raw_name: str) -> str:
    """
    Return a descriptive name for known container helper processes.

    Args:
        pid: Process ID
        raw_name: Raw process name from /proc

    Returns:
        Enriched name with container context if applicable
    """
    if raw_name not in _HELPER_NAMES:
        return raw_name

    cmdline = read_proc_cmdline(pid)
    container_hint = ""

    # Extract container name from cmdline if present
    if match := re.search(r"--container-name[= ](\S+)", cmdline):
        container_hint = match.group(1)

    # Look for container runtime parent
    runtime = find_container_runtime(pid)
    if runtime:
        if container_hint:
            return f"{runtime}[{container_hint}]"
        return f"{runtime}→{raw_name}"

    return raw_name


def resolve_group_name(pid: str, comm: str) -> str:
    """Return the display group name for a process row."""
    if pid == "—":
        return "kernel"

    if comm in _HELPER_NAMES:
        runtime = find_container_runtime(pid)
        if runtime:
            return runtime
        return "podman"

    return comm


# ============================================================================
# Port Data Fetching
# ============================================================================

class PortDataFetcher:
    """Thread-safe fetcher for network port data with caching."""

    def __init__(self) -> None:
        self._inode_cache: Optional[InodeCacheEntry] = None
        self._cache_lock = threading.Lock()

    def _get_inode_map(self) -> Dict[str, Tuple[str, str]]:
        """Build inode map with caching."""
        with self._cache_lock:
            now = time.monotonic()
            if (self._inode_cache is not None and
                    now - self._inode_cache.timestamp < Config.INODE_CACHE_TTL):
                logger.debug("Using cached inode map")
                return self._inode_cache.inode_map

            logger.debug("Building fresh inode map")
            inode_map = self._build_inode_map()
            self._inode_cache = InodeCacheEntry(inode_map, now)
            return inode_map

    @staticmethod
    def _build_inode_map() -> Dict[str, Tuple[str, str]]:
        """Build inode map of sockets to (pid, comm) by walking /proc/<pid>/fd."""
        inode_map: Dict[str, Tuple[str, str]] = {}
        proc_path = Path("/proc")

        try:
            pids = [entry.name for entry in proc_path.iterdir()
                    if entry.is_dir() and entry.name.isdigit()]
        except OSError as e:
            logger.warning(f"Could not list /proc: {e}")
            return inode_map

        for pid in pids:
            fd_dir = proc_path / pid / "fd"
            try:
                fds = list(fd_dir.iterdir())
            except (OSError, PermissionError):
                continue

            for fd in fds:
                try:
                    target = str(fd.readlink())
                except (OSError, ValueError):
                    continue

                if not target.startswith("socket:["):
                    continue

                inode = target[8:-1]
                if inode in inode_map:
                    continue

                name = read_proc_file(pid, "comm") or "unknown"
                inode_map[inode] = (pid, name)

        return inode_map

    def _parse_proc_net(self) -> List[PortRow]:
        """Pure-Python port scanner reading /proc/net/{tcp,tcp6,udp,udp6}."""
        inode_map = self._get_inode_map()
        rows: List[PortRow] = []
        seen: Set[Tuple[str, str, str]] = set()

        sources = [
            ("/proc/net/tcp", "TCP", False),
            ("/proc/net/tcp6", "TCP", True),
            ("/proc/net/udp", "UDP", False),
            ("/proc/net/udp6", "UDP", True),
        ]

        for path, proto, is_v6 in sources:
            try:
                with open(path, "r") as fh:
                    lines = fh.readlines()[1:]  # Skip header
            except OSError as e:
                logger.debug(f"Could not read {path}: {e}")
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

                addr = hex_to_ipv6(hex_addr) if is_v6 else hex_to_ipv4(hex_addr)
                state = _TCP_STATES.get(state_hex, state_hex) if proto == "TCP" else "—"

                pid, name = inode_map.get(inode, ("—", "kernel"))
                name = enrich_process_name(pid, name)
                group = resolve_group_name(pid, name)

                key = inode
                if key in seen:
                    continue
                seen.add(key)

                rows.append(PortRow(
                    pid=pid, name=name, proto=proto,
                    addr=addr, port=port, state=state, group=group
                ))

        return rows

    @staticmethod
    def _parse_ss_output() -> Optional[List[PortRow]]:
        """Parse output from 'ss -tulpn' command."""
        try:
            result = subprocess.run(
                ["ss", "-tulpn"],
                capture_output=True, text=True,
                timeout=Config.SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.debug(f"ss returned non-zero: {result.stderr}")
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Could not run ss: {e}")
            return None

        rows: List[PortRow] = []
        seen: Set[Tuple[str, str, str]] = set()

        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue

            proto, state, local, *_, proc_field = parts[0], parts[1], parts[4], parts[-1]

            if not (match := re.search(r":(\d+)$", local)):
                continue
            port = match.group(1)
            addr = local[:-(len(port) + 1)]

            pids = re.findall(r"pid=(\d+)", proc_field)
            names = re.findall(r'"([^"]+)"', proc_field)

            if not pids:
                pids = ["—"]
                names = names or ["kernel"]

            # Pad names to match pid count
            names.extend([names[-1]] * (len(pids) - len(names)))

            proto_norm = "TCP" if "tcp" in proto.lower() else "UDP"

            for pid, name in zip(pids, names):
                key = (pid, port, proto_norm)
                if key in seen:
                    continue
                seen.add(key)

                rows.append(PortRow(
                    pid=pid, name=enrich_process_name(pid, name),
                    proto=proto_norm, addr=addr, port=port,
                    state=state, group=resolve_group_name(pid, name)
                ))

        return rows if rows else None

    @staticmethod
    def _parse_netstat_output() -> Optional[List[PortRow]]:
        """Parse output from 'netstat -tulpn' command."""
        try:
            result = subprocess.run(
                ["netstat", "-tulpn"],
                capture_output=True, text=True,
                timeout=Config.SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Could not run netstat: {e}")
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
            if proto == "TCP":
                state = parts[5]
                proc = parts[-1]
            else:
                state = "—"
                proc = parts[5] if len(parts) >= 6 else "—"

            if not (match := re.search(r":(\d+)$", local)):
                continue
            port = match.group(1)
            addr = local[:-(len(port) + 1)]

            if match := re.match(r"(\d+)/(.*)", proc):
                pid, name = match.group(1), match.group(2)
            else:
                pid, name = "—", proc

            key = (pid, port, proto)
            if key in seen:
                continue
            seen.add(key)

            rows.append(PortRow(
                pid=pid, name=enrich_process_name(pid, name),
                proto=proto, addr=addr, port=port,
                state=state, group=resolve_group_name(pid, name)
            ))

        return rows if rows else None

    def fetch(self) -> Tuple[List[PortRow], Optional[str]]:
        """
        Fetch port data using the best available method.

        Returns:
            Tuple of (rows, error_message). error_message is None on success.
        """
        # Try ss first (fastest, most detailed)
        if rows := self._parse_ss_output():
            logger.info(f"Fetched {len(rows)} rows via ss")
            return rows, None

        # Fall back to netstat
        if rows := self._parse_netstat_output():
            logger.info(f"Fetched {len(rows)} rows via netstat")
            return rows, None

        # Last resort: parse /proc/net directly
        rows = self._parse_proc_net()
        if rows:
            logger.info(f"Fetched {len(rows)} rows via /proc/net")
            return rows, None

        return [], "Could not fetch port data from any source"


# ============================================================================
# Process Management
# ============================================================================

def validate_pid(pid: str) -> Tuple[bool, int, str]:
    """
    Validate a PID string.

    Returns:
        Tuple of (is_valid, pid_int, error_message)
    """
    if not pid or not pid.isdigit():
        return False, 0, f"Invalid PID format: {pid!r}"

    pid_int = int(pid)
    if pid_int <= 0:
        return False, 0, f"PID must be positive, got {pid_int}"

    return True, pid_int, ""


def send_signal_to_pid(pid: str, sig: signal.Signals) -> Tuple[bool, str]:
    """
    Send signal to process, escalating to sudo/doas if permission denied.

    Args:
        pid: Process ID as string
        sig: Signal to send

    Returns:
        Tuple of (success, error_message)
    """
    is_valid, pid_int, error = validate_pid(pid)
    if not is_valid:
        return False, error

    # Try direct kill first
    try:
        os.kill(pid_int, sig)
        logger.info(f"Sent signal {sig.name} to PID {pid_int}")
        return True, ""
    except PermissionError:
        pass
    except OSError as exc:
        return False, str(exc)

    # Escalate privileges
    last_err = "No privilege escalation tool available (tried sudo, doas)"
    sig_num = int(sig)

    for cmd_base in (["sudo", "-n"], ["doas"]):
        cmd = cmd_base + ["kill", f"-{sig_num}", str(pid_int)]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=Config.SUBPROCESS_TIMEOUT,
                preexec_fn=os.setsid,
            )
            if result.returncode == 0:
                logger.info(f"Sent signal {sig.name} to PID {pid_int} via {cmd_base[0]}")
                return True, ""
            last_err = result.stderr.strip() or f"{cmd_base[0]}: non-zero exit"
        except FileNotFoundError:
            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_err = str(exc)
            break

    return False, last_err


# ============================================================================
# UI Components
# ============================================================================

class FontSpec(NamedTuple):
    """Font specification tuple."""
    family: str
    size: int
    weight: str = "normal"


class LogoCanvas(tk.Canvas):
    """
    Animated background (matrix rain, grid, corner HUD) with a static
    'PORKILL' logo rendered as large bold text on top.
    """

    _RAIN_CHARS = "01アイウエオカキクケコサシスセソタチツテトナニヌネノ"

    def __init__(self, master: tk.Misc, auto_animate: bool = True, **kwargs: Any) -> None:
        super().__init__(
            master, bg=Config.BG, highlightthickness=0,
            height=190, **kwargs
        )
        self._phase    = 0.0
        self._after_id: Optional[str] = None
        self._destroyed = False

        # Matrix rain columns: [x, y, speed, char_idx]
        self._rain_cols: List[List[Any]] = []
        self._rain_initialized = False

        self.bind("<Configure>", self._on_configure)
        if auto_animate:
            self._animate()

    # ------------------------------------------------------------------
    # Setup / helpers
    # ------------------------------------------------------------------

    def _on_configure(self, _event: Any = None) -> None:
        self._rain_initialized = False
        # Do not call _draw() here in tests to verify the reset state
        if self.winfo_width() > 1 and self.winfo_height() > 1:
            self._draw()

    def _init_rain(self, width: int, height: int) -> None:
        self._rain_cols = []
        for x in range(0, width, 14):
            self._rain_cols.append([
                x,
                random.uniform(0, height),
                random.uniform(0.4, 1.4),
                random.randint(0, len(self._RAIN_CHARS) - 1),
            ])
        self._rain_initialized = True

    @staticmethod
    def _lerp_color(a: str, b: str, t: float) -> str:
        t = max(0.0, min(1.0, t))
        ar, ag, ab_ = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        br, bg_, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
        return (f"#{int(ar+(br-ar)*t):02x}"
                f"{int(ag+(bg_-ag)*t):02x}"
                f"{int(ab_+(bb-ab_)*t):02x}")

    # ------------------------------------------------------------------
    # Draw layers
    # ------------------------------------------------------------------

    def _draw_background_grid(self, width: int, height: int) -> None:
        for x in range(0, width, 32):
            self.create_line(x, 0, x, height, fill="#090f09", width=1)
        for y in range(0, height, 16):
            self.create_line(0, y, width, y, fill="#090f09", width=1)

    def _draw_matrix_rain(self, width: int, height: int) -> None:
        if not self._rain_initialized:
            self._init_rain(width, height)
        for col in self._rain_cols:
            x, y, _spd, ci = col
            char = self._RAIN_CHARS[ci % len(self._RAIN_CHARS)]
            fill = Config.NEON_DIM if random.random() > 0.7 else "#0a2a0a"
            self.create_text(x, int(y) % height, text=char,
                             font=("Monospace", 8), fill=fill, anchor="nw")

    def _draw_logo(self, width: int, height: int, pulse: float) -> None:
        """Draw static 'PORKILL' text with glow shadow."""
        cx = width // 2
        cy = height // 2 - 10

        # Glow shadow (slightly offset, dimmer)
        glow = self._lerp_color(Config.NEON_DIM, Config.NEON, pulse * 0.6)
        for dx, dy in ((-2, -2), (2, -2), (-2, 2), (2, 2), (0, 3), (0, -3)):
            self.create_text(cx + dx, cy + dy, text="PORKILL",
                             font=("Monospace", 38, "bold"),
                             fill=glow, anchor="center")

        # Main text
        self.create_text(cx, cy, text="PORKILL",
                         font=("Monospace", 38, "bold"),
                         fill=Config.NEON, anchor="center")

        # Subtitle
        sub_col = self._lerp_color(Config.NEON_DIM, Config.FG2, pulse * 0.7)
        cursor  = "█" if int(self._phase / 18) % 2 == 0 else " "
        self.create_text(cx, cy + 46,
                         text=f"[ Process & Port Monitor // Kill with Precision ]{cursor}",
                         font=("Monospace", 9), fill=sub_col, anchor="center")

        # Author credit
        author_col = self._lerp_color(Config.CYAN_DIM, Config.CYAN, pulse * 0.5)
        self.create_text(cx, cy + 64,
                         text="⌬ by a-issaoui  ·  github.com/a-issaoui",
                         font=("Monospace", 8), fill=author_col, anchor="center")

    def _draw_corner_hud(self, width: int, height: int, pulse: float) -> None:
        arm  = int(22 + pulse * 10)
        pad  = 6
        col  = self._lerp_color(Config.NEON_DIM, Config.NEON, pulse)
        col2 = self._lerp_color("#003322", Config.CYAN_DIM, pulse)

        for cx, cy, dx, dy in [
            (pad, pad, 1, 1), (width - pad, pad, -1, 1),
            (pad, height - pad, 1, -1), (width - pad, height - pad, -1, -1),
        ]:
            self.create_line(cx, cy, cx + dx * arm, cy, fill=col, width=2)
            self.create_line(cx, cy, cx, cy + dy * arm, fill=col, width=2)
            for t in range(3, arm, 6):
                self.create_line(cx + dx * t, cy, cx + dx * t, cy + dy * 3,
                                  fill=col2, width=1)
            self.create_rectangle(cx - 1, cy - 1, cx + 1, cy + 1,
                                   fill=Config.NEON_GLOW, outline="")

        mid_x    = width // 2
        line_len = int(30 + pulse * 20)
        self.create_line(mid_x - line_len, pad, mid_x + line_len, pad,
                          fill=col2, width=1)
        self.create_line(mid_x - line_len, height - pad,
                          mid_x + line_len, height - pad, fill=col2, width=1)
        self.create_line(mid_x, pad, mid_x, pad + 5, fill=col, width=2)
        self.create_line(mid_x, height - pad, mid_x, height - pad - 5,
                          fill=col, width=2)

    # ------------------------------------------------------------------
    # Main draw
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        if self._destroyed:
            return

        self.delete("all")
        width  = self.winfo_width()  or 1000
        height = self.winfo_height() or 190
        pulse  = (math.sin(self._phase * 0.06) + 1) / 2

        self._draw_background_grid(width, height)
        self._draw_matrix_rain(width, height)
        self._draw_logo(width, height, pulse)
        self._draw_corner_hud(width, height, pulse)

    # ------------------------------------------------------------------
    # Animation loop
    # ------------------------------------------------------------------

    def _animate(self) -> None:
        if self._destroyed or not self.winfo_exists():
            return

        try:
            self._phase += 1.0

            if self._rain_initialized:
                for col in self._rain_cols:
                    col[1] += col[2] * 2.0
                    if col[1] > (self.winfo_height() or 190):
                        col[1] = random.uniform(-40, 0)
                        col[3] = random.randint(0, len(self._RAIN_CHARS) - 1)
                    else:
                        col[3] = (col[3] + 1) % len(self._RAIN_CHARS)

            self._draw()

        except tk.TclError:
            return
        except Exception as e:
            logger.error(f"Animation error: {e}")
            return

        self._after_id = self.after(Config.ANIMATION_INTERVAL_MS, self._animate)  # type: ignore

    def destroy(self) -> None:
        self._destroyed = True
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.delete("all")
        super().destroy()


class StatBadge(tk.Frame):
    """Labelled numeric counter widget."""

    def __init__(self, master: tk.Misc, label: str, color: str, **kwargs: Any) -> None:
        super().__init__(master, bg=Config.BG, **kwargs)
        self._var = tk.StringVar(value="0")

        tk.Label(
            self, text=label, font=("Monospace", 9),
            bg=Config.BG, fg=Config.FG2
        ).pack(anchor="w")

        tk.Label(
            self, textvariable=self._var,
            font=("Monospace", 14, "bold"),
            bg=Config.BG, fg=color
        ).pack(anchor="w")

    def set(self, value: int) -> None:
        """Update the displayed value."""
        self._var.set(str(value))


class KillButton(tk.Canvas):
    """Canvas-drawn button with hover and press states."""

    _WIDTH = 180
    _HEIGHT = 38

    def __init__(
            self, master: tk.Misc, text: str, color: str,
            command: Callable[[], None], **kwargs: Any
    ) -> None:
        super().__init__(
            master, bg=Config.BG, highlightthickness=0,
            width=self._WIDTH, height=self._HEIGHT,
            cursor="hand2", **kwargs
        )
        self._text = text
        self._color = color
        self._command = command
        self._hover = False
        self._pressed = False

        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._on_press())
        self.bind("<ButtonRelease-1>", lambda _e: self._on_release())

        self._draw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _on_press(self) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self) -> None:
        self._pressed = False
        self._draw()
        if self._hover:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        width, height = self._WIDTH, self._HEIGHT
        color = self._color

        if self._pressed:
            fill, fg = color, Config.BG
        elif self._hover:
            fill, fg = Config.BG4, color
        else:
            fill, fg = Config.BG3, color

        if self._hover:
            self.create_rectangle(
                1, 1, width - 1, height - 1,
                outline=color, width=2
            )
            self.create_rectangle(
                3, 3, width - 3, height - 3,
                outline=Config.BORDER, width=1
            )
        else:
            self.create_rectangle(
                1, 1, width - 1, height - 1,
                outline=Config.BORDER, width=1
            )

        self.create_rectangle(2, 2, width - 2, height - 2, fill=fill, outline="")

        # Corner accents
        corners = [
            (2, 2, 1, 1), (width - 2, 2, -1, 1),
            (2, height - 2, 1, -1), (width - 2, height - 2, -1, -1)
        ]
        for cx, cy, dx, dy in corners:
            self.create_line(cx, cy, cx + dx * 8, cy, fill=color, width=1)
            self.create_line(cx, cy, cx, cy + dy * 8, fill=color, width=1)

        self.create_text(
            width // 2, height // 2,
            text=self._text, font=("Monospace", 10),
            fill=fg, anchor="center"
        )


# ============================================================================
# Main Application
# ============================================================================

class Porkill(tk.Tk):
    """Main application window for porkill."""

    _COLUMN_HEADERS: ClassVar[Dict[str, str]] = {
        "pid": "PID",
        "name": "PROCESS NAME",
        "proto": "PROTO",
        "addr": "LOCAL ADDRESS",
        "port": "PORT",
        "state": "STATE",
    }

    def __init__(self, config: Optional[argparse.Namespace] = None) -> None:
        super().__init__(className="porkill")

        # Apply configuration
        if config:
            Config.MAX_ROWS = config.max_rows
            self._auto_refresh_interval = max(2, min(120, config.interval))
            self._auto_refresh_enabled = not config.no_auto_refresh
        else:
            self._auto_refresh_interval = 5
            self._auto_refresh_enabled = True

        # Resolve monospace font
        self._mono_font = resolve_mono_font()

        self.title("porkill")
        self.configure(bg=Config.BG)
        self.minsize(900, 600)

        # Try to load and set window icon
        self._icon = None  # Prevent GC
        icon_paths = [
            os.path.join(os.path.dirname(__file__), "porkill.png"),
            "/usr/share/icons/hicolor/256x256/apps/porkill.png",
            "/usr/local/share/icons/hicolor/256x256/apps/porkill.png",
        ]
        for ip in icon_paths:
            if os.path.exists(ip):
                try:
                    self._icon = tk.PhotoImage(file=ip)
                    self.iconphoto(True, self._icon)
                    break
                except Exception:
                    continue

        # Center window on screen
        self.update_idletasks()
        width, height = 1100, 740
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        # State variables
        self._auto = tk.BooleanVar(value=self._auto_refresh_enabled)
        self._every = tk.IntVar(value=self._auto_refresh_interval)
        self._filter_text = tk.StringVar()
        self._status_var = tk.StringVar(value="INITIALIZING...")
        self._info_var = tk.StringVar(value="-- no process selected --")

        self._sort_column: str = "port"
        self._sort_reverse: bool = False
        self._all_rows: List[PortRow] = []
        self._item_sequence: int = 0
        self._selected_key: Optional[Tuple[str, str, str, str]] = None
        self._selected_group: Optional[str] = None  # grp: iid if a group header is selected
        self._pre_click_iid: str = ""
        self._collapsed_groups: Set[str] = set()
        self._rebuilding: bool = False

        # Threading
        self._fetch_lock = threading.RLock()
        self._fetching: bool = False
        self._refresh_job: Optional[str] = None
        self._filter_job: Optional[str] = None
        self._shutdown_event = threading.Event()

        # Data fetcher
        self._fetcher = PortDataFetcher()

        # Widget references (initialized in _build_ui)
        self._s_total: StatBadge
        self._s_listen: StatBadge
        self._s_udp: StatBadge
        self.tree: ttk.Treeview

        # Bind filter text changes
        self._filter_text.trace_add("write", lambda _n, _i, _m: self._schedule_filter())

        # Build UI
        self._build_ui()

        # Schedule initial refresh
        self._schedule_refresh()

        # Bind keyboard shortcuts
        self._bind_shortcuts()

    def _font(self, size: int, weight: str = "normal") -> Tuple[str, int, str]:
        """Return font tuple with resolved monospace family."""
        return self._mono_font, size, weight

    def _build_ui(self) -> None:
        """Build the user interface."""
        # Logo
        LogoCanvas(self).pack(fill="x")
        tk.Frame(self, bg=Config.NEON, height=1).pack(fill="x")

        # Control bar
        self._build_control_bar()

        # Filter bar
        self._build_filter_bar()

        # Treeview
        tk.Frame(self, bg=Config.BORDER, height=1).pack(fill="x")
        tv_frame = tk.Frame(self, bg=Config.BG)
        tv_frame.pack(fill="both", expand=True)
        self._setup_treeview(tv_frame)

        # Action bar
        tk.Frame(self, bg=Config.NEON, height=1).pack(fill="x")
        self._build_action_bar()

    def _build_control_bar(self) -> None:
        """Build the top control bar with stats and controls."""
        ctrl = tk.Frame(self, bg=Config.BG, pady=8, padx=16)
        ctrl.pack(fill="x")

        # Stats badges
        stats = tk.Frame(ctrl, bg=Config.BG)
        stats.pack(side="left")

        self._s_total = StatBadge(stats, "TOTAL", Config.CYAN)
        self._s_total.pack(side="left", padx=(0, 20))

        self._s_listen = StatBadge(stats, "LISTEN", Config.NEON)
        self._s_listen.pack(side="left", padx=(0, 20))

        self._s_udp = StatBadge(stats, "UDP", Config.AMBER)
        self._s_udp.pack(side="left", padx=(0, 20))

        # Right side controls
        right = tk.Frame(ctrl, bg=Config.BG)
        right.pack(side="right")

        tk.Label(
            right, text="AUTO-REFRESH", font=self._font(9),
            bg=Config.BG, fg=Config.FG2
        ).pack(side="left")

        tk.Checkbutton(
            right, variable=self._auto, onvalue=True, offvalue=False,
            command=self._toggle_auto, bg=Config.BG, fg=Config.NEON,
            selectcolor=Config.BG3, activebackground=Config.BG,
            activeforeground=Config.NEON, cursor="hand2", relief="flat"
        ).pack(side="left", padx=4)

        tk.Label(
            right, text="EVERY", font=self._font(9),
            bg=Config.BG, fg=Config.FG2
        ).pack(side="left", padx=(8, 4))

        # Validate spinbox input
        vcmd = (self.register(self._validate_interval), "%P")
        spinbox = tk.Spinbox(
            right, from_=2, to=120, textvariable=self._every,
            width=3, font=self._font(9), bg=Config.BG3, fg=Config.NEON,
            insertbackground=Config.NEON, buttonbackground=Config.BG3,
            relief="flat", disabledbackground=Config.BG3,
            validate="key", validatecommand=vcmd
        )
        spinbox.pack(side="left")

        tk.Label(
            right, text="s", font=self._font(9),
            bg=Config.BG, fg=Config.FG2
        ).pack(side="left", padx=(2, 16))

        KillButton(
            right, "↻  REFRESH NOW", Config.CYAN, self._schedule_refresh
        ).pack(side="left")

    @staticmethod
    def _validate_interval(value: str) -> bool:
        """Validate spinbox input is numeric."""
        if value == "":
            return True
        return value.isdigit() and 0 < int(value) <= 120

    def _build_filter_bar(self) -> None:
        """Build the filter input bar."""
        fbar = tk.Frame(self, bg=Config.BG2, pady=7, padx=16)
        fbar.pack(fill="x")

        tk.Frame(fbar, bg=Config.NEON, width=3, height=22).pack(
            side="left", padx=(0, 10)
        )

        tk.Label(
            fbar, text="FILTER ❯", font=self._font(10),
            bg=Config.BG2, fg=Config.NEON
        ).pack(side="left")

        tk.Entry(
            fbar, textvariable=self._filter_text, font=self._font(10),
            bg=Config.BG3, fg=Config.NEON, insertbackground=Config.NEON,
            relief="flat", bd=6, width=36, highlightthickness=1,
            highlightbackground=Config.BORDER, highlightcolor=Config.NEON
        ).pack(side="left", padx=10)

        tk.Label(
            fbar, text="name · pid · port · proto · state",
            font=self._font(9), bg=Config.BG2, fg=Config.FG2
        ).pack(side="left")

        tk.Label(
            fbar, textvariable=self._status_var,
            font=self._font(9), bg=Config.BG2, fg=Config.FG2
        ).pack(side="right")

    def _setup_treeview(self, parent: tk.Frame) -> None:
        """Configure the treeview widget."""
        cols = ("pid", "name", "proto", "addr", "port", "state")
        heads = ("PID", "PROCESS NAME", "PROTO", "LOCAL ADDRESS", "PORT", "STATE")

        # Configure style
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "P.Treeview", background=Config.BG2, fieldbackground=Config.BG2,
            foreground=Config.FG, rowheight=26, borderwidth=0,
            font=self._font(10), indent=16
        )
        style.configure(
            "P.Treeview.Heading", background=Config.BG3,
            foreground="#4da6ff", font=self._font(12, "bold"),
            relief="flat", borderwidth=0
        )
        style.map(
            "P.Treeview",
            background=[("selected", Config.SEL_BG)],
            foreground=[("selected", Config.NEON_GLOW)],
            font=[("selected", self._font(12, "bold"))]
        )
        style.map("P.Treeview.Heading", background=[("active", Config.BG4)])
        style.configure(
            "Vertical.TScrollbar", troughcolor=Config.BG,
            background=Config.BG4, arrowcolor=Config.NEON, borderwidth=0
        )

        self.tree = ttk.Treeview(
            parent, columns=cols, show="tree headings",
            style="P.Treeview", selectmode="browse"
        )

        self.tree.column("#0", width=320, minwidth=120, stretch=True, anchor="w")
        self.tree.heading("#0", text="", anchor="w")

        widths = [72, 200, 60, 160, 72, 100]
        for col, hdr, w in zip(cols, heads, widths):
            arrow = " ↑" if col == self._sort_column else " ↕"
            self.tree.heading(
                col, text=f"{hdr}{arrow}", anchor="w",
                command=functools.partial(self._sort, col)
            )
            self.tree.column(col, width=w, anchor="w", minwidth=36)

        # Configure tags
        self.tree.tag_configure("even", background=Config.BG2)
        self.tree.tag_configure("odd", background=Config.BG3)
        self.tree.tag_configure("listen", foreground=Config.NEON)
        self.tree.tag_configure("udp", foreground=Config.AMBER)
        self.tree.tag_configure("kernel", foreground=Config.CYAN_DIM)
        self.tree.tag_configure(
            "group_hdr", background="#0a1a0a",
            foreground=Config.NEON, font=self._font(12, "bold")
        )

        # Bind events
        def on_open(_event: tk.Event) -> None:  # type: ignore[type-arg]
            if self._rebuilding:
                return
            iid = self.tree.focus()
            if iid and iid.startswith("grp:"):
                self._collapsed_groups.discard(iid)

        def on_close(_event: tk.Event) -> None:  # type: ignore[type-arg]
            if self._rebuilding:
                return
            iid = self.tree.focus()
            if iid and iid.startswith("grp:"):
                self._collapsed_groups.add(iid)

        self.tree.bind("<<TreeviewOpen>>", on_open)
        self.tree.bind("<<TreeviewClose>>", on_close)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self._kill(signal.SIGTERM))
        self.tree.bind("<ButtonPress-1>", self._on_click_pre)
        self.tree.bind("<ButtonRelease-1>", self._on_click_toggle)

        # Scrollbar
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _build_action_bar(self) -> None:
        """Build the bottom action bar."""
        abar = tk.Frame(self, bg=Config.BG, pady=10, padx=16)
        abar.pack(fill="x")

        tk.Label(
            abar, textvariable=self._info_var,
            font=self._font(10), bg=Config.BG, fg=Config.FG2, anchor="w"
        ).pack(side="left")

        btn_frame = tk.Frame(abar, bg=Config.BG)
        btn_frame.pack(side="right")

        KillButton(
            btn_frame, ">>  SIGTERM (graceful)", Config.AMBER,
            lambda: self._kill(signal.SIGTERM)
        ).pack(side="left", padx=8)

        KillButton(
            btn_frame, ">>  SIGKILL  (-9)", Config.RED,
            lambda: self._kill(signal.SIGKILL)
        ).pack(side="left")

    def _bind_shortcuts(self) -> None:
        """Bind keyboard shortcuts."""
        self.bind("<Control-r>", lambda _e: self._schedule_refresh())
        self.bind("<F5>", lambda _e: self._schedule_refresh())
        self.bind("<Delete>", lambda _e: self._kill(signal.SIGTERM))
        self.bind("<Control-k>", lambda _e: self._kill(signal.SIGKILL))
        self.bind("<Escape>", lambda _e: self._clear_selection())
        self.bind("<Control-f>", lambda _e: self._focus_filter())
        self.bind("<Control-q>", lambda _e: self.quit_app())

    def _focus_filter(self) -> None:
        """Focus the filter entry field."""
        # Find the filter entry and focus it
        for child in self.winfo_children():
            if isinstance(child, tk.Frame):
                for subchild in child.winfo_children():
                    if isinstance(subchild, tk.Entry):
                        subchild.focus_set()
                        return

    def _clear_selection(self) -> None:
        """Clear the current selection."""
        self.tree.selection_set()
        self._selected_key = None
        self._selected_group = None
        self._info_var.set("-- no process selected --")

    def quit_app(self) -> None:
        """Gracefully quit the application."""
        self._shutdown_event.set()
        self._cancel_pending_jobs()
        self.quit()

    def _cancel_pending_jobs(self) -> None:
        """Cancel all pending after() jobs."""
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
            self._filter_job = None

    def _schedule_refresh(self) -> None:
        """Cancel any pending refresh and start a new fetch cycle."""
        if not self.winfo_exists():
            return

        self._cancel_refresh_job()
        self._status_var.set("SCANNING...")
        self._launch_fetch()

        if self._auto.get():
            delay = max(2, self._every.get()) * 1000
            self._refresh_job = self.after(delay, self._on_refresh_tick) # type: ignore

    def _cancel_refresh_job(self) -> None:
        """Cancel the pending refresh job."""
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None

    def _on_refresh_tick(self) -> None:
        """Handle refresh timer tick."""
        self._refresh_job = None
        self._schedule_refresh()

    def _launch_fetch(self) -> None:
        """Spawn fetch thread only when no fetch is already running."""
        with self._fetch_lock:
            if self._fetching:
                logger.debug("Fetch already in progress, skipping")
                return
            self._fetching = True

        thread = threading.Thread(target=self._fetch_worker, daemon=True)
        thread.start()

    def _fetch_worker(self) -> None:
        """Fetch port data in background and schedule UI update."""
        rows: List[PortRow] = []
        error_msg: Optional[str] = None

        try:
            rows, error_msg = self._fetcher.fetch()
        except Exception as exc:
            logger.exception("Unexpected error during fetch")
            error_msg = str(exc)
        finally:
            with self._fetch_lock:
                self._fetching = False

            # Schedule UI update on main thread
            if not self._shutdown_event.is_set():
                try:
                    self.after(0, lambda: self._populate(rows, error_msg)) # type: ignore
                except (tk.TclError, RuntimeError):
                    pass # App is likely shutting down or destroyed

    def _populate(self, rows: List[PortRow], error_msg: Optional[str] = None) -> None:
        """Update UI with fetched data."""
        if not self.winfo_exists():
            return

        if error_msg:
            self._status_var.set(f"ERROR: {error_msg[:50]}")
            logger.error(f"Fetch error: {error_msg}")
            return

        truncated = len(rows) > Config.MAX_ROWS
        if truncated:
            rows = rows[:Config.MAX_ROWS]

        self._all_rows = rows
        self._update_stats(rows)
        self._do_apply_filter()

        ts = time.strftime("%H:%M:%S")
        if truncated:
            self._status_var.set(f"⚠ TRUNCATED to {Config.MAX_ROWS} rows — {ts}")
        else:
            self._status_var.set(f"UPDATED {ts}")

        # Clear to free memory (treeview holds its own copy)
        rows.clear()

    def _update_stats(self, rows: List[PortRow]) -> None:
        """Update statistics badges."""
        self._s_total.set(len(rows))
        self._s_listen.set(sum(1 for r in rows if r.state.upper() == "LISTEN"))
        self._s_udp.set(sum(1 for r in rows if r.proto == "UDP"))

    def _schedule_filter(self) -> None:
        """Schedule filter application with debouncing."""
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(Config.FILTER_DEBOUNCE_MS, self._on_filter_tick) # type: ignore

    def _on_filter_tick(self) -> None:
        """Handle filter timer tick."""
        self._filter_job = None
        self._do_apply_filter()

    def _do_apply_filter(self) -> None:
        """Rebuild the Treeview applying filter, sort, and grouping."""
        if not self.winfo_exists():
            return

        query = self._filter_text.get().strip().lower()

        # Apply filter
        visible = [
            r for r in self._all_rows
            if not query or any(query in str(v).lower() for v in [
                r.pid, r.name, r.proto, r.addr, r.port, r.state
            ])
        ]

        # Apply sort
        if self._sort_column:
            decorated = [
                (self._get_sort_key(r), idx, r) for idx, r in enumerate(visible)
            ]
            decorated.sort(key=lambda t: (t[0], t[1]), reverse=self._sort_reverse)
            visible = [r for _, _, r in decorated]

        # Save selection
        sel = self.tree.selection()
        if sel:
            try:
                iid = sel[0]
                vals = self.tree.item(iid, "values")
                if iid.startswith("grp:"):
                    self._selected_group = iid  # remember by stable grp: iid
                    self._selected_key = None
                elif vals and vals[0]:
                    self._selected_key = (vals[0], vals[1], vals[2], vals[4])
                    self._selected_group = None
            except tk.TclError:
                pass

        # Clear treeview (batched for performance)
        self._rebuilding = True
        children = self.tree.get_children()
        for start in range(0, len(children), 200):
            self.tree.delete(*children[start:start + 200])
        self._rebuilding = False

        # Reset sequence if too large
        if self._item_sequence > 1_000_000:
            self._item_sequence = 0

        # Group by process group
        groups: Dict[str, List[PortRow]] = {}
        for row in visible:
            g = row.group or row.name
            groups.setdefault(g, []).append(row)

        restore_iid: Optional[str] = None

        # Populate treeview
        for g_name, g_rows in groups.items():
            grp_iid = f"grp:{g_name}"
            count = len(g_rows)
            suffix = "ports" if count != 1 else "port"
            is_open = grp_iid not in self._collapsed_groups

            # Store PID of first child so group header is killable
            group_pid = g_rows[0].pid if g_rows else ""
            group_proc_name = g_rows[0].name if g_rows else g_name

            self.tree.insert(
                "", "end", iid=grp_iid,
                text=f"  {g_name.upper()}   ({count} {suffix})",
                values=(group_pid, group_proc_name, "", "", "", ""),
                tags=("group_hdr",), open=is_open
            )
            if self._selected_group and grp_iid == self._selected_group:
                restore_iid = grp_iid

            for i, row in enumerate(g_rows):
                self._item_sequence += 1
                iid = f"r{self._item_sequence}"

                tags: List[str] = ["even" if i % 2 == 0 else "odd"]
                if row.state.upper() == "LISTEN":
                    tags.append("listen")
                elif row.proto == "UDP":
                    tags.append("udp")
                if row.pid == "—":
                    tags.append("kernel")

                self.tree.insert(
                    grp_iid, "end", iid=iid,
                    values=(row.pid, row.name, row.proto, row.addr, row.port, row.state),
                    tags=tags
                )

                if self._selected_key:
                    key = (row.pid, row.name, row.proto, row.port)
                    if key == self._selected_key:
                        restore_iid = iid

        # Restore selection
        if restore_iid:
            self.tree.selection_set(restore_iid)
            self.tree.see(restore_iid)
        else:
            self._selected_key = None
            self._info_var.set("-- no process selected --")

    def _get_sort_key(self, row: PortRow) -> Tuple[int, Any]:
        """Get sort key for a row."""
        if self._sort_column == "port":
            return row.sort_key_port

        val = getattr(row, self._sort_column, "")
        if isinstance(val, str) and val.isdigit():
            return 0, int(val)
        return 1, str(val).lower()

    def _sort(self, col: str) -> None:
        """Handle column header click for sorting."""
        prev = self._sort_column
        if prev == col:
            self._sort_reverse = not self._sort_reverse
        else:
            if prev:
                self.tree.heading(prev, text=f"{self._COLUMN_HEADERS[prev]} ↕")
            self._sort_column = col
            self._sort_reverse = False

        arrow = " ↓" if self._sort_reverse else " ↑"
        self.tree.heading(col, text=f"{self._COLUMN_HEADERS[col]}{arrow}")
        self._do_apply_filter()

    def _on_click_pre(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Record which row is selected before Treeview processes the click."""
        iid = self.tree.identify_row(event.y)
        self._pre_click_iid = (
            iid if iid and self.tree.selection() == (iid,) else ""
        )

    def _on_click_toggle(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Deselect the current row when the user clicks it a second time."""
        iid = self.tree.identify_row(event.y)
        if iid and not iid.startswith("grp:") and iid == self._pre_click_iid:
            self.tree.selection_remove(iid)
            self._selected_key = None
            self._info_var.set("-- no process selected --")

    def _on_select(self, _event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        """Handle treeview selection change."""
        sel = self.tree.selection()
        if not sel:
            self._info_var.set("-- no process selected --")
            self._selected_key = None
            return

        try:
            vals = self.tree.item(sel[0], "values")
            pid, name, proto, addr, port, state = vals
            self._selected_key = (pid, name, proto, port)
            if sel[0].startswith("grp:"):
                if pid and pid != "\u2014":
                    self._info_var.set(
                        f"❯  GROUP PID: {pid}   NAME: {name}   [kill entire process]"
                    )
                else:
                    self._info_var.set("-- no process selected --")
                    self._selected_key = None
            else:
                self._info_var.set(
                    f"❯  PID: {pid}   NAME: {name}   {proto}  {addr}:{port}   [{state}]"
                )
        except (ValueError, tk.TclError):
            self._info_var.set("-- error reading selection --")

    def _kill(self, sig: signal.Signals) -> None:
        """Send signal to selected process, escalating to sudo if needed."""
        # Ensure we're on the main thread
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda: self._kill(sig)) # type: ignore
            return

        if not self.winfo_exists():
            return

        sel = self.tree.selection()
        if not sel:
            self._flash_status("SELECT A PROCESS FIRST")
            return

        is_group = sel[0].startswith("grp:")

        try:
            vals = self.tree.item(sel[0], "values")
            pid, name, _proto, _addr, port, _state = vals
        except (ValueError, tk.TclError):
            self._flash_status("ERROR READING SELECTION")
            return

        if not pid or pid == "\u2014":
            messagebox.showwarning(
                "porkill", "No PID — kernel entry, cannot kill."
            )
            return

        sig_label = "SIGKILL -9 (force)" if sig == signal.SIGKILL else "SIGTERM (graceful)"
        if is_group:
            msg = (
                f"Send  {sig_label}  to entire process group:\n\n"
                f"   Process : {name}\n"
                f"   PID     : {pid}\n\n"
                "This will kill the parent and all its ports.\nConfirm?"
            )
        else:
            msg = (
                f"Send  {sig_label}  to:\n\n"
                f"   Process : {name}\n"
                f"   PID     : {pid}\n"
                f"   Port    : {port}\n\n"
                "Confirm?"
            )

        if not messagebox.askyesno("porkill // confirm kill", msg, icon="warning"):
            return

        ok, err = send_signal_to_pid(pid, sig)
        if ok:
            self._flash_status(f"KILLED PID {pid} ({name}) ✓")
            self.after(900, self._schedule_refresh) # type: ignore
        else:
            self._flash_status(f"FAILED: {err}")
            messagebox.showerror(
                "porkill // kill failed",
                f"Could not kill PID {pid}:\n{err}\n\nTry running with sudo.",
            )

    def _flash_status(self, msg: str) -> None:
        """Flash a status message temporarily."""
        self._status_var.set(msg)
        ts = time.strftime("%H:%M:%S")
        self.after(Config.FLASH_DURATION_MS, self._status_var.set, f"UPDATED {ts}")

    def _toggle_auto(self) -> None:
        """Toggle auto-refresh on/off."""
        if self._auto.get():
            self._schedule_refresh()
        else:
            self._cancel_refresh_job()

    def destroy(self) -> None:
        """Clean up before destroying the window."""
        self._shutdown_event.set()
        self._cancel_pending_jobs()
        super().destroy()


# ============================================================================
# Main Entry Point
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Process & Port Monitor / Killer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Keyboard Shortcuts:
  Ctrl+R / F5    Refresh
  Delete         Send SIGTERM to selected process
  Ctrl+K         Send SIGKILL to selected process
  Ctrl+F         Focus filter input
  Escape         Clear selection
  Ctrl+Q         Quit
        """
    )

    parser.add_argument(
        "--interval", "-i",
        type=int, default=2,
        help="Auto-refresh interval in seconds (default: 5, min: 2, max: 120)"
    )
    parser.add_argument(
        "--max-rows", "-m",
        type=int, default=10_000,
        help="Maximum rows to display (default: 10000)"
    )
    parser.add_argument(
        "--no-auto-refresh", "-n",
        action="store_true",
        help="Disable auto-refresh on startup"
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="ERROR",
        help="Logging level (default: INFO)"
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    # Check for root privileges and relaunch if necessary
    if os.geteuid() != 0:
        # Check if we are in a graphical environment
        has_display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        launcher = "pkexec" if has_display else "sudo"

        logger.info(f"Restarting with root privileges using {launcher}...")

        try:
            # Get absolute path of the current script
            script_path = os.path.abspath(sys.argv[0])

            # Reconstruct the command line using the absolute path
            cmd = [launcher, sys.executable, script_path] + sys.argv[1:]
            os.execvp(launcher, cmd)
        except Exception as e:
            logger.error(f"Failed to elevate privileges: {e}")
            # Fallback: continue as normal user, but warn
            print("\n" + "!" * 60)
            print("WARNING: RUNNING WITHOUT ROOT PRIVILEGES")
            print("Process names and termination capabilities will be restricted.")
            print("!" * 60 + "\n")

    args = parse_arguments()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Validate arguments
    args.interval = max(2, min(120, args.interval))
    args.max_rows = max(100, args.max_rows)

    # Create application
    app = Porkill(args)

    # Set up signal handler
    def handle_sigint(_sig_num: int, _frame: Any) -> None:
        """Handle SIGINT by scheduling quit on main thread."""
        try:
            if app.winfo_exists():
                app.after(0, app.quit_app)# type: ignore
        except tk.TclError:
            pass

    signal.signal(signal.SIGINT, handle_sigint)

    # Run main loop
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down...")
        try:
            if app.winfo_exists():
                app.destroy()
        except tk.TclError:
            pass  # App already destroyed, nothing to do

    return 0


if __name__ == "__main__":
    sys.exit(main())
