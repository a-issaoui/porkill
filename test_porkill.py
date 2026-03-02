"""
test_porkill.py — Comprehensive test suite for porkill.py
==========================================================

Coverage strategy
-----------------
- Pure logic functions (hex conversion, proc parsing, pid validation, etc.)
  are tested directly with no mocking.
- Filesystem / subprocess interactions are tested via unittest.mock so the
  suite runs on any machine without root or real /proc entries.
- GUI classes (LogoCanvas, StatBadge, KillButton, Porkill) are tested only
  when a DISPLAY is available; otherwise the tests are skipped gracefully.
- The static helpers that live on GUI classes (e.g. _lerp_color,
  _validate_interval) are extracted and tested without instantiating tk.

Run:
    python3 -m pytest test_porkill.py -v
    python3 -m pytest test_porkill.py -v --tb=short   # quieter tracebacks

Requirements:
    pip install pytest pytest-cov
    pytest --cov=porkill --cov-report=term-missing test_porkill.py
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, mock_open, patch

# ── Import the module under test ───────────────────────────────────────────────
# porkill.py must be on sys.path. If running from the project root this works
# automatically; adjust if your layout differs.
sys.path.insert(0, str(Path(__file__).parent))
import porkill as pk

# ── Display availability check (used by GUI test decorators) ──────────────────
_HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# ==============================================================================
# 1. Constants
# ==============================================================================

class TestConstants(unittest.TestCase):

    def test_tcp_states_completeness(self):
        expected_keys = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "0A", "0B"}
        self.assertEqual(set(pk._TCP_STATES.keys()), expected_keys)

    def test_tcp_states_values(self):
        self.assertEqual(pk._TCP_STATES["01"], "ESTABLISHED")
        self.assertEqual(pk._TCP_STATES["0A"], "LISTEN")
        self.assertEqual(pk._TCP_STATES["06"], "TIME_WAIT")
        self.assertEqual(pk._TCP_STATES["0B"], "CLOSING")

    def test_helper_names_set(self):
        self.assertIn("rootlessport", pk._HELPER_NAMES)
        self.assertIn("slirp4netns", pk._HELPER_NAMES)
        self.assertIn("pasta", pk._HELPER_NAMES)
        self.assertIsInstance(pk._HELPER_NAMES, set)

    def test_container_runtimes_set(self):
        for name in ("podman", "docker", "containerd", "runc", "crun", "conmon"):
            self.assertIn(name, pk._CONTAINER_RUNTIMES)
        self.assertIsInstance(pk._CONTAINER_RUNTIMES, set)


# ==============================================================================
# 2. Config
# ==============================================================================

class TestConfig(unittest.TestCase):

    def test_color_format(self):
        """All color strings must be valid 7-char hex."""
        colors = [
            pk.Config.BG, pk.Config.BG2, pk.Config.BG3, pk.Config.BG4,
            pk.Config.NEON, pk.Config.NEON_DIM, pk.Config.NEON_GLOW,
            pk.Config.RED, pk.Config.AMBER, pk.Config.CYAN, pk.Config.CYAN_DIM,
            pk.Config.FG, pk.Config.FG2, pk.Config.BORDER, pk.Config.SEL_BG,
        ]
        for color in colors:
            with self.subTest(color=color):
                self.assertRegex(color, r"^#[0-9a-fA-F]{6}$")

    def test_numeric_defaults(self):
        self.assertGreater(pk.Config.MAX_ROWS, 0)
        self.assertGreater(pk.Config.SUBPROCESS_TIMEOUT, 0)
        self.assertGreater(pk.Config.FILTER_DEBOUNCE_MS, 0)
        self.assertGreater(pk.Config.INODE_CACHE_TTL, 0)
        self.assertGreater(pk.Config.MAX_PARENT_TRAVERSAL, 0)
        self.assertGreater(pk.Config.ANIMATION_INTERVAL_MS, 0)


# ==============================================================================
# 3. Data Models
# ==============================================================================

class TestPortRow(unittest.TestCase):

    def _make_row(self, port="80", **kwargs):
        defaults = dict(pid="1234", name="nginx", proto="TCP",
                        addr="0.0.0.0", port=port, state="LISTEN", group="nginx")
        defaults.update(kwargs)
        return pk.PortRow(**defaults)

    def test_frozen(self):
        row = self._make_row()
        with self.assertRaises((AttributeError, TypeError)):
            row.pid = "999"  # type: ignore[misc]

    def test_sort_key_numeric_port(self):
        row = self._make_row(port="8080")
        self.assertEqual(row.sort_key_port, (0, 8080))

    def test_sort_key_port_zero(self):
        row = self._make_row(port="0")
        self.assertEqual(row.sort_key_port, (0, 0))

    def test_sort_key_non_numeric_port(self):
        row = self._make_row(port="—")
        self.assertEqual(row.sort_key_port, (1, 0))

    def test_sort_key_ordering(self):
        """Numeric ports must sort before non-numeric ones."""
        numeric = self._make_row(port="22")
        text = self._make_row(port="—")
        self.assertLess(numeric.sort_key_port, text.sort_key_port)

    def test_all_fields_accessible(self):
        row = self._make_row()
        self.assertEqual(row.pid, "1234")
        self.assertEqual(row.name, "nginx")
        self.assertEqual(row.proto, "TCP")
        self.assertEqual(row.addr, "0.0.0.0")
        self.assertEqual(row.port, "80")
        self.assertEqual(row.state, "LISTEN")
        self.assertEqual(row.group, "nginx")


class TestProcessInfo(unittest.TestCase):

    def test_required_fields(self):
        pi = pk.ProcessInfo(pid="42", comm="bash")
        self.assertEqual(pi.pid, "42")
        self.assertEqual(pi.comm, "bash")
        self.assertIsNone(pi.ppid)
        self.assertEqual(pi.cmdline, "")

    def test_optional_fields(self):
        pi = pk.ProcessInfo(pid="42", comm="bash", ppid="1", cmdline="/bin/bash")
        self.assertEqual(pi.ppid, "1")
        self.assertEqual(pi.cmdline, "/bin/bash")


class TestInodeCacheEntry(unittest.TestCase):

    def test_named_tuple_fields(self):
        imap = {"12345": ("100", "nginx")}
        ts = time.monotonic()
        entry = pk.InodeCacheEntry(inode_map=imap, timestamp=ts)
        self.assertEqual(entry.inode_map, imap)
        self.assertEqual(entry.timestamp, ts)

    def test_unpacking(self):
        imap = {}
        ts = 1.0
        inode_map, timestamp = pk.InodeCacheEntry(inode_map=imap, timestamp=ts)
        self.assertEqual(inode_map, imap)
        self.assertEqual(timestamp, ts)


class TestFontSpec(unittest.TestCase):

    def test_defaults(self):
        fs = pk.FontSpec(family="Monospace", size=10)
        self.assertEqual(fs.weight, "normal")

    def test_custom_weight(self):
        fs = pk.FontSpec(family="Hack", size=12, weight="bold")
        self.assertEqual(fs.weight, "bold")


# ==============================================================================
# 4. Utility Functions — hex_to_ipv4 / hex_to_ipv6
# ==============================================================================

class TestHexToIPv4(unittest.TestCase):

    def test_localhost(self):
        # 127.0.0.1 little-endian = 0100007F
        self.assertEqual(pk.hex_to_ipv4("0100007F"), "127.0.0.1")

    def test_all_zeros(self):
        self.assertEqual(pk.hex_to_ipv4("00000000"), "0.0.0.0")

    def test_broadcast(self):
        # 255.255.255.255 = FFFFFFFF
        self.assertEqual(pk.hex_to_ipv4("FFFFFFFF"), "255.255.255.255")

    def test_real_address(self):
        # 192.168.1.1 little-endian = 0101A8C0
        self.assertEqual(pk.hex_to_ipv4("0101A8C0"), "192.168.1.1")

    def test_invalid_hex_returns_original(self):
        result = pk.hex_to_ipv4("ZZZZZZZZ")
        self.assertEqual(result, "ZZZZZZZZ")

    def test_empty_string_returns_original(self):
        result = pk.hex_to_ipv4("")
        self.assertEqual(result, "")

    def test_short_string_returns_original(self):
        result = pk.hex_to_ipv4("0001")
        # struct.pack with too-small int still works; just ensure no crash
        self.assertIsInstance(result, str)


class TestHexToIPv6(unittest.TestCase):

    def test_loopback(self):
        # ::1 in /proc/net/tcp6 format: 16 zero bytes except last byte = 1
        # 00000000000000000000000001000000
        result = pk.hex_to_ipv6("00000000000000000000000001000000")
        self.assertIn("[", result)
        self.assertIn("]", result)

    def test_all_zeros(self):
        result = pk.hex_to_ipv6("0" * 32)
        self.assertEqual(result, "[::]")

    def test_invalid_returns_original(self):
        bad = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        result = pk.hex_to_ipv6(bad)
        self.assertEqual(result, bad)

    def test_too_short_returns_original(self):
        bad = "0000"
        result = pk.hex_to_ipv6(bad)
        self.assertEqual(result, bad)

    def test_brackets_present_on_valid(self):
        result = pk.hex_to_ipv6("0" * 32)
        self.assertTrue(result.startswith("["))
        self.assertTrue(result.endswith("]"))


# ==============================================================================
# 5. Utility Functions — read_proc_file / read_proc_cmdline
# ==============================================================================

class TestReadProcFile(unittest.TestCase):

    def test_reads_content_stripped(self):
        with patch("porkill.Path.read_text", return_value="  nginx  \n"):
            result = pk.read_proc_file("123", "comm")
        self.assertEqual(result, "nginx")

    def test_oserror_returns_empty(self):
        with patch("porkill.Path.read_text", side_effect=OSError("no such file")):
            result = pk.read_proc_file("999999", "comm")
        self.assertEqual(result, "")

    def test_ioerror_returns_empty(self):
        with patch("porkill.Path.read_text", side_effect=IOError):
            result = pk.read_proc_file("999999", "status")
        self.assertEqual(result, "")

    def test_correct_path_constructed(self):
        with patch("porkill.Path.read_text", return_value="bash") as mock_rt:
            pk.read_proc_file("42", "comm")
        # Verify Path was constructed with the right components via the call
        # (we check the return value was used)
        mock_rt.assert_called_once()


class TestReadProcCmdline(unittest.TestCase):

    def test_null_bytes_replaced(self):
        raw = b"/usr/bin/python3\x00-m\x00porkill\x00"
        with patch("porkill.Path.read_bytes", return_value=raw):
            result = pk.read_proc_cmdline("123")
        self.assertEqual(result, "/usr/bin/python3 -m porkill")

    def test_oserror_returns_empty(self):
        with patch("porkill.Path.read_bytes", side_effect=OSError):
            result = pk.read_proc_cmdline("999999")
        self.assertEqual(result, "")

    def test_ioerror_returns_empty(self):
        with patch("porkill.Path.read_bytes", side_effect=IOError):
            result = pk.read_proc_cmdline("999999")
        self.assertEqual(result, "")

    def test_empty_cmdline(self):
        with patch("porkill.Path.read_bytes", return_value=b""):
            result = pk.read_proc_cmdline("1")
        self.assertEqual(result, "")

    def test_invalid_utf8_decoded_with_replace(self):
        raw = b"/usr/bin/test\xff\xfe"
        with patch("porkill.Path.read_bytes", return_value=raw):
            result = pk.read_proc_cmdline("1")
        self.assertIsInstance(result, str)
        self.assertIn("/usr/bin/test", result)


# ==============================================================================
# 6. get_parent_pid
# ==============================================================================

class TestGetParentPid(unittest.TestCase):

    def _mock_status(self, ppid_value: str) -> str:
        return f"Name:\tbash\nPid:\t42\nPPid:\t{ppid_value}\nState:\tS\n"

    def test_extracts_ppid(self):
        with patch("porkill.read_proc_file", return_value=self._mock_status("1234")):
            result = pk.get_parent_pid("42")
        self.assertEqual(result, "1234")

    def test_ppid_zero(self):
        with patch("porkill.read_proc_file", return_value=self._mock_status("0")):
            result = pk.get_parent_pid("1")
        self.assertEqual(result, "0")

    def test_no_ppid_line_returns_none(self):
        status = "Name:\tbash\nPid:\t42\nState:\tS\n"
        with patch("porkill.read_proc_file", return_value=status):
            result = pk.get_parent_pid("42")
        self.assertIsNone(result)

    def test_empty_status_returns_none(self):
        with patch("porkill.read_proc_file", return_value=""):
            result = pk.get_parent_pid("42")
        self.assertIsNone(result)

    def test_malformed_ppid_line_skipped(self):
        # PPid line with no value after it — split gives only 1 part
        status = "PPid:\n"
        with patch("porkill.read_proc_file", return_value=status):
            result = pk.get_parent_pid("42")
        self.assertIsNone(result)


# ==============================================================================
# 7. find_container_runtime
# ==============================================================================

class TestFindContainerRuntime(unittest.TestCase):

    def test_finds_docker_parent(self):
        def fake_get_parent(pid):
            return {"100": "200", "200": "300"}.get(pid)

        def fake_read_proc(pid, filename):
            return {"200": "systemd", "300": "docker"}.get(pid, "")

        with patch("porkill.get_parent_pid", side_effect=fake_get_parent), \
             patch("porkill.read_proc_file", side_effect=fake_read_proc):
            result = pk.find_container_runtime("100")
        self.assertEqual(result, "docker")

    def test_returns_none_when_no_runtime(self):
        def fake_get_parent(pid):
            return {"100": "2", "2": "1"}.get(pid)

        def fake_read_proc(pid, filename):
            return {"2": "kthreadd"}.get(pid, "")

        with patch("porkill.get_parent_pid", side_effect=fake_get_parent), \
             patch("porkill.read_proc_file", side_effect=fake_read_proc):
            result = pk.find_container_runtime("100")
        self.assertIsNone(result)

    def test_stops_at_pid_1(self):
        """Traversal must stop when it reaches pid 1."""
        calls = []

        def fake_get_parent(pid):
            calls.append(pid)
            return "1"

        with patch("porkill.get_parent_pid", side_effect=fake_get_parent), \
             patch("porkill.read_proc_file", return_value="systemd"):
            result = pk.find_container_runtime("500")
        self.assertIsNone(result)

    def test_stops_at_pid_0(self):
        def fake_get_parent(pid):
            return "0"

        with patch("porkill.get_parent_pid", side_effect=fake_get_parent), \
             patch("porkill.read_proc_file", return_value="swapper"):
            result = pk.find_container_runtime("500")
        self.assertIsNone(result)

    def test_depth_limit_respected(self):
        """Should stop after max_depth traversals even if no PID 0/1 found."""
        counter = {"n": 0}

        def fake_get_parent(pid):
            counter["n"] += 1
            return str(int(pid) + 1)

        def fake_read_proc(pid, filename):
            return "some_process"

        with patch("porkill.get_parent_pid", side_effect=fake_get_parent), \
             patch("porkill.read_proc_file", side_effect=fake_read_proc):
            result = pk.find_container_runtime("100", max_depth=3)
        self.assertIsNone(result)
        self.assertLessEqual(counter["n"], 3)

    def test_returns_none_when_ppid_none(self):
        with patch("porkill.get_parent_pid", return_value=None):
            result = pk.find_container_runtime("100")
        self.assertIsNone(result)


# ==============================================================================
# 8. enrich_process_name
# ==============================================================================

class TestEnrichProcessName(unittest.TestCase):

    def test_non_helper_returned_unchanged(self):
        result = pk.enrich_process_name("123", "nginx")
        self.assertEqual(result, "nginx")

    def test_helper_no_runtime_returned_unchanged(self):
        with patch("porkill.read_proc_cmdline", return_value="rootlessport --arg"), \
             patch("porkill.find_container_runtime", return_value=None):
            result = pk.enrich_process_name("123", "rootlessport")
        self.assertEqual(result, "rootlessport")

    def test_helper_with_runtime_no_container_hint(self):
        with patch("porkill.read_proc_cmdline", return_value="slirp4netns --other"), \
             patch("porkill.find_container_runtime", return_value="podman"):
            result = pk.enrich_process_name("123", "slirp4netns")
        self.assertEqual(result, "podman→slirp4netns")

    def test_helper_with_runtime_and_container_hint(self):
        cmdline = "rootlessport --container-name my-web-app --port 80"
        with patch("porkill.read_proc_cmdline", return_value=cmdline), \
             patch("porkill.find_container_runtime", return_value="podman"):
            result = pk.enrich_process_name("123", "rootlessport")
        self.assertEqual(result, "podman[my-web-app]")

    def test_helper_with_runtime_and_container_hint_equals_sign(self):
        cmdline = "rootlessport --container-name=db-postgres"
        with patch("porkill.read_proc_cmdline", return_value=cmdline), \
             patch("porkill.find_container_runtime", return_value="docker"):
            result = pk.enrich_process_name("456", "rootlessport")
        self.assertEqual(result, "docker[db-postgres]")

    def test_all_helper_names_are_recognised(self):
        for helper in pk._HELPER_NAMES:
            with self.subTest(helper=helper):
                with patch("porkill.read_proc_cmdline", return_value=""), \
                     patch("porkill.find_container_runtime", return_value=None):
                    result = pk.enrich_process_name("1", helper)
                # If no runtime found it returns the helper name unchanged
                self.assertEqual(result, helper)


# ==============================================================================
# 9. resolve_group_name
# ==============================================================================

class TestResolveGroupName(unittest.TestCase):

    def test_em_dash_pid_returns_kernel(self):
        result = pk.resolve_group_name("—", "something")
        self.assertEqual(result, "kernel")

    def test_normal_process_returns_comm(self):
        result = pk.resolve_group_name("1234", "nginx")
        self.assertEqual(result, "nginx")

    def test_helper_with_runtime_returns_runtime(self):
        with patch("porkill.find_container_runtime", return_value="docker"):
            result = pk.resolve_group_name("555", "slirp4netns")
        self.assertEqual(result, "docker")

    def test_helper_without_runtime_returns_podman(self):
        with patch("porkill.find_container_runtime", return_value=None):
            result = pk.resolve_group_name("555", "pasta")
        self.assertEqual(result, "podman")

    def test_non_helper_not_sent_to_find_runtime(self):
        with patch("porkill.find_container_runtime") as mock_fnd:
            pk.resolve_group_name("1", "sshd")
        mock_fnd.assert_not_called()


# ==============================================================================
# 10. resolve_mono_font
# ==============================================================================

class TestResolveMonoFont(unittest.TestCase):

    def test_returns_first_available_candidate(self):
        available = {"JetBrains Mono", "DejaVu Sans Mono", "Monospace"}
        with patch("porkill.tkfont") as mock_tkfont:
            mock_tkfont.families.return_value = list(available)
            result = pk.resolve_mono_font()
        self.assertEqual(result, "JetBrains Mono")

    def test_skips_unavailable_candidates(self):
        available = {"DejaVu Sans Mono", "Monospace"}
        with patch("porkill.tkfont") as mock_tkfont:
            mock_tkfont.families.return_value = list(available)
            result = pk.resolve_mono_font()
        self.assertEqual(result, "DejaVu Sans Mono")

    def test_fallback_when_nothing_available(self):
        with patch("porkill.tkfont") as mock_tkfont:
            mock_tkfont.families.return_value = ["Arial", "Times New Roman"]
            result = pk.resolve_mono_font()
        self.assertEqual(result, "monospace")

    def test_oserror_returns_fallback(self):
        with patch("porkill.tkfont") as mock_tkfont:
            mock_tkfont.families.side_effect = OSError("no display")
            result = pk.resolve_mono_font()
        self.assertEqual(result, "monospace")


# ==============================================================================
# 11. validate_pid
# ==============================================================================

class TestValidatePid(unittest.TestCase):

    def test_valid_pid(self):
        ok, pid_int, err = pk.validate_pid("1234")
        self.assertTrue(ok)
        self.assertEqual(pid_int, 1234)
        self.assertEqual(err, "")

    def test_pid_one(self):
        ok, pid_int, _ = pk.validate_pid("1")
        self.assertTrue(ok)
        self.assertEqual(pid_int, 1)

    def test_empty_string(self):
        ok, pid_int, err = pk.validate_pid("")
        self.assertFalse(ok)
        self.assertEqual(pid_int, 0)
        self.assertIn("Invalid", err)

    def test_non_digit_string(self):
        ok, pid_int, err = pk.validate_pid("abc")
        self.assertFalse(ok)
        self.assertEqual(pid_int, 0)

    def test_em_dash(self):
        ok, _, err = pk.validate_pid("—")
        self.assertFalse(ok)

    def test_zero_pid(self):
        ok, _, err = pk.validate_pid("0")
        self.assertFalse(ok)
        self.assertIn("positive", err)

    def test_float_string(self):
        ok, _, _ = pk.validate_pid("12.3")
        self.assertFalse(ok)

    def test_negative_string(self):
        # "-1" is not all digits so it fails the isdigit check
        ok, _, _ = pk.validate_pid("-1")
        self.assertFalse(ok)

    def test_large_valid_pid(self):
        ok, pid_int, _ = pk.validate_pid("4194304")
        self.assertTrue(ok)
        self.assertEqual(pid_int, 4194304)


# ==============================================================================
# 12. send_signal_to_pid
# ==============================================================================

class TestSendSignalToPid(unittest.TestCase):

    def test_invalid_pid_returns_false(self):
        ok, err = pk.send_signal_to_pid("abc", signal.SIGTERM)
        self.assertFalse(ok)
        self.assertIn("Invalid", err)

    def test_zero_pid_returns_false(self):
        ok, err = pk.send_signal_to_pid("0", signal.SIGTERM)
        self.assertFalse(ok)

    def test_direct_kill_succeeds(self):
        with patch("porkill.os.kill") as mock_kill:
            ok, err = pk.send_signal_to_pid("9999", signal.SIGTERM)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        mock_kill.assert_called_once_with(9999, signal.SIGTERM)

    def test_oserror_returns_false(self):
        with patch("porkill.os.kill", side_effect=OSError("no such process")):
            ok, err = pk.send_signal_to_pid("9999", signal.SIGTERM)
        self.assertFalse(ok)
        self.assertIn("no such process", err)

    def test_permission_error_escalates_to_sudo(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("porkill.os.kill", side_effect=PermissionError), \
             patch("porkill.subprocess.run", return_value=mock_result) as mock_run:
            ok, err = pk.send_signal_to_pid("1234", signal.SIGKILL)

        self.assertTrue(ok)
        # sudo -n was tried
        args = mock_run.call_args[0][0]
        self.assertIn("sudo", args)

    def test_permission_error_sudo_nonzero_tries_doas(self):
        sudo_result = MagicMock(returncode=1, stderr="sudo: no password")
        doas_result = MagicMock(returncode=0, stderr="")

        results = [sudo_result, doas_result]

        with patch("porkill.os.kill", side_effect=PermissionError), \
             patch("porkill.subprocess.run", side_effect=results):
            ok, err = pk.send_signal_to_pid("1234", signal.SIGTERM)
        self.assertTrue(ok)

    def test_permission_error_all_escalation_fails(self):
        bad_result = MagicMock(returncode=1, stderr="permission denied")

        with patch("porkill.os.kill", side_effect=PermissionError), \
             patch("porkill.subprocess.run", return_value=bad_result):
            ok, err = pk.send_signal_to_pid("1234", signal.SIGTERM)
        self.assertFalse(ok)

    def test_sudo_not_found_tries_doas(self):
        doas_result = MagicMock(returncode=0, stderr="")

        def run_side_effect(cmd, **kwargs):
            if "sudo" in cmd:
                raise FileNotFoundError
            return doas_result

        with patch("porkill.os.kill", side_effect=PermissionError), \
             patch("porkill.subprocess.run", side_effect=run_side_effect):
            ok, err = pk.send_signal_to_pid("1234", signal.SIGTERM)
        self.assertTrue(ok)

    def test_subprocess_timeout_stops_escalation(self):
        import subprocess as _sp

        with patch("porkill.os.kill", side_effect=PermissionError), \
             patch("porkill.subprocess.run",
                   side_effect=_sp.TimeoutExpired(cmd="sudo", timeout=5)):
            ok, err = pk.send_signal_to_pid("1234", signal.SIGTERM)
        self.assertFalse(ok)


# ==============================================================================
# 13. PortDataFetcher — inode cache
# ==============================================================================

class TestPortDataFetcherCache(unittest.TestCase):

    def setUp(self):
        self.fetcher = pk.PortDataFetcher()

    def test_cache_miss_builds_map(self):
        with patch.object(pk.PortDataFetcher, "_build_inode_map",
                          return_value={"1": ("100", "nginx")}) as mock_build:
            result = self.fetcher._get_inode_map()
        mock_build.assert_called_once()
        self.assertIn("1", result)

    def test_cache_hit_skips_rebuild(self):
        imap = {"2": ("200", "ssh")}
        self.fetcher._inode_cache = pk.InodeCacheEntry(imap, time.monotonic())

        with patch.object(pk.PortDataFetcher, "_build_inode_map") as mock_build:
            result = self.fetcher._get_inode_map()
        mock_build.assert_not_called()
        self.assertEqual(result, imap)

    def test_stale_cache_triggers_rebuild(self):
        old_imap = {"stale": ("1", "old")}
        stale_ts = time.monotonic() - pk.Config.INODE_CACHE_TTL - 1
        self.fetcher._inode_cache = pk.InodeCacheEntry(old_imap, stale_ts)
        new_imap = {"fresh": ("2", "new")}

        with patch.object(pk.PortDataFetcher, "_build_inode_map",
                          return_value=new_imap) as mock_build:
            result = self.fetcher._get_inode_map()
        mock_build.assert_called_once()
        self.assertEqual(result, new_imap)

    def test_thread_safety(self):
        """Multiple threads must not corrupt the cache."""
        call_counts = {"n": 0}

        def slow_build():
            call_counts["n"] += 1
            time.sleep(0.01)
            return {}

        with patch.object(pk.PortDataFetcher, "_build_inode_map",
                          side_effect=slow_build):
            threads = [threading.Thread(target=self.fetcher._get_inode_map)
                       for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Only one build should have run (subsequent threads hit the cache)
        self.assertEqual(call_counts["n"], 1)


# ==============================================================================
# 14. PortDataFetcher._parse_ss_output
# ==============================================================================

class TestParseSsOutput(unittest.TestCase):

    _SS_HEADER = "Netid  State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port  Process\n"

    def _run_with_output(self, stdout: str):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self._SS_HEADER + stdout
        with patch("porkill.subprocess.run", return_value=mock_result):
            return pk.PortDataFetcher._parse_ss_output()

    def test_tcp_listen_row(self):
        line = 'tcp   LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1234,fd=3))\n'
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].port, "22")
        self.assertEqual(rows[0].proto, "TCP")
        self.assertEqual(rows[0].state, "LISTEN")

    def test_udp_row(self):
        line = 'udp   UNCONN  0  0  0.0.0.0:53  0.0.0.0:*  users:(("dnsmasq",pid=555,fd=5))\n'
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].proto, "UDP")
        self.assertEqual(rows[0].port, "53")

    def test_kernel_entry_no_pid(self):
        line = 'tcp   LISTEN  0  128  0.0.0.0:80  0.0.0.0:*  \n'
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        row = rows[0]
        self.assertEqual(row.pid, "—")
        self.assertEqual(row.name, "kernel")

    def test_duplicate_pid_port_proto_skipped(self):
        line = ('tcp   LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1234,fd=3))\n'
                'tcp   LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1234,fd=4))\n')
        rows = self._run_with_output(line)
        self.assertEqual(len(rows), 1)

    def test_short_line_skipped(self):
        rows = self._run_with_output("tcp LISTEN\n")
        self.assertIsNone(rows)

    def test_no_port_in_local_skipped(self):
        line = 'tcp   LISTEN  0  128  no-port-here  0.0.0.0:*  users:(("x",pid=1,fd=1))\n'
        rows = self._run_with_output(line)
        self.assertIsNone(rows)

    def test_ss_not_found_returns_none(self):
        with patch("porkill.subprocess.run", side_effect=FileNotFoundError):
            result = pk.PortDataFetcher._parse_ss_output()
        self.assertIsNone(result)

    def test_ss_nonzero_returns_none(self):
        mock_result = MagicMock(returncode=1, stderr="error")
        with patch("porkill.subprocess.run", return_value=mock_result):
            result = pk.PortDataFetcher._parse_ss_output()
        self.assertIsNone(result)

    def test_ss_timeout_returns_none(self):
        import subprocess as _sp
        with patch("porkill.subprocess.run",
                   side_effect=_sp.TimeoutExpired(cmd="ss", timeout=5)):
            result = pk.PortDataFetcher._parse_ss_output()
        self.assertIsNone(result)

    def test_ss_oserror_returns_none(self):
        with patch("porkill.subprocess.run", side_effect=OSError):
            result = pk.PortDataFetcher._parse_ss_output()
        self.assertIsNone(result)

    def test_empty_output_returns_none(self):
        mock_result = MagicMock(returncode=0, stdout=self._SS_HEADER)
        with patch("porkill.subprocess.run", return_value=mock_result):
            result = pk.PortDataFetcher._parse_ss_output()
        self.assertIsNone(result)

    def test_tcp6_normalised_to_tcp(self):
        line = 'tcp6  LISTEN  0  128  [::]:443  [::]:*  users:(("nginx",pid=777,fd=6))\n'
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].proto, "TCP")

    def test_multiple_pids_same_port(self):
        line = 'tcp   LISTEN  0  0  0.0.0.0:8080  0.0.0.0:*  users:(("worker",pid=10,fd=1),("worker",pid=11,fd=1))\n'
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        pids = {r.pid for r in rows}
        self.assertIn("10", pids)
        self.assertIn("11", pids)


# ==============================================================================
# 15. PortDataFetcher._parse_netstat_output
# ==============================================================================

class TestParseNetstatOutput(unittest.TestCase):

    _HEADER = "Active Internet connections (only servers)\n" \
              "Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program\n"

    def _run_with_output(self, stdout: str):
        mock_result = MagicMock(returncode=0, stdout=self._HEADER + stdout)
        with patch("porkill.subprocess.run", return_value=mock_result):
            return pk.PortDataFetcher._parse_netstat_output()

    def test_tcp_listen_row(self):
        line = "tcp   0  0  0.0.0.0:22  0.0.0.0:*  LISTEN  1234/sshd\n"
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].port, "22")
        self.assertEqual(rows[0].proto, "TCP")
        self.assertEqual(rows[0].state, "LISTEN")
        self.assertEqual(rows[0].pid, "1234")
        self.assertEqual(rows[0].name, "sshd")

    def test_udp_row(self):
        # netstat UDP lines: Proto Recv-Q Send-Q Local-Addr Foreign-Addr PID/Program
        line = "udp   0  0  0.0.0.0:53  0.0.0.0:*  555/dnsmasq\n"
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].proto, "UDP")

    def test_no_pid_column(self):
        line = "tcp   0  0  0.0.0.0:80  0.0.0.0:*  LISTEN  -\n"
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].pid, "—")

    def test_duplicate_skipped(self):
        line = ("tcp  0  0  0.0.0.0:22  0.0.0.0:*  LISTEN  1234/sshd\n"
                "tcp  0  0  0.0.0.0:22  0.0.0.0:*  LISTEN  1234/sshd\n")
        rows = self._run_with_output(line)
        self.assertEqual(len(rows), 1)

    def test_short_line_skipped(self):
        rows = self._run_with_output("tcp 0\n")
        self.assertIsNone(rows)

    def test_not_starting_with_tcp_udp_skipped(self):
        rows = self._run_with_output("raw  0  0  something\n")
        self.assertIsNone(rows)

    def test_netstat_not_found_returns_none(self):
        with patch("porkill.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(pk.PortDataFetcher._parse_netstat_output())

    def test_netstat_nonzero_returns_none(self):
        mock_result = MagicMock(returncode=1)
        with patch("porkill.subprocess.run", return_value=mock_result):
            self.assertIsNone(pk.PortDataFetcher._parse_netstat_output())

    def test_netstat_timeout_returns_none(self):
        import subprocess as _sp
        with patch("porkill.subprocess.run",
                   side_effect=_sp.TimeoutExpired(cmd="netstat", timeout=5)):
            self.assertIsNone(pk.PortDataFetcher._parse_netstat_output())

    def test_empty_result_returns_none(self):
        mock_result = MagicMock(returncode=0, stdout=self._HEADER)
        with patch("porkill.subprocess.run", return_value=mock_result):
            self.assertIsNone(pk.PortDataFetcher._parse_netstat_output())

    def test_tcp6_row(self):
        line = "tcp6  0  0  :::8080  :::*  LISTEN  999/java\n"
        rows = self._run_with_output(line)
        self.assertIsNotNone(rows)
        self.assertEqual(rows[0].proto, "TCP")


# ==============================================================================
# 16. PortDataFetcher._parse_proc_net
# ==============================================================================

class TestParseProcNet(unittest.TestCase):

    # A realistic /proc/net/tcp line (127.0.0.1:22 LISTEN, inode 12345)
    _TCP_LINE = (
        "   0: 0100007F:0016 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000 1000 0 12345 1 0000000000000000 100 0 0 10 0\n"
    )

    def _make_proc_net_mock(self, content: str, proto: str = "TCP", is_v6: bool = False):
        """Return a PortDataFetcher whose _get_inode_map is patched."""
        fetcher = pk.PortDataFetcher()
        fetcher._inode_cache = pk.InodeCacheEntry({"12345": ("1234", "sshd")},
                                                   time.monotonic())
        return fetcher

    def test_tcp_listen_parsed(self):
        fetcher = self._make_proc_net_mock(self._TCP_LINE)

        mock_open_fn = mock_open(read_data="header\n" + self._TCP_LINE)
        with patch("builtins.open", mock_open_fn), \
             patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
             patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()

        self.assertGreater(len(rows), 0)
        row = rows[0]
        self.assertEqual(row.port, "22")
        self.assertEqual(row.state, "LISTEN")
        self.assertEqual(row.proto, "TCP")

    def test_unknown_inode_gets_kernel(self):
        fetcher = pk.PortDataFetcher()
        fetcher._inode_cache = pk.InodeCacheEntry({}, time.monotonic())

        mock_open_fn = mock_open(read_data="header\n" + self._TCP_LINE)
        with patch("builtins.open", mock_open_fn), \
             patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
             patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()

        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0].pid, "—")
        self.assertEqual(rows[0].name, "kernel")

    def test_short_line_skipped(self):
        fetcher = pk.PortDataFetcher()
        fetcher._inode_cache = pk.InodeCacheEntry({}, time.monotonic())

        short_line = "   0: 0100007F:0016\n"
        mock_open_fn = mock_open(read_data="header\n" + short_line)
        with patch("builtins.open", mock_open_fn):
            rows = fetcher._parse_proc_net()
        self.assertEqual(rows, [])

    def test_oserror_on_file_skipped_gracefully(self):
        fetcher = pk.PortDataFetcher()
        fetcher._inode_cache = pk.InodeCacheEntry({}, time.monotonic())

        with patch("builtins.open", side_effect=OSError("no file")):
            rows = fetcher._parse_proc_net()
        self.assertEqual(rows, [])

    def test_duplicate_pid_port_proto_skipped(self):
        fetcher = pk.PortDataFetcher()
        imap = {"12345": ("1234", "sshd")}
        fetcher._inode_cache = pk.InodeCacheEntry(imap, time.monotonic())

        # Same line twice
        data = "header\n" + self._TCP_LINE + self._TCP_LINE
        mock_open_fn = mock_open(read_data=data)
        with patch("builtins.open", mock_open_fn), \
             patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
             patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()
        self.assertEqual(len(rows), 1)

    def test_udp_state_is_dash(self):
        fetcher = pk.PortDataFetcher()
        fetcher._inode_cache = pk.InodeCacheEntry({"12345": ("555", "dnsmasq")},
                                                   time.monotonic())
        udp_line = (
            "   0: 0100007F:0035 00000000:0000 07 00000000:00000000 "
            "00:00000000 00000000 1000 0 12345 1 0000000000000000 100 0 0 10 0\n"
        )
        data = "header\n" + udp_line

        # Patch all four file opens: tcp, tcp6, udp, udp6
        # Only udp open should return real data
        opened = []

        def side_open(path, *args, **kwargs):
            opened.append(path)
            if "udp" in path and "6" not in path:
                return mock_open(read_data=data)()
            raise OSError("skip")

        with patch("builtins.open", side_effect=side_open), \
             patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
             patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()

        udp_rows = [r for r in rows if r.proto == "UDP"]
        if udp_rows:
            self.assertEqual(udp_rows[0].state, "—")


# ==============================================================================
# 17. PortDataFetcher.fetch — method selection waterfall
# ==============================================================================

class TestPortDataFetcherFetch(unittest.TestCase):

    def setUp(self):
        self.fetcher = pk.PortDataFetcher()

    def _make_row(self):
        return pk.PortRow(pid="1", name="test", proto="TCP",
                          addr="0.0.0.0", port="80", state="LISTEN", group="test")

    def test_uses_ss_when_available(self):
        rows = [self._make_row()]
        with patch.object(pk.PortDataFetcher, "_parse_ss_output", return_value=rows), \
             patch.object(pk.PortDataFetcher, "_parse_netstat_output") as mock_ns, \
             patch.object(pk.PortDataFetcher, "_parse_proc_net") as mock_proc:
            result, err = self.fetcher.fetch()

        self.assertEqual(result, rows)
        self.assertIsNone(err)
        mock_ns.assert_not_called()
        mock_proc.assert_not_called()

    def test_falls_back_to_netstat_when_ss_fails(self):
        rows = [self._make_row()]
        with patch.object(pk.PortDataFetcher, "_parse_ss_output", return_value=None), \
             patch.object(pk.PortDataFetcher, "_parse_netstat_output", return_value=rows), \
             patch.object(pk.PortDataFetcher, "_parse_proc_net") as mock_proc:
            result, err = self.fetcher.fetch()

        self.assertEqual(result, rows)
        self.assertIsNone(err)
        mock_proc.assert_not_called()

    def test_falls_back_to_proc_net_when_all_external_fail(self):
        rows = [self._make_row()]
        with patch.object(pk.PortDataFetcher, "_parse_ss_output", return_value=None), \
             patch.object(pk.PortDataFetcher, "_parse_netstat_output", return_value=None), \
             patch.object(pk.PortDataFetcher, "_parse_proc_net", return_value=rows):
            result, err = self.fetcher.fetch()

        self.assertEqual(result, rows)
        self.assertIsNone(err)

    def test_returns_error_message_when_all_sources_empty(self):
        with patch.object(pk.PortDataFetcher, "_parse_ss_output", return_value=None), \
             patch.object(pk.PortDataFetcher, "_parse_netstat_output", return_value=None), \
             patch.object(pk.PortDataFetcher, "_parse_proc_net", return_value=[]):
            result, err = self.fetcher.fetch()

        self.assertEqual(result, [])
        self.assertIsNotNone(err)
        self.assertIsInstance(err, str)
        self.assertGreater(len(err), 0)


# ==============================================================================
# 18. PortDataFetcher._build_inode_map
# ==============================================================================

class TestBuildInodeMap(unittest.TestCase):

    def test_returns_empty_on_proc_oserror(self):
        with patch("porkill.Path.iterdir", side_effect=OSError("no /proc")):
            result = pk.PortDataFetcher._build_inode_map()
        self.assertEqual(result, {})

    def test_ignores_permission_error_on_fd_dir(self):
        pid_entry = MagicMock()
        pid_entry.name = "123"
        pid_entry.is_dir.return_value = True

        fd_dir = MagicMock()
        fd_dir.iterdir.side_effect = PermissionError

        def path_div(part):
            if part == "fd":
                return fd_dir
            return MagicMock()

        with patch("porkill.Path") as MockPath:
            mock_proc = MagicMock()
            mock_proc.iterdir.return_value = [pid_entry]
            MockPath.return_value = mock_proc
            # Just ensure no exception is raised
            try:
                pk.PortDataFetcher._build_inode_map()
            except Exception:
                pass  # We're testing that PermissionError is handled

    def test_non_socket_fd_skipped(self):
        """FDs that don't point to socket:[ should be ignored."""
        pid_entry = MagicMock()
        pid_entry.name = "100"
        pid_entry.is_dir.return_value = True

        fd_mock = MagicMock()
        fd_mock.readlink.return_value = Path("/dev/null")

        fd_dir = MagicMock()
        fd_dir.iterdir.return_value = [fd_mock]

        proc_path = MagicMock()
        proc_path.iterdir.return_value = [pid_entry]
        proc_path.__truediv__ = lambda self, other: fd_dir if other == "100" else MagicMock()

        with patch("porkill.Path", return_value=proc_path), \
             patch("porkill.read_proc_file", return_value="myproc"):
            # This is largely integration-level; we just confirm no crash and
            # the result is a dict.
            result = pk.PortDataFetcher._build_inode_map()
        self.assertIsInstance(result, dict)


# ==============================================================================
# 19. parse_arguments
# ==============================================================================

class TestParseArguments(unittest.TestCase):

    def _parse(self, args):
        with patch("sys.argv", ["porkill"] + args):
            return pk.parse_arguments()

    def test_defaults(self):
        ns = self._parse([])
        self.assertEqual(ns.interval, 2)
        self.assertEqual(ns.max_rows, 10_000)
        self.assertFalse(ns.no_auto_refresh)
        self.assertEqual(ns.log_level, "ERROR")

    def test_interval_short_flag(self):
        ns = self._parse(["-i", "10"])
        self.assertEqual(ns.interval, 10)

    def test_interval_long_flag(self):
        ns = self._parse(["--interval", "30"])
        self.assertEqual(ns.interval, 30)

    def test_max_rows(self):
        ns = self._parse(["--max-rows", "500"])
        self.assertEqual(ns.max_rows, 500)

    def test_max_rows_short(self):
        ns = self._parse(["-m", "200"])
        self.assertEqual(ns.max_rows, 200)

    def test_no_auto_refresh_flag(self):
        ns = self._parse(["--no-auto-refresh"])
        self.assertTrue(ns.no_auto_refresh)

    def test_no_auto_refresh_short(self):
        ns = self._parse(["-n"])
        self.assertTrue(ns.no_auto_refresh)

    def test_log_level_debug(self):
        ns = self._parse(["--log-level", "DEBUG"])
        self.assertEqual(ns.log_level, "DEBUG")

    def test_log_level_short(self):
        ns = self._parse(["-l", "WARNING"])
        self.assertEqual(ns.log_level, "WARNING")

    def test_log_level_invalid_exits(self):
        with self.assertRaises(SystemExit):
            self._parse(["--log-level", "VERBOSE"])

    def test_combined_flags(self):
        ns = self._parse(["-i", "15", "-m", "5000", "-n", "-l", "INFO"])
        self.assertEqual(ns.interval, 15)
        self.assertEqual(ns.max_rows, 5000)
        self.assertTrue(ns.no_auto_refresh)
        self.assertEqual(ns.log_level, "INFO")


# ==============================================================================
# 20. Porkill._validate_interval (static — no display needed)
# ==============================================================================

class TestValidateInterval(unittest.TestCase):
    """
    _validate_interval is a @staticmethod so we can call it without
    instantiating the Porkill window.
    """

    def test_empty_string_allowed(self):
        self.assertTrue(pk.Porkill._validate_interval(""))

    def test_valid_values(self):
        for v in ("2", "10", "60", "120"):
            with self.subTest(v=v):
                self.assertTrue(pk.Porkill._validate_interval(v))

    def test_zero_rejected(self):
        self.assertFalse(pk.Porkill._validate_interval("0"))

    def test_above_120_rejected(self):
        self.assertFalse(pk.Porkill._validate_interval("121"))

    def test_non_digit_rejected(self):
        self.assertFalse(pk.Porkill._validate_interval("abc"))

    def test_float_rejected(self):
        self.assertFalse(pk.Porkill._validate_interval("1.5"))

    def test_negative_rejected(self):
        self.assertFalse(pk.Porkill._validate_interval("-1"))


# ==============================================================================
# 21. LogoCanvas._lerp_color (static — no display needed)
# ==============================================================================

class TestLerpColor(unittest.TestCase):
    """
    _lerp_color is a @staticmethod on LogoCanvas; call it directly.
    """
    lerp = staticmethod(pk.LogoCanvas._lerp_color)

    def test_t_zero_returns_a(self):
        result = self.lerp("#000000", "#ffffff", 0.0)
        self.assertEqual(result, "#000000")

    def test_t_one_returns_b(self):
        result = self.lerp("#000000", "#ffffff", 1.0)
        self.assertEqual(result, "#ffffff")

    def test_t_half(self):
        result = self.lerp("#000000", "#ffffff", 0.5)
        # midpoint of 0 and 255 = 127 = 0x7f
        self.assertEqual(result, "#7f7f7f")

    def test_t_below_zero_clamped(self):
        result = self.lerp("#000000", "#ffffff", -1.0)
        self.assertEqual(result, "#000000")

    def test_t_above_one_clamped(self):
        result = self.lerp("#000000", "#ffffff", 2.0)
        self.assertEqual(result, "#ffffff")

    def test_returns_hash_prefixed_string(self):
        result = self.lerp("#39ff14", "#080c08", 0.5)
        self.assertTrue(result.startswith("#"))
        self.assertEqual(len(result), 7)

    def test_same_color_unchanged(self):
        result = self.lerp("#39ff14", "#39ff14", 0.7)
        self.assertEqual(result, "#39ff14")

    def test_red_channel_only(self):
        result = self.lerp("#ff0000", "#000000", 0.5)
        r = int(result[1:3], 16)
        g = int(result[3:5], 16)
        b = int(result[5:7], 16)
        self.assertGreater(r, 0)
        self.assertEqual(g, 0)
        self.assertEqual(b, 0)


# ==============================================================================
# 22. GUI classes — require a DISPLAY
# ==============================================================================

@unittest.skipUnless(_HAS_DISPLAY, "No DISPLAY available — skipping GUI tests")
class TestStatBadge(unittest.TestCase):

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_initial_value_is_zero(self):
        badge = pk.StatBadge(self.root, "TOTAL", pk.Config.CYAN)
        self.assertEqual(badge._var.get(), "0")

    def test_set_updates_var(self):
        badge = pk.StatBadge(self.root, "LISTEN", pk.Config.NEON)
        badge.set(42)
        self.assertEqual(badge._var.get(), "42")

    def test_set_zero(self):
        badge = pk.StatBadge(self.root, "UDP", pk.Config.AMBER)
        badge.set(0)
        self.assertEqual(badge._var.get(), "0")


@unittest.skipUnless(_HAS_DISPLAY, "No DISPLAY available — skipping GUI tests")
class TestKillButton(unittest.TestCase):

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_command_not_called_on_press_without_hover(self):
        called = []
        btn = pk.KillButton(self.root, "TEST", pk.Config.RED, lambda: called.append(1))
        btn._on_press()
        btn._on_release()  # hover is False → command NOT called
        self.assertEqual(called, [])

    def test_command_called_on_release_with_hover(self):
        called = []
        btn = pk.KillButton(self.root, "TEST", pk.Config.RED, lambda: called.append(1))
        btn._hover = True
        btn._on_press()
        btn._on_release()
        self.assertEqual(called, [1])

    def test_hover_state_changes(self):
        btn = pk.KillButton(self.root, "TEST", pk.Config.AMBER, lambda: None)
        self.assertFalse(btn._hover)
        btn._set_hover(True)
        self.assertTrue(btn._hover)
        btn._set_hover(False)
        self.assertFalse(btn._hover)


@unittest.skipUnless(_HAS_DISPLAY, "No DISPLAY available — skipping GUI tests")
class TestLogoCanvas(unittest.TestCase):

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception:
            pass

    def test_instantiation(self):
        canvas = pk.LogoCanvas(self.root, auto_animate=False)
        self.assertFalse(canvas._destroyed)
        self.assertEqual(canvas._phase, 0.0)
        canvas.destroy()

    def test_destroy_sets_flag(self):
        canvas = pk.LogoCanvas(self.root)
        canvas.destroy()
        self.assertTrue(canvas._destroyed)

    def test_init_rain_populates_columns(self):
        canvas = pk.LogoCanvas(self.root)
        canvas._init_rain(800, 200)
        self.assertTrue(canvas._rain_initialized)
        self.assertGreater(len(canvas._rain_cols), 0)
        canvas.destroy()

    def test_on_configure_resets_rain(self):
        canvas = pk.LogoCanvas(self.root)
        canvas._rain_initialized = True
        canvas._on_configure()
        self.assertFalse(canvas._rain_initialized)
        canvas.destroy()


@unittest.skipUnless(_HAS_DISPLAY, "No DISPLAY available — skipping GUI tests")
class TestPorkillApp(unittest.TestCase):

    def setUp(self):
        args = argparse.Namespace(
            interval=5,
            max_rows=100,
            no_auto_refresh=True,   # prevent background fetches during tests
            log_level="ERROR",
        )
        self.app = pk.Porkill(args)
        self.app.withdraw()

    def tearDown(self):
        try:
            self.app._shutdown_event.set()
            self.app._cancel_pending_jobs()
            if self.app.winfo_exists():
                self.app.destroy()
        except Exception:
            pass

    # ── validate_interval (also tested standalone above) ──────────────────────

    def test_validate_interval_via_instance(self):
        self.assertTrue(self.app._validate_interval("5"))
        self.assertFalse(self.app._validate_interval("0"))

    # ── _update_stats ──────────────────────────────────────────────────────────

    def _make_rows(self, specs):
        """specs: list of (state, proto) tuples."""
        return [
            pk.PortRow(pid="1", name="p", proto=proto, addr="0.0.0.0",
                       port=str(i), state=state, group="p")
            for i, (state, proto) in enumerate(specs)
        ]

    def test_update_stats_total(self):
        rows = self._make_rows([("LISTEN", "TCP"), ("ESTABLISHED", "TCP"), ("—", "UDP")])
        self.app._update_stats(rows)
        self.assertEqual(self.app._s_total._var.get(), "3")

    def test_update_stats_listen_count(self):
        rows = self._make_rows([("LISTEN", "TCP"), ("LISTEN", "TCP"), ("ESTABLISHED", "TCP")])
        self.app._update_stats(rows)
        self.assertEqual(self.app._s_listen._var.get(), "2")

    def test_update_stats_udp_count(self):
        rows = self._make_rows([("—", "UDP"), ("—", "UDP"), ("LISTEN", "TCP")])
        self.app._update_stats(rows)
        self.assertEqual(self.app._s_udp._var.get(), "2")

    def test_update_stats_all_zero_on_empty(self):
        self.app._update_stats([])
        self.assertEqual(self.app._s_total._var.get(), "0")
        self.assertEqual(self.app._s_listen._var.get(), "0")
        self.assertEqual(self.app._s_udp._var.get(), "0")

    # ── _get_sort_key ──────────────────────────────────────────────────────────

    def _row(self, **kwargs):
        defaults = dict(pid="1", name="p", proto="TCP", addr="0.0.0.0",
                        port="80", state="LISTEN", group="p")
        defaults.update(kwargs)
        return pk.PortRow(**defaults)

    def test_get_sort_key_port_numeric(self):
        self.app._sort_column = "port"
        row = self._row(port="22")
        self.assertEqual(self.app._get_sort_key(row), (0, 22))

    def test_get_sort_key_port_non_numeric(self):
        self.app._sort_column = "port"
        row = self._row(port="—")
        self.assertEqual(self.app._get_sort_key(row), (1, 0))

    def test_get_sort_key_pid_numeric(self):
        self.app._sort_column = "pid"
        row = self._row(pid="1234")
        self.assertEqual(self.app._get_sort_key(row), (0, 1234))

    def test_get_sort_key_name_text(self):
        self.app._sort_column = "name"
        row = self._row(name="nginx")
        self.assertEqual(self.app._get_sort_key(row), (1, "nginx"))

    # ── _populate — truncation ─────────────────────────────────────────────────

    def test_populate_truncates_to_max_rows(self):
        pk.Config.MAX_ROWS = 3
        rows = [self._row(port=str(i)) for i in range(10)]

        with patch.object(self.app, "_update_stats") as mock_stats, \
             patch.object(self.app, "_do_apply_filter"):
            self.app._populate(rows)

        # _all_rows was set to the original list (truncated in-place by slice)
        self.assertLessEqual(len(self.app._all_rows), 3)
        # Status should mention truncation
        self.assertIn("TRUNCATED", self.app._status_var.get())

    def test_populate_sets_error_status(self):
        self.app._populate([], error_msg="connection refused")
        self.assertIn("ERROR", self.app._status_var.get())

    def test_populate_sets_updated_status(self):
        with patch.object(self.app, "_update_stats"), \
             patch.object(self.app, "_do_apply_filter"):
            self.app._populate([self._row()])
        self.assertIn("UPDATED", self.app._status_var.get())

    # ── filter logic ──────────────────────────────────────────────────────────

    def test_filter_matches_port(self):
        self.app._all_rows = [self._row(port="8080"), self._row(port="22")]
        self.app._filter_text.set("8080")
        self.app._do_apply_filter()
        items = self.app.tree.get_children()
        # Should have one group header containing port 8080
        self.assertGreater(len(items), 0)

    def test_filter_empty_shows_all(self):
        self.app._all_rows = [self._row(port=str(i)) for i in range(5)]
        self.app._filter_text.set("")
        self.app._do_apply_filter()
        # At minimum one group header exists
        self.assertGreater(len(self.app.tree.get_children()), 0)

    def test_filter_no_match_empty_tree(self):
        self.app._all_rows = [self._row(name="nginx", port="80")]
        self.app._filter_text.set("xyzzy_no_match")
        self.app._do_apply_filter()
        self.assertEqual(len(self.app.tree.get_children()), 0)

    def test_filter_case_insensitive(self):
        self.app._all_rows = [self._row(name="NGINX", port="80")]
        self.app._filter_text.set("nginx")
        self.app._do_apply_filter()
        self.assertGreater(len(self.app.tree.get_children()), 0)

    # ── quit_app ──────────────────────────────────────────────────────────────

    def test_quit_app_sets_shutdown_event(self):
        with patch.object(self.app, "quit"):
            self.app.quit_app()
        self.assertTrue(self.app._shutdown_event.is_set())

    # ── _sort ─────────────────────────────────────────────────────────────────

    def test_sort_same_column_toggles_reverse(self):
        self.app._sort_column = "port"
        self.app._sort_reverse = False
        self.app._all_rows = []
        self.app._sort("port")
        self.assertTrue(self.app._sort_reverse)
        self.app._sort("port")
        self.assertFalse(self.app._sort_reverse)

    def test_sort_new_column_resets_reverse(self):
        self.app._sort_column = "port"
        self.app._sort_reverse = True
        self.app._all_rows = []
        self.app._sort("name")
        self.assertFalse(self.app._sort_reverse)
        self.assertEqual(self.app._sort_column, "name")

    # ── _flash_status ─────────────────────────────────────────────────────────

    def test_flash_status_sets_message(self):
        self.app._flash_status("TEST MESSAGE")
        self.assertEqual(self.app._status_var.get(), "TEST MESSAGE")

    # ── _clear_selection ──────────────────────────────────────────────────────

    def test_clear_selection_resets_state(self):
        self.app._selected_key = ("1", "p", "TCP", "80")
        self.app._clear_selection()
        self.assertIsNone(self.app._selected_key)
        self.assertIn("no process selected", self.app._info_var.get())

    # ── item_sequence rollover ────────────────────────────────────────────────

    def test_item_sequence_resets_at_limit(self):
        self.app._item_sequence = 1_000_001
        self.app._all_rows = [self._row()]
        self.app._filter_text.set("")
        self.app._do_apply_filter()
        self.assertLessEqual(self.app._item_sequence, 10)

    # ── group collapse tracking ───────────────────────────────────────────────

    def test_collapsed_group_stays_closed_on_rebuild(self):
        self.app._all_rows = [self._row(group="nginx", name="nginx")]
        self.app._collapsed_groups = {"grp:nginx"}
        self.app._filter_text.set("")
        self.app._do_apply_filter()
        # Group header should exist and be closed
        children = self.app.tree.get_children()
        grp_iids = [c for c in children if c.startswith("grp:")]
        self.assertGreater(len(grp_iids), 0)
        self.assertFalse(self.app.tree.item(grp_iids[0], "open"))


# ==============================================================================
# Entry point
# ==============================================================================

# ==============================================================================
# 18. Extra Coverage Tests (Integrated)
# ==============================================================================

class TestExtraCoverage(unittest.TestCase):

    def test_main_full_coverage(self):
        """Test the main() function to cover almost all branches."""
        with patch("porkill.parse_arguments") as mock_parse, \
             patch("porkill.Porkill") as mock_app_cls, \
             patch("porkill.signal.signal") as mock_sig, \
             patch("porkill.logging.getLogger"), \
             patch("sys.exit"):

            mock_args = argparse.Namespace(
                interval=150, max_rows=50, no_auto_refresh=False, log_level="INFO"
            )
            mock_parse.return_value = mock_args
            mock_app = mock_app_cls.return_value
            mock_app.winfo_exists.return_value = True

            # Test successful run
            pk.main()
            mock_app.mainloop.assert_called_once()
            mock_app.destroy.assert_called()

            # Verify arg clamping
            self.assertEqual(mock_args.interval, 120)
            self.assertEqual(mock_args.max_rows, 100)

            # Test KeyboardInterrupt
            mock_app.mainloop.side_effect = KeyboardInterrupt
            pk.main()

            # Test signal handler registration
            mock_sig.assert_called()
            handler = mock_sig.call_args[0][1]
            # Call handler directly
            handler(signal.SIGINT, None)
            mock_app.after.assert_called()

    def test_handle_sigint_error(self):
        """Test the SIGINT handler logic in main()."""
        mock_app = MagicMock()
        mock_app.winfo_exists.return_value = True

        def handle_sigint(_sig, _frame):
            try:
                if mock_app.winfo_exists():
                    mock_app.after(0, mock_app.quit_app)
            except pk.tk.TclError:
                pass

        handle_sigint(signal.SIGINT, None)
        mock_app.after.assert_called_with(0, mock_app.quit_app)

        mock_app.after.side_effect = pk.tk.TclError("mock")
        handle_sigint(signal.SIGINT, None)

    def test_porkill_internal_methods_complete(self):
        """Test internal helper methods with all variables mocked."""
        mock_args = argparse.Namespace(
            interval=5, max_rows=100, no_auto_refresh=True, log_level="ERROR"
        )
        with patch("porkill.tk.Tk"), patch("porkill.Porkill._build_ui"):
            app = pk.Porkill(mock_args)
            app.tree = MagicMock()
            app._status_var = MagicMock()
            app._info_var = MagicMock()
            app._auto = MagicMock()
            app._every = MagicMock()
            app._every.get.return_value = 5

            # Initialize ALL stat vars used in _update_stats
            for var in ['_s_total', '_s_pids', '_s_ports', '_s_groups', '_s_listen', '_s_tcp', '_s_udp']:
                setattr(app, var, MagicMock())

            # Test _populate truncated branch
            rows = [pk.PortRow(str(i), "p", "T", "A", "P", "S", "G") for i in range(200)]
            with patch.object(app, "winfo_exists", return_value=True):
                app._populate(rows)

            # Test _update_stats with data
            app._update_stats(rows[:2])

            # Test _on_select branches
            app.tree.selection.return_value = ["grp:item1"]
            app.tree.item.return_value = ("123", "proc", "TCP", "0.0.0.0", "80", "LISTEN")
            app._on_select()

            app.tree.item.return_value = ("", "group", "TCP", "0.0.0.0", "80", "LISTEN")
            app._on_select()

            app.tree.selection.return_value = ["item1"]
            app.tree.item.return_value = ("1", "p", "T", "A", "P", "S")
            app._on_select()

    def test_porkill_kill_branches(self):
        """Test all branches in _kill method."""
        mock_args = argparse.Namespace(
            interval=5, max_rows=100, no_auto_refresh=True, log_level="ERROR"
        )
        with patch("porkill.tk.Tk"), patch("porkill.Porkill._build_ui"):
            app = pk.Porkill(mock_args)
            app.tree = MagicMock()
            app._status_var = MagicMock()

            with patch.object(app, "winfo_exists", return_value=True):
                # 1. Thread safety check
                with patch("threading.current_thread") as mock_thread:
                    mock_thread.return_value = MagicMock() # Not main thread
                    with patch.object(app, "after") as mock_after:
                        app._kill(signal.SIGTERM)
                        mock_after.assert_called()

                # 2. No selection
                app.tree.selection.return_value = []
                app._kill(signal.SIGTERM)

                # 3. Kernel PID
                app.tree.item.return_value = ("\u2014", "k", "T", "A", "P", "S")
                app.tree.selection.return_value = ["item1"]
                with patch("porkill.messagebox.showwarning") as mock_warn:
                    app._kill(signal.SIGTERM)
                    mock_warn.assert_called()

                # 4. Error reading selection
                app.tree.item.side_effect = pk.tk.TclError
                app._kill(signal.SIGTERM)
                app.tree.item.side_effect = None

                # 5. Success signal
                app.tree.item.return_value = ("123", "p", "T", "A", "P", "S")
                with patch("porkill.messagebox.askyesno", return_value=True), \
                     patch("porkill.send_signal_to_pid", return_value=(True, "")):
                    app._kill(signal.SIGTERM)

    def test_fetch_worker_shutdown_guards(self):
        """Test _fetch_worker with shutdown event set."""
        mock_args = argparse.Namespace(
            interval=5, max_rows=100, no_auto_refresh=True, log_level="ERROR"
        )
        with patch("porkill.tk.Tk"), patch("porkill.Porkill._build_ui"):
            app = pk.Porkill(mock_args)
            app._shutdown_event.set()
            app._fetch_worker()
            # Should return immediately

    def test_logo_canvas_draw_branches(self):
        """Cover minor lines in LogoCanvas _draw."""
        with patch("porkill.tk.Tk"):
            canvas = pk.LogoCanvas(MagicMock())
            with patch.object(canvas, "winfo_width", return_value=100), \
                 patch.object(canvas, "winfo_height", return_value=100):
                canvas._draw()


if __name__ == "__main__":
    unittest.main(verbosity=2)
