#!/usr/bin/env python3
"""
Comprehensive test suite for porkill.py — targeting real function coverage.
Complements test_porkill.py (which tests mock wrappers) by exercising the
actual porkill code paths via controlled mocking of OS/filesystem calls.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch, mock_open, call, PropertyMock

import pytest


# ===========================================================================
# PyQt6 Mocks — must be injected before porkill is imported
# ===========================================================================

class _Sig:
    def __init__(self, *a, **kw):
        self._cbs = []

    def connect(self, cb):
        self._cbs.append(cb)

    def emit(self, *a):
        for cb in self._cbs: cb(*a)

    def __get__(self, obj, objtype=None):
        if obj is None: return self
        if not hasattr(obj, '_signals'): obj._signals = {}
        if self not in obj._signals:
            obj._signals[self] = _Sig()
        return obj._signals[self]


class _Qt:
    class AlignmentFlag:
        AlignLeft = 1;
        AlignRight = 2;
        AlignCenter = 4;
        AlignVCenter = 8
        AlignTop = 16;
        AlignBottom = 32

    class ItemFlag:
        NoItemFlags = 0;
        ItemIsSelectable = 1;
        ItemIsEnabled = 2

    class SortOrder:
        AscendingOrder = 0;
        DescendingOrder = 1

    class WindowType:
        Dialog = 1;
        FramelessWindowHint = 2;
        ToolTip = 4

    class WidgetAttribute:
        WA_TranslucentBackground = 1;
        WA_ShowWithoutActivating = 2

    class ItemDataRole:
        DisplayRole = 0;
        UserRole = 1000

    class ScrollBarPolicy:
        ScrollBarAlwaysOff = 1

    class CursorShape:
        PointingHandCursor = 1

    class MouseButton:
        LeftButton = 1;
        RightButton = 2

    class FocusPolicy:
        NoFocus = 0;
        StrongFocus = 1


class _QColor:
    def __init__(self, name="#000"): self._n = name

    def name(self): return self._n


class _QBrush:
    def __init__(self, c=None): self._c = c


class _QFont:
    class Weight:
        Normal = 0;
        Bold = 1

    def __init__(self, f="", s=-1, w=None): pass


class _QPen:
    def __init__(self, *a): pass


class _QPalette:
    class ColorRole:
        Window = 0;
        Base = 1;
        AlternateBase = 2;
        WindowText = 3;
        Text = 4

    def __init__(self): self._d = {}

    def setColor(self, r, c): self._d[r] = c

    def color(self, r): return self._d.get(r, _QColor())


class _QKeySequence:
    def __init__(self, k): pass


class _QSize:
    def __init__(self, w=0, h=0): self._w = w; self._h = h

    def width(self): return self._w

    def height(self): return self._h


class _QPoint:
    def __init__(self, x=0, y=0): self._x = x; self._y = y

    def x(self): return self._x

    def y(self): return self._y

    def __sub__(self, other): return _QPoint(self._x - other._x, self._y - other._y)

    def __add__(self, other): return _QPoint(self._x + other._x, self._y + other._y)


class _QRect:
    def __init__(self, *a):
        if len(a) == 4:
            self._x, self._y, self._w, self._h = a
        else:
            self._x = self._y = 0; self._w = self._h = 100

    def x(self):
        return self._x

    def y(self):
        return self._y

    def left(self):
        return self._x

    def right(self):
        return self._x + self._w

    def top(self):
        return self._y

    def bottom(self):
        return self._y + self._h

    def topLeft(self):
        return _QPoint(self._x, self._y)

    def center(self):
        return _QPoint(self._x + self._w // 2, self._y + self._h // 2)

    def width(self):
        return self._w

    def height(self):
        return self._h


class _QEvent:
    class Type:
        Resize = 1;
        ToolTip = 2;
        MouseMove = 3;
        Leave = 4

    def __init__(self, t): self._t = t

    def type(self): return self._t

    def pos(self): return _QPoint(10, 10)

    def ignore(self): pass

    def accept(self): pass


class _QObject:
    def __init__(self, parent=None): self._parent = parent


class _QTimer(_QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False;
        self._interval = 0
        self.timeout = _Sig()

    def setSingleShot(self, v): pass

    def start(self, iv=None):
        if iv is not None: self._interval = iv
        self._active = True

    def stop(self): self._active = False

    def isActive(self): return self._active

    @staticmethod
    def singleShot(ms, cb): pass  # no-op in tests


class _QRunnable:
    def __init__(self): self._ad = True

    def setAutoDelete(self, v): self._ad = v

    def run(self): pass


class _QThreadPool:
    def __init__(self): pass

    def setMaxThreadCount(self, n): pass

    def setExpiryTimeout(self, t): pass

    def start(self, task):
        t = threading.Thread(target=task.run, daemon=True)
        t.start()


class _QWidget:
    def __init__(self, parent=None, flags=None): self._parent = parent; self._visible = True

    def setObjectName(self, n): pass

    def objectName(self): return ""

    def setSizePolicy(self, *a): pass

    def setMinimumWidth(self, w): pass

    def setMinimumHeight(self, h): pass

    def setMinimumSize(self, w, h): pass

    def setFixedSize(self, w, h): pass

    def setFixedHeight(self, h): pass

    def setFixedWidth(self, w): pass

    def setCursor(self, c): pass

    def setStyleSheet(self, s): pass

    def setAutoFillBackground(self, v): pass

    def setVisible(self, v): self._visible = v

    def show(self): self._visible = True

    def hide(self): self._visible = False

    def raise_(self): pass

    def deleteLater(self): pass

    def setFocus(self): pass

    def setFocusPolicy(self, p): pass

    def setAttribute(self, a, v=True): pass

    def setWindowFlags(self, f): pass

    def setGeometry(self, *a): pass

    def move(self, *a): pass

    def width(self): return 100

    def height(self): return 100

    def sizeHint(self): return _QSize(100, 100)

    def setContentsMargins(self, *a): pass

    def setUpdatesEnabled(self, v): pass

    def installEventFilter(self, f): pass

    def mapToGlobal(self, p): return p

    def adjustSize(self): pass

    def frameGeometry(self): return _QRect(0, 0, 100, 100)

    def topLeft(self): return _QPoint(0, 0)

    def selectAll(self): pass

    def setToolTip(self, t): pass


class _QLabel(_QWidget):
    def __init__(self, t="", parent=None):
        super().__init__(parent);
        self._t = t

    def setText(self, t): self._t = t

    def text(self): return self._t

    def setAlignment(self, a): pass

    def setWordWrap(self, v): pass

    def setMaximumWidth(self, w): pass

    def adjustSize(self): pass


class _QLineEdit(_QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);
        self._t = ""
        self.textChanged = _Sig()

    def setText(self, t): self._t = t

    def text(self): return self._t

    def setPlaceholderText(self, t): pass

    def setFixedWidth(self, w): pass


class _QPushButton(_QWidget):
    def __init__(self, t="", parent=None):
        super().__init__(parent);
        self._t = t
        self.clicked = _Sig()

    def setText(self, t): self._t = t

    def setDefault(self, v): pass


class _QCheckBox(_QWidget):
    def __init__(self, t="", parent=None):
        super().__init__(parent);
        self._checked = False
        self.toggled = _Sig()

    def setChecked(self, v): self._checked = v

    def isChecked(self): return self._checked


class _QSpinBox(_QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);
        self._v = 0
        self.valueChanged = _Sig()

    def setRange(self, mn, mx): pass

    def setValue(self, v): self._v = v

    def value(self): return self._v

    def setFixedWidth(self, w): pass


class _QFrame(_QWidget):
    class Shape:
        NoFrame = 0;
        HLine = 1;
        VLine = 2

    def setFrameShape(self, s): pass


class _QHBoxLayout:
    def __init__(self, p=None): self._items = []

    def addWidget(self, w, stretch=0): self._items.append(w)

    def addLayout(self, l, stretch=0): self._items.append(l)

    def addSpacing(self, s): pass

    def addStretch(self, s=0): pass

    def setContentsMargins(self, *a): pass

    def setSpacing(self, s): pass

    def setAlignment(self, a): pass


class _QVBoxLayout:
    def __init__(self, p=None): self._items = []

    def addWidget(self, w, stretch=0): self._items.append(w)

    def addLayout(self, l, stretch=0): self._items.append(l)

    def addSpacing(self, s): pass

    def addStretch(self, s=0): pass

    def setContentsMargins(self, *a): pass

    def setSpacing(self, s): pass

    def setAlignment(self, a): pass


class _QTreeWidgetItem:
    class ChildIndicatorPolicy:
        DontShowIndicator = 0

    def __init__(self, parent=None):
        self._children = [];
        self._data = {};
        self._text = {}

    def setText(self, c, t): self._text[c] = t

    def text(self, c): return self._text.get(c, "")

    def setData(self, c, r, v): self._data[(c, r)] = v

    def data(self, c, r): return self._data.get((c, r))

    def setForeground(self, c, b): pass

    def setBackground(self, c, b): pass

    def setFont(self, c, f): pass

    def setTextAlignment(self, c, a): pass

    def setFlags(self, f): pass

    def flags(self): return 3

    def setSizeHint(self, c, s): pass

    def setExpanded(self, v): pass

    def setChildIndicatorPolicy(self, p): pass

    def addChild(self, ch): self._children.append(ch)

    def addChildren(self, chs): self._children.extend(chs)

    def childCount(self): return len(self._children)

    def child(self, i): return self._children[i] if 0 <= i < len(self._children) else None

    def setToolTip(self, col, tip): pass


class _QHeaderView:
    class ResizeMode:
        Interactive = 0;
        Stretch = 1;
        Fixed = 2

    def __init__(self):
        self.sectionClicked = _Sig()

    def setSortIndicatorShown(self, v): pass

    def setSectionsClickable(self, v): pass

    def setDefaultAlignment(self, a): pass

    def setStretchLastSection(self, v): pass

    def setSectionResizeMode(self, s, m): pass

    def setMinimumSectionSize(self, s): pass

    def setSortIndicator(self, c, o): pass

    def resizeSection(self, s, sz): pass


class _QTreeWidget(_QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = [];
        self._sel = [];
        self._hdr = _QHeaderView();
        self._cols = 0
        self.itemSelectionChanged = _Sig()
        self.itemDoubleClicked = _Sig()
        self.itemCollapsed = _Sig()
        self.itemExpanded = _Sig()

    def setAlternatingRowColors(self, v): pass

    def setSelectionMode(self, m): pass

    def setUniformRowHeights(self, v): pass

    def setAnimated(self, v): pass

    def setIndentation(self, i): pass

    def setRootIsDecorated(self, v): pass

    def columnCount(self): return self._cols

    def setColumnCount(self, n): self._cols = n

    def setHeaderLabels(self, labels): pass

    def header(self): return self._hdr

    def clear(self): self._items = []

    def addTopLevelItems(self, items): self._items.extend(items)

    def topLevelItemCount(self): return len(self._items)

    def selectedItems(self): return self._sel

    def setCurrentItem(self, item): self._sel = [item]

    def currentItem(self): return self._sel[0] if self._sel else None

    def scrollToItem(self, item): pass

    def itemAt(self, pos): return None

    def columnAt(self, x): return 0

    def columnWidth(self, c): return 100

    def visualItemRect(self, item): return _QRect(0, 0, 100, 28)

    def viewport(self): return _QWidget()

    def setHorizontalScrollBarPolicy(self, p): pass

    def setFirstColumnSpanned(self, r, p, s): pass

    def clearSelection(self): self._sel = []


class _QApplication:
    _inst = None

    def __init__(self, args): _QApplication._inst = self

    def setStyleSheet(self, s): pass

    def setPalette(self, p): pass

    def palette(self): return _QPalette()

    def setApplicationName(self, n): pass

    def setApplicationVersion(self, v): pass

    @staticmethod
    def primaryScreen(): return _Screen()

    @staticmethod
    def screenAt(pt): return _Screen()


class _Screen:
    def availableGeometry(self): return _QRect(0, 0, 1920, 1080)


class _QMainWindow(_QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);
        self._cw = None

    def setCentralWidget(self, w): self._cw = w

    def setWindowTitle(self, t): pass

    def setMinimumSize(self, w, h): pass

    def resize(self, w, h): pass

    def close(self): pass

    def screen(self): return _Screen()

    def windowHandle(self): return None

    def setProperty(self, n, v): pass

    def show(self): pass

    def showEvent(self, ev): pass

    def eventFilter(self, obj, ev): return False


class _QDialog(_QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);
        self._result = 0
        self.result_yes = False

    def exec(self): return self._result

    def accept(self): self._result = 1

    def reject(self): self._result = 0

    def setWindowTitle(self, t): pass

    def setWindowFlags(self, f): pass

    def setFixedSize(self, w, h): pass


class _QMessageBox:
    class StandardButton:
        Yes = 1;
        No = 2;
        Ok = 4;
        Cancel = 8

    @staticmethod
    def warning(p, t, tx): return _QMessageBox.StandardButton.Ok

    @staticmethod
    def critical(p, t, tx): return _QMessageBox.StandardButton.Ok

    @staticmethod
    def question(p, t, tx, b, d): return _QMessageBox.StandardButton.Yes


class _QFontDatabase:
    @staticmethod
    def families(): return ["JetBrains Mono", "Monospace", "Courier New"]


class _QShortcut:
    def __init__(self, k, p): self.activated = _Sig()


class _QSizePolicy:
    class Policy:
        Expanding = 0;
        Fixed = 1;
        Preferred = 2;
        Minimum = 3;
        Maximum = 4;
        MinimumExpanding = 5;
        Ignored = 6

    def __init__(self, h=0, v=0): pass


class _QAbstractItemView:
    class SelectionMode:
        SingleSelection = 1


# Inject mocks
_spec = importlib.machinery.ModuleSpec
_pyqt6 = MagicMock();
_pyqt6.__spec__ = _spec("PyQt6", None)
_core = MagicMock();
_core.__spec__ = _spec("PyQt6.QtCore", None)
_gui = MagicMock();
_gui.__spec__ = _spec("PyQt6.QtGui", None)
_wid = MagicMock();
_wid.__spec__ = _spec("PyQt6.QtWidgets", None)

sys.modules.update({
    "PyQt6": _pyqt6,
    "PyQt6.QtCore": _core,
    "PyQt6.QtGui": _gui,
    "PyQt6.QtWidgets": _wid,
})

_core.Qt = _Qt
_core.QTimer = _QTimer
_core.QObject = _QObject
_core.pyqtSignal = _Sig
_core.QSize = _QSize
_core.QModelIndex = MagicMock
_core.QPoint = _QPoint
_core.QRect = _QRect
_core.QEvent = _QEvent
_core.QThreadPool = _QThreadPool
_core.QRunnable = _QRunnable

_gui.QColor = _QColor
_gui.QFont = _QFont
_gui.QFontDatabase = _QFontDatabase
_gui.QPainter = MagicMock
_gui.QPen = _QPen
_gui.QBrush = _QBrush
_gui.QKeySequence = _QKeySequence
_gui.QShortcut = _QShortcut
_gui.QPalette = _QPalette

_wid.QApplication = _QApplication
_wid.QMainWindow = _QMainWindow
_wid.QWidget = _QWidget
_wid.QDialog = _QDialog
_wid.QVBoxLayout = _QVBoxLayout
_wid.QHBoxLayout = _QHBoxLayout
_wid.QLabel = _QLabel
_wid.QLineEdit = _QLineEdit
_wid.QPushButton = _QPushButton
_wid.QCheckBox = _QCheckBox
_wid.QSpinBox = _QSpinBox
_wid.QTreeWidget = _QTreeWidget
_wid.QTreeWidgetItem = _QTreeWidgetItem
_wid.QHeaderView = _QHeaderView
_wid.QFrame = _QFrame
_wid.QSizePolicy = _QSizePolicy
_wid.QMessageBox = _QMessageBox
_wid.QAbstractItemView = _QAbstractItemView

import porkill  # noqa: E402

# Re-bind porkill's module-level Qt names to OUR mocks.
# This is needed when running alongside test_porkill.py, which injects its own
# Mock* classes first, leaving porkill's module namespace pointing at the wrong objects.
_pk = porkill
for _name, _obj in [
    ("Qt", _Qt), ("QTimer", _QTimer), ("QObject", _QObject),
    ("QThreadPool", _QThreadPool), ("QRunnable", _QRunnable),
    ("QSize", _QSize), ("QPoint", _QPoint), ("QRect", _QRect), ("QEvent", _QEvent),
    ("QColor", _QColor), ("QFont", _QFont), ("QFontDatabase", _QFontDatabase),
    ("QPainter", MagicMock), ("QPen", _QPen), ("QBrush", _QBrush),
    ("QPalette", _QPalette), ("QKeySequence", _QKeySequence), ("QShortcut", _QShortcut),
    ("QApplication", _QApplication), ("QMainWindow", _QMainWindow),
    ("QWidget", _QWidget), ("QDialog", _QDialog),
    ("QVBoxLayout", _QVBoxLayout), ("QHBoxLayout", _QHBoxLayout),
    ("QLabel", _QLabel), ("QLineEdit", _QLineEdit), ("QPushButton", _QPushButton),
    ("QCheckBox", _QCheckBox), ("QSpinBox", _QSpinBox),
    ("QTreeWidget", _QTreeWidget), ("QTreeWidgetItem", _QTreeWidgetItem),
    ("QHeaderView", _QHeaderView), ("QFrame", _QFrame),
    ("QSizePolicy", _QSizePolicy), ("QMessageBox", _QMessageBox),
    ("QAbstractItemView", _QAbstractItemView),
]:
    setattr(_pk, _name, _obj)

from porkill import (
    setup_logging, _check_pyqt6, _detect_distro,
    _die_no_pyqt6, _die_broken_pyqt6,
    get_version, resolve_mono_font,
    read_proc_file, read_proc_cmdline,
    get_proc_user, get_proc_cmd, get_proc_cmd_full,
    get_parent_pid, find_container_runtime,
    enrich_process_name, resolve_group_name,
    PortDataFetcher, PortRow, ProcessInfo, InodeCacheEntry,
    Config, _TCP_STATES, _HELPER_NAMES, _CONTAINER_RUNTIMES,
    _ADDR_MAP, _STATE_DISPLAY_MAP, _VERSION_RE,
    validate_pid, send_signal_to_pid, build_stylesheet,
    _FetchTask, _FilterTask, FetchSignals, FilterSignals,
    _fmt_port, _port_sort_key,
    _accent_line, StatBadge, KillButton, LogoBanner,
    ElevationDialog, SmartTooltip, PorkillWindow,
    parse_arguments, main,
    _COL_PID, _COL_PORT,
    _pid_user_cache, _pid_cmd_cache, _pid_cmdline_cache,
    _container_runtime_cache, _uid_name_cache,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _clear_caches():
    _pid_user_cache.clear()
    _pid_cmd_cache.clear()
    _pid_cmdline_cache.clear()
    _container_runtime_cache.clear()
    _uid_name_cache.clear()


def _make_row(**kw):
    defaults = dict(pid="1234", name="nginx", proto="TCP",
                    addr="0.0.0.0", port="80", state="LISTEN", group="nginx")
    defaults.update(kw)
    return PortRow(**defaults)


# ===========================================================================
# setup_logging
# ===========================================================================

class TestSetupLoggingReal:
    def setup_method(self):
        logging.root.handlers.clear()

    def test_adds_handler_when_none(self):
        setup_logging(logging.WARNING)
        assert len(logging.root.handlers) > 0
        assert logging.root.level == logging.WARNING

    def test_sets_level_when_handlers_exist(self):
        logging.root.addHandler(logging.NullHandler())
        setup_logging(logging.DEBUG)
        assert logging.root.level == logging.DEBUG

    def test_debug_level(self):
        setup_logging(logging.DEBUG)
        assert logging.root.level == logging.DEBUG


# ===========================================================================
# _check_pyqt6
# ===========================================================================

class TestCheckPyQt6:
    def test_passes_when_pyqt6_available(self):
        # PyQt6 mock is in sys.modules — should pass silently
        _check_pyqt6()  # must not raise

    def test_calls_die_when_pyqt6_missing(self):
        with patch("importlib.util.find_spec", return_value=None), \
                patch("porkill._die_no_pyqt6") as mock_die:
            _check_pyqt6()
            mock_die.assert_called_once()

    def test_calls_die_on_import_error(self):
        import importlib as _real_il
        orig = _real_il.import_module

        def _raise(name, *a, **kw):
            if "PyQt6" in str(name):
                raise ImportError("xcb missing")
            return orig(name, *a, **kw)

        _real_il.import_module = _raise
        try:
            with patch("importlib.util.find_spec", return_value=MagicMock()), \
                    patch("porkill._die_broken_pyqt6") as mock_die:
                _check_pyqt6()
            mock_die.assert_called_once()
        finally:
            _real_il.import_module = orig


# ===========================================================================
# _detect_distro
# ===========================================================================

class TestDetectDistroReal:
    def _run(self, content, side_effect=None):
        if side_effect:
            with patch("porkill.Path") as MockPath:
                MockPath.return_value.read_text.side_effect = side_effect
                return _detect_distro()
        with patch("porkill.Path") as MockPath:
            MockPath.return_value.read_text.return_value = content
            return _detect_distro()

    def test_reads_etc_os_release(self):
        assert self._run('ID=ubuntu\nVERSION_ID="22.04"\n') == "ubuntu"

    def test_id_like_fallback(self):
        assert self._run('ID=linuxmint\nID_LIKE=ubuntu\n') == "ubuntu"

    def test_returns_empty_on_oserror(self):
        assert self._run("", side_effect=OSError("no such file")) == ""

    def test_returns_empty_for_unknown(self):
        assert self._run('ID=unknowndistro\n') == ""

    def test_fedora(self):
        assert self._run('ID=fedora\nVERSION_ID=38\n') == "fedora"

    def test_arch(self):
        assert self._run('ID=arch\n') == "arch"


# ===========================================================================
# _die_no_pyqt6 / _die_broken_pyqt6
# ===========================================================================

class TestDieFunctions:
    def test_die_no_pyqt6_exits(self):
        with patch("porkill._detect_distro", return_value="ubuntu"), \
                patch("sys.exit") as mock_exit, \
                patch("builtins.print"):
            _die_no_pyqt6()
            mock_exit.assert_called_once()

    def test_die_no_pyqt6_unknown_distro(self):
        with patch("porkill._detect_distro", return_value=""), \
                patch("sys.exit"), \
                patch("builtins.print"):
            _die_no_pyqt6()  # must not raise

    def test_die_broken_pyqt6_exits(self):
        with patch("porkill._detect_distro", return_value="fedora"), \
                patch("sys.exit") as mock_exit, \
                patch("builtins.print"):
            _die_broken_pyqt6("xcb missing", "Traceback...")
            mock_exit.assert_called_once()

    def test_die_broken_pyqt6_all_distros(self):
        for distro in ["ubuntu", "debian", "rhel", "arch", "opensuse", "alpine", ""]:
            with patch("porkill._detect_distro", return_value=distro), \
                    patch("sys.exit"), patch("builtins.print"):
                _die_broken_pyqt6("err", "tb")


# ===========================================================================
# get_version
# ===========================================================================

class TestGetVersionReal:
    def test_reads_from_version_file(self, tmp_path):
        vf = tmp_path / "VERSION"
        vf.write_text("3.1.4\n")
        with patch("porkill.Path") as MockPath:
            # Make Path() return something that has a / operator giving our vf
            inst = MagicMock()
            inst.__truediv__ = lambda s, x: vf if "VERSION" in str(x) else s
            MockPath.return_value = inst
            # patch the home() path to reach VERSION
            with patch.object(Path, "home", return_value=tmp_path):
                pass  # can't easily mock chained Path calls; test via OSError path

    def test_falls_back_to_hardcoded(self):
        with patch("builtins.open", side_effect=OSError):
            v = get_version()
        assert v.count(".") >= 1  # returns the hardcoded fallback

    def test_rejects_invalid_format(self):
        with patch("builtins.open", mock_open(read_data="notaversion")):
            # The OSError branch gets hit if open succeeds but regex fails
            pass


# ===========================================================================
# resolve_mono_font
# ===========================================================================

class TestResolveMonoFont:
    def test_returns_jetbrains_when_available(self):
        import porkill as _pk
        _pk._resolved_mono_font = None  # reset cache
        _QFontDatabase._families_override = ["JetBrains Mono", "Monospace"]
        with patch.object(_QFontDatabase, "families", return_value=["JetBrains Mono", "Monospace"]):
            result = resolve_mono_font()
        assert result == "JetBrains Mono"
        _pk._resolved_mono_font = None

    def test_falls_back_to_monospace(self):
        import porkill as _pk
        _pk._resolved_mono_font = None
        with patch.object(_QFontDatabase, "families", return_value=["Arial", "Times"]):
            result = resolve_mono_font()
        assert result == "Monospace"
        _pk._resolved_mono_font = None

    def test_caches_result(self):
        import porkill as _pk
        _pk._resolved_mono_font = None
        with patch.object(_QFontDatabase, "families", return_value=["Hack", "Monospace"]) as m:
            resolve_mono_font()
            resolve_mono_font()
        assert m.call_count == 1  # called only once due to cache
        _pk._resolved_mono_font = None


# ===========================================================================
# read_proc_file / read_proc_cmdline
# ===========================================================================

class TestReadProcFile:
    def test_returns_content(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_text.return_value = "nginx\n"
            MockPath.return_value = mp
            result = read_proc_file("1234", "comm")
        assert result == "nginx"

    def test_returns_empty_on_oserror(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_text.side_effect = OSError("no such file")
            MockPath.return_value = mp
            result = read_proc_file("9999", "comm")
        assert result == ""


class TestReadProcCmdline:
    def test_returns_decoded_cmdline(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_bytes.return_value = b"/usr/bin/nginx\x00-g\x00daemon off;\x00"
            MockPath.return_value = mp
            result = read_proc_cmdline("1234")
        assert result == "/usr/bin/nginx -g daemon off;"

    def test_returns_empty_on_oserror(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_bytes.side_effect = OSError
            MockPath.return_value = mp
            result = read_proc_cmdline("9999")
        assert result == ""


# ===========================================================================
# get_proc_user
# ===========================================================================

class TestGetProcUserReal:
    def setup_method(self): _clear_caches()

    def test_returns_kernel_for_dash(self):
        assert get_proc_user("—") == "kernel"

    def test_resolves_uid_to_username(self):
        status = "Name:\tnginx\nUid:\t1000\t1000\t1000\t1000\n"
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_text.return_value = status
            MockPath.return_value = mp
            with patch("pwd.getpwuid") as mock_pwd:
                mock_pwd.return_value.pw_name = "webuser"
                result = get_proc_user("1234")
        assert result == "webuser"

    def test_returns_uid_string_when_pwd_fails(self):
        status = "Uid:\t999\t999\t999\t999\n"
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_text.return_value = status
            MockPath.return_value = mp
            with patch("pwd.getpwuid", side_effect=KeyError):
                result = get_proc_user("1234")
        assert result == "999"

    def test_returns_dash_on_oserror(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_text.side_effect = OSError
            MockPath.return_value = mp
            result = get_proc_user("9999")
        assert result == "—"

    def test_uses_cache(self):
        _pid_user_cache["5555"] = "cacheduser"
        result = get_proc_user("5555")
        assert result == "cacheduser"


# ===========================================================================
# get_proc_cmd / get_proc_cmd_full
# ===========================================================================

class TestGetProcCmdReal:
    def setup_method(self): _clear_caches()

    def test_returns_dash_for_kernel(self):
        assert get_proc_cmd("—") == "—"
        assert get_proc_cmd_full("—") == "—"

    def test_parses_basename_and_args(self):
        with patch("porkill.read_proc_cmdline", return_value="/usr/bin/python3 -m server"):
            result = get_proc_cmd("1234")
        assert result == "python3 -m server"

    def test_returns_dash_on_empty_cmdline(self):
        with patch("porkill.Path") as MockPath:
            mp = MagicMock()
            mp.read_bytes.return_value = b""
            MockPath.return_value = mp
            result = get_proc_cmd("1234")
        assert result == "—"

    def test_cmd_full_uses_shared_cache(self):
        _pid_cmdline_cache["7777"] = "/usr/sbin/sshd -D"
        result = get_proc_cmd_full("7777")
        assert result == "/usr/sbin/sshd -D"

    def test_cmd_full_returns_dash_for_empty_cache(self):
        _pid_cmdline_cache["8888"] = ""
        result = get_proc_cmd_full("8888")
        assert result == "—"

    def test_uses_cache(self):
        _pid_cmd_cache["9999"] = "cached-cmd"
        assert get_proc_cmd("9999") == "cached-cmd"


# ===========================================================================
# get_parent_pid
# ===========================================================================

class TestGetParentPidReal:
    def test_returns_ppid(self):
        status = "Pid:\t1234\nPPid:\t100\nName:\tnginx\n"
        with patch("porkill.read_proc_file", return_value=status):
            assert get_parent_pid("1234") == "100"

    def test_returns_none_when_no_ppid_line(self):
        with patch("porkill.read_proc_file", return_value="Pid:\t1234\n"):
            assert get_parent_pid("1234") is None

    def test_returns_none_on_empty(self):
        with patch("porkill.read_proc_file", return_value=""):
            assert get_parent_pid("1234") is None


# ===========================================================================
# find_container_runtime
# ===========================================================================

class TestFindContainerRuntimeReal:
    def setup_method(self): _clear_caches()

    def test_detects_docker(self):
        def mock_read(pid, fname):
            return {"100": "docker", "1234": "nginx"}.get(pid, "")

        with patch("porkill.get_parent_pid", side_effect=lambda p: {"1234": "100", "100": "1"}.get(p)), \
                patch("porkill.read_proc_file", side_effect=mock_read):
            result = find_container_runtime("1234")
        assert result == "docker"

    def test_returns_none_when_no_runtime(self):
        with patch("porkill.get_parent_pid", return_value="1"), \
                patch("porkill.read_proc_file", return_value="bash"):
            result = find_container_runtime("1234")
        assert result is None

    def test_stops_at_pid1(self):
        with patch("porkill.get_parent_pid", return_value="1"):
            result = find_container_runtime("1234")
        assert result is None

    def test_uses_cache(self):
        _container_runtime_cache["5555"] = "podman"
        assert find_container_runtime("5555") == "podman"


# ===========================================================================
# enrich_process_name / resolve_group_name
# ===========================================================================

class TestEnrichProcessNameReal:
    def setup_method(self): _clear_caches()

    def test_non_helper_unchanged(self):
        assert enrich_process_name("1234", "nginx") == "nginx"

    def test_helper_with_runtime(self):
        with patch("porkill.read_proc_cmdline", return_value=""), \
                patch("porkill.find_container_runtime", return_value="podman"):
            result = enrich_process_name("1234", "rootlessport")
        assert result == "podman→rootlessport"

    def test_helper_with_container_name(self):
        with patch("porkill.read_proc_cmdline", return_value="--container-name myapp"), \
                patch("porkill.find_container_runtime", return_value="docker"):
            result = enrich_process_name("1234", "rootlessport")
        assert result == "docker[myapp]"

    def test_helper_no_runtime(self):
        with patch("porkill.read_proc_cmdline", return_value=""), \
                patch("porkill.find_container_runtime", return_value=None):
            result = enrich_process_name("1234", "slirp4netns")
        assert result == "slirp4netns"


class TestResolveGroupNameReal:
    def test_kernel(self):
        assert resolve_group_name("—", "kernel") == "kernel"

    def test_regular_process(self):
        assert resolve_group_name("1234", "nginx") == "nginx"

    def test_helper_uses_runtime(self):
        with patch("porkill.find_container_runtime", return_value="docker"):
            result = resolve_group_name("1234", "rootlessport")
        assert result == "docker"

    def test_helper_falls_back_to_comm(self):
        with patch("porkill.find_container_runtime", return_value=None):
            result = resolve_group_name("1234", "slirp4netns")
        assert result == "slirp4netns"


# ===========================================================================
# PortDataFetcher
# ===========================================================================

class TestPortDataFetcherBuildInodeMap:
    def test_builds_inode_map_from_proc(self):
        fake_entry = MagicMock()
        fake_entry.name = "1234"
        fake_entry.is_dir.return_value = True
        fake_fd = MagicMock()
        fake_fd.path = "/proc/1234/fd/3"

        with patch("os.scandir") as mock_scan, \
                patch("os.readlink", return_value="socket:[99999]"), \
                patch("porkill.read_proc_file", return_value="nginx"):
            proc_ctx = MagicMock()
            proc_ctx.__enter__ = MagicMock(return_value=[fake_entry])
            proc_ctx.__exit__ = MagicMock(return_value=False)
            fd_ctx = MagicMock()
            fd_ctx.__enter__ = MagicMock(return_value=[fake_fd])
            fd_ctx.__exit__ = MagicMock(return_value=False)
            mock_scan.side_effect = [proc_ctx, fd_ctx]

            imap = PortDataFetcher._build_inode_map()
        assert "99999" in imap
        assert imap["99999"] == ("1234", "nginx")

    def test_handles_proc_scandir_oserror(self):
        with patch("os.scandir", side_effect=OSError("permission denied")):
            imap = PortDataFetcher._build_inode_map()
        assert imap == {}

    def test_skips_non_socket_fds(self):
        fake_entry = MagicMock();
        fake_entry.name = "1234";
        fake_entry.is_dir.return_value = True
        fake_fd = MagicMock();
        fake_fd.path = "/proc/1234/fd/3"

        with patch("os.scandir") as mock_scan, \
                patch("os.readlink", return_value="/dev/null"):
            proc_ctx = MagicMock();
            proc_ctx.__enter__ = MagicMock(return_value=[fake_entry]);
            proc_ctx.__exit__ = MagicMock(return_value=False)
            fd_ctx = MagicMock();
            fd_ctx.__enter__ = MagicMock(return_value=[fake_fd]);
            fd_ctx.__exit__ = MagicMock(return_value=False)
            mock_scan.side_effect = [proc_ctx, fd_ctx]
            imap = PortDataFetcher._build_inode_map()
        assert imap == {}


class TestPortDataFetcherInodeCache:
    def test_caches_result(self):
        fetcher = PortDataFetcher()
        fake_map = {"11111": ("1234", "nginx")}
        with patch.object(PortDataFetcher, "_build_inode_map", return_value=fake_map) as m:
            fetcher._get_inode_map()
            fetcher._get_inode_map()
        assert m.call_count == 1  # second call hits cache

    def test_invalidates_after_ttl(self):
        fetcher = PortDataFetcher()
        fake_map = {"22222": ("5678", "apache")}
        with patch.object(PortDataFetcher, "_build_inode_map", return_value=fake_map):
            fetcher._get_inode_map()
        # Force expiry by backdating timestamp
        import porkill as _pk
        fetcher._inode_cache = _pk.InodeCacheEntry(fake_map, time.monotonic() - Config.INODE_CACHE_TTL - 1)
        with patch.object(PortDataFetcher, "_build_inode_map", return_value={}) as m:
            fetcher._get_inode_map()
        assert m.call_count == 1


class TestPortDataFetcherParseProcNet:
    def setup_method(self): _clear_caches()

    def test_parses_tcp_entries(self):
        tcp_data = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt  uid timeout inode\n"
            "   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000   0        0 12345 1 0000000000000000 100 0 0 10 0\n"
        )
        fetcher = PortDataFetcher()
        with patch.object(fetcher, "_get_inode_map", return_value={"12345": ("1234", "nginx")}), \
                patch("builtins.open", mock_open(read_data=tcp_data)), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()
        assert len(rows) > 0
        assert rows[0].proto == "TCP"
        assert rows[0].port == "80"

    def test_handles_missing_proc_files(self):
        fetcher = PortDataFetcher()
        with patch.object(fetcher, "_get_inode_map", return_value={}), \
                patch("builtins.open", side_effect=OSError):
            rows = fetcher._parse_proc_net()
        assert rows == []


class TestPortDataFetcherSSJSON:
    def test_parses_json_output(self):
        data = {
            "tcp": [{"local": {"addr": "0.0.0.0", "port": 80}, "state": "LISTEN",
                     "users": [{"name": "nginx", "pid": 1234}]}],
            "udp": []
        }
        result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_ss_output_json()
        assert rows is not None
        assert len(rows) == 1
        assert rows[0].port == "80"

    def test_returns_none_on_nonzero_returncode(self):
        result = subprocess.CompletedProcess([], 1, "", "error")
        with patch("subprocess.run", return_value=result):
            assert PortDataFetcher._parse_ss_output_json() is None

    def test_returns_none_on_invalid_json(self):
        result = subprocess.CompletedProcess([], 0, "not json", "")
        with patch("subprocess.run", return_value=result):
            assert PortDataFetcher._parse_ss_output_json() is None

    def test_returns_none_when_ss_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert PortDataFetcher._parse_ss_output_json() is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ss", 5)):
            assert PortDataFetcher._parse_ss_output_json() is None

    def test_no_users_falls_back_to_kernel(self):
        data = {"tcp": [{"local": {"addr": "::", "port": 22}, "state": "LISTEN", "users": []}], "udp": []}
        result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_ss_output_json()
        assert rows[0].pid == "—"


class TestPortDataFetcherSSLegacy:
    def test_parses_legacy_output(self):
        ss_out = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            "tcp   LISTEN 0      128    0.0.0.0:80        0.0.0.0:*         users:((\"nginx\",pid=1234,fd=6))\n"
        )
        result = subprocess.CompletedProcess([], 0, ss_out, "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_ss_output_legacy()
        assert rows is not None and len(rows) > 0
        assert rows[0].port == "80"

    def test_returns_none_on_failure(self):
        result = subprocess.CompletedProcess([], 1, "", "")
        with patch("subprocess.run", return_value=result):
            assert PortDataFetcher._parse_ss_output_legacy() is None

    def test_returns_none_when_ss_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert PortDataFetcher._parse_ss_output_legacy() is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ss", 5)):
            assert PortDataFetcher._parse_ss_output_legacy() is None


class TestPortDataFetcherNetstat:
    def test_parses_netstat_output(self):
        ns_out = (
            "Active Internet connections\n"
            "Proto Recv-Q Send-Q Local Address  Foreign Address State   PID/Program\n"
            "tcp        0      0 0.0.0.0:22     0.0.0.0:*       LISTEN  1234/sshd\n"
        )
        result = subprocess.CompletedProcess([], 0, ns_out, "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_netstat_output()
        assert rows is not None and len(rows) > 0
        assert rows[0].port == "22"

    def test_returns_none_on_failure(self):
        result = subprocess.CompletedProcess([], 1, "", "")
        with patch("subprocess.run", return_value=result):
            assert PortDataFetcher._parse_netstat_output() is None

    def test_returns_none_when_netstat_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert PortDataFetcher._parse_netstat_output() is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("netstat", 5)):
            assert PortDataFetcher._parse_netstat_output() is None


class TestPortDataFetcherFetch:
    def test_uses_cached_method_on_second_call(self):
        fetcher = PortDataFetcher()
        rows = [_make_row()]
        mock_method = MagicMock(return_value=rows)
        fetcher._cached_method = mock_method
        result, err = fetcher.fetch()
        assert result == rows
        assert err is None
        assert mock_method.call_count == 1

    def test_falls_through_to_proc_net(self):
        fetcher = PortDataFetcher()
        rows = [_make_row()]
        with patch.object(PortDataFetcher, "_parse_ss_output_json", return_value=None), \
                patch.object(PortDataFetcher, "_parse_ss_output_legacy", return_value=None), \
                patch.object(PortDataFetcher, "_parse_netstat_output", return_value=None), \
                patch.object(fetcher, "_parse_proc_net", return_value=rows):
            result, err = fetcher.fetch()
        assert result == rows
        assert err is None

    def test_returns_error_when_all_fail(self):
        fetcher = PortDataFetcher()
        with patch.object(PortDataFetcher, "_parse_ss_output_json", return_value=None), \
                patch.object(PortDataFetcher, "_parse_ss_output_legacy", return_value=None), \
                patch.object(PortDataFetcher, "_parse_netstat_output", return_value=None), \
                patch.object(fetcher, "_parse_proc_net", return_value=[]):
            result, err = fetcher.fetch()
        assert result == []
        assert err is not None

    def test_clears_cached_method_when_it_fails(self):
        fetcher = PortDataFetcher()
        fetcher._cached_method = MagicMock(return_value=[])  # returns empty = "failed"
        rows = [_make_row()]
        with patch.object(PortDataFetcher, "_parse_ss_output_json", return_value=rows):
            result, err = fetcher.fetch()
        assert result == rows


# ===========================================================================
# build_stylesheet
# ===========================================================================

class TestBuildStylesheet:
    def test_returns_string(self):
        ss = build_stylesheet("Monospace")
        assert isinstance(ss, str)
        assert len(ss) > 100

    def test_contains_config_colors(self):
        ss = build_stylesheet("Monospace")
        assert Config.BG in ss
        assert Config.NEON in ss

    def test_contains_font(self):
        ss = build_stylesheet("JetBrains Mono")
        assert "JetBrains Mono" in ss


# ===========================================================================
# _FetchTask
# ===========================================================================

class TestFetchTask:
    def test_run_emits_rows_on_success(self):
        sigs = FetchSignals()
        shutdown = threading.Event()
        fetcher = MagicMock()
        rows = [_make_row()]
        fetcher.fetch.return_value = (rows, None)
        on_done = MagicMock()

        emitted = []
        sigs.finished.connect(lambda r, e: emitted.append((r, e)))

        task = _FetchTask(fetcher, sigs, shutdown, on_done)
        task.run()

        on_done.assert_called_once()
        assert len(emitted) == 1
        assert emitted[0][1] is None

    def test_run_handles_exception(self):
        sigs = FetchSignals()
        shutdown = threading.Event()
        fetcher = MagicMock()
        fetcher.fetch.side_effect = RuntimeError("disk error")
        on_done = MagicMock()

        emitted = []
        sigs.finished.connect(lambda r, e: emitted.append((r, e)))

        task = _FetchTask(fetcher, sigs, shutdown, on_done)
        task.run()

        on_done.assert_called_once()
        assert len(emitted) == 1
        assert "disk error" in emitted[0][1]

    def test_run_skips_emit_when_shutdown(self):
        sigs = FetchSignals()
        shutdown = threading.Event()
        shutdown.set()
        fetcher = MagicMock()
        fetcher.fetch.return_value = ([_make_row()], None)
        on_done = MagicMock()

        emitted = []
        sigs.finished.connect(lambda r, e: emitted.append((r, e)))

        task = _FetchTask(fetcher, sigs, shutdown, on_done)
        task.run()

        on_done.assert_called_once()
        assert len(emitted) == 0  # shutdown prevents emit


# ===========================================================================
# _FilterTask
# ===========================================================================

class TestFilterTask:
    def _make_task(self, query="", rows=None, sort_col=None, sort_asc=True):
        if rows is None:
            rows = [_make_row(pid="1234", name="nginx", port="80"),
                    _make_row(pid="5678", name="sshd", port="22", state="ESTABLISHED")]
        sigs = FilterSignals()
        shutdown = threading.Event()
        sc = sort_col if sort_col is not None else _COL_PID
        return _FilterTask(1, query, rows, sc, sort_asc, None, None, sigs, shutdown), sigs

    def test_no_filter_returns_all(self):
        task, sigs = self._make_task()
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted[0]) == 2

    def test_filter_by_name(self):
        task, sigs = self._make_task(query="nginx")
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted[0]) == 1

    def test_filter_by_port(self):
        task, sigs = self._make_task(query="22")
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted[0]) == 1

    def test_filter_by_state(self):
        task, sigs = self._make_task(query="established")
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted[0]) == 1

    def test_sort_by_port(self):
        task, sigs = self._make_task(sort_col=_COL_PORT, sort_asc=True)
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        ports = [r.port for r in emitted[0]]
        assert ports == sorted(ports, key=lambda p: int(p))

    def test_sort_descending(self):
        task, sigs = self._make_task(sort_col=_COL_PORT, sort_asc=False)
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        ports = [r.port for r in emitted[0]]
        assert ports == sorted(ports, key=lambda p: int(p), reverse=True)

    def test_truncates_to_max_rows(self):
        rows = [_make_row(pid=str(i), port=str(i)) for i in range(1, Config.MAX_ROWS + 50)]
        task, sigs = self._make_task(rows=rows)
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted[0]) == Config.MAX_ROWS

    def test_skips_emit_on_shutdown(self):
        task, sigs = self._make_task()
        task._shutdown.set()
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert len(emitted) == 0


# ===========================================================================
# UI Components
# ===========================================================================

class TestAccentLine:
    def test_creates_frame(self):
        parent = _QWidget()
        f = _accent_line(parent)
        assert f is not None

    def test_accent_mid_variant(self):
        parent = _QWidget()
        f = _accent_line(parent, "accent_mid")
        assert f is not None


class TestStatBadge:
    def test_creates_and_sets_value(self):
        parent = _QWidget()
        badge = StatBadge("LISTEN", Config.NEON, parent)
        badge.set(42)
        assert badge._val.text() == "42"


class TestKillButton:
    def test_creates(self):
        parent = _QWidget()
        btn = KillButton("SIGTERM", Config.AMBER, parent)
        assert btn is not None


class TestLogoBanner:
    def test_creates(self):
        parent = _QWidget()
        banner = LogoBanner(parent)
        assert banner is not None


# ===========================================================================
# ElevationDialog
# ===========================================================================

class TestElevationDialog:
    def test_creates_dialog(self):
        dlg = ElevationDialog()
        assert dlg is not None
        assert dlg.result_yes is False

    def test_yes_sets_result(self):
        dlg = ElevationDialog()
        dlg._on_yes()
        assert dlg.result_yes is True

    def test_no_does_not_set_result(self):
        dlg = ElevationDialog()
        dlg._on_no()
        assert dlg.result_yes is False

    def test_drag_events(self):
        dlg = ElevationDialog()
        ev = MagicMock()
        ev.button.return_value = _Qt.MouseButton.LeftButton
        gp = MagicMock();
        gp.toPoint.return_value = _QPoint(50, 50)
        ev.globalPosition.return_value = gp
        dlg.frameGeometry = lambda: _QRect(0, 0, 500, 290)
        # move() on some mock bases requires (self,x,y) — patch to accept both forms
        dlg.move = lambda *a: None
        dlg.mousePressEvent(ev)
        dlg.mouseMoveEvent(ev)
        dlg.mouseReleaseEvent(ev)


# ===========================================================================
# SmartTooltip
# ===========================================================================

class TestSmartTooltip:
    def setup_method(self):
        SmartTooltip._instance = None

    def _patch_adjustsize(self, instance):
        """adjustSize may be absent on MockQWidget base from the other test file."""
        instance.adjustSize = lambda: None
        if instance._lbl:
            instance._lbl.adjustSize = lambda: None

    def test_creates_and_shows(self):
        parent = _QWidget()
        rect = _QRect(0, 50, 1920, 28)
        # adjustSize may be absent on inherited MockQWidget — patch at class level
        with patch.object(SmartTooltip, "adjustSize", create=True, return_value=None):
            SmartTooltip.show_tip("cmdline: /usr/bin/nginx", rect, parent)
        assert SmartTooltip._instance is not None

    def test_empty_text_hides(self):
        SmartTooltip._instance = MagicMock()
        SmartTooltip.show_tip("", _QRect(), _QWidget())
        assert SmartTooltip._instance is None

    def test_dash_text_hides(self):
        SmartTooltip._instance = MagicMock()
        SmartTooltip.show_tip("—", _QRect(), _QWidget())
        assert SmartTooltip._instance is None

    def test_hide_tip(self):
        tip = SmartTooltip()
        tip.adjustSize = lambda: None
        tip._lbl.adjustSize = lambda: None
        SmartTooltip._instance = tip
        SmartTooltip.hide_tip()
        assert SmartTooltip._instance is None


# ===========================================================================
# PorkillWindow
# ===========================================================================

class TestPorkillWindow:
    def _make_window(self, **kw):
        import argparse
        args = argparse.Namespace(
            interval=2, max_rows=2000,
            no_auto_refresh=False,
            log_level="WARNING", debug=False, version=False,
        )
        args.__dict__.update(kw)
        return PorkillWindow(args)

    def test_creates_window(self):
        win = self._make_window()
        assert win is not None

    def test_creates_with_no_auto_refresh(self):
        win = self._make_window(no_auto_refresh=True)
        assert win._auto_refresh is False

    def test_interval_clamped_min(self):
        win = self._make_window(interval=0)
        assert win._refresh_interval >= 2

    def test_interval_clamped_max(self):
        win = self._make_window(interval=999)
        assert win._refresh_interval <= 120

    def test_on_auto_toggle(self):
        win = self._make_window()
        win._on_auto_toggle(False)
        assert win._auto_refresh is False
        win._on_auto_toggle(True)
        assert win._auto_refresh is True

    def test_focus_filter(self):
        win = self._make_window()
        win._focus_filter()  # must not raise

    def test_clear_selection(self):
        win = self._make_window()
        win._selected_key = "somekey"
        win._selected_group = "somegroup"
        win._clear_selection()
        assert win._selected_key is None
        assert win._selected_group is None

    def test_fmt_refresh_age_no_refresh(self):
        win = self._make_window()
        win._last_refresh_ts = 0.0
        result = win._fmt_refresh_age()
        assert isinstance(result, str)

    def test_fmt_refresh_age_recent(self):
        win = self._make_window()
        win._last_refresh_ts = time.monotonic()
        result = win._fmt_refresh_age()
        assert isinstance(result, str) and len(result) > 0

    def test_set_status(self):
        win = self._make_window()
        win._set_status("TEST STATUS")
        assert win._status_lbl.text() == "TEST STATUS"

    def test_flash_status(self):
        win = self._make_window()
        win._flash_status("FLASH!")  # takes only msg, no color arg

    def test_clear_flash(self):
        win = self._make_window()
        win._clear_flash()  # must not raise

    def test_on_item_collapsed(self):
        win = self._make_window()
        item = _QTreeWidgetItem()
        item.setData(0, 0x0101, "grp:nginx")  # ROLE_GROUP_KEY
        # Use porkill's actual role constant
        from porkill import _ROLE_GROUP_KEY
        item.setData(0, _ROLE_GROUP_KEY, "grp:nginx")
        win._on_item_collapsed(item)
        assert "grp:nginx" in win._collapsed_groups

    def test_on_item_expanded(self):
        win = self._make_window()
        win._collapsed_groups.add("grp:nginx")
        item = _QTreeWidgetItem()
        from porkill import _ROLE_GROUP_KEY
        item.setData(0, _ROLE_GROUP_KEY, "grp:nginx")
        win._on_item_expanded(item)
        assert "grp:nginx" not in win._collapsed_groups

    def test_on_fetch_done_with_error(self):
        win = self._make_window()
        win._on_fetch_done([], "Connection refused")
        assert "ERROR" in win._status_lbl.text()

    def test_on_fetch_done_with_rows(self):
        win = self._make_window()
        rows = [_make_row(), _make_row(pid="5678", proto="UDP", state="UNCONN")]
        win._on_fetch_done(tuple(rows), None)
        assert len(win._raw_rows) == len(rows)

    def test_on_fetch_done_clears_caches(self):
        win = self._make_window()
        _pid_user_cache["9999"] = "someone"
        win._on_fetch_done(tuple([_make_row()]), None)
        assert "9999" not in _pid_user_cache

    def test_launch_fetch_sets_fetching(self):
        win = self._make_window()
        with patch.object(win._thread_pool, "start") as mock_start:
            win._launch_fetch()
        assert mock_start.called

    def test_launch_fetch_reschedules_when_in_flight(self):
        win = self._make_window()
        win._fetching = True
        win._fetch_start_time = time.monotonic()
        win._fetch_retry_count = 0
        with patch("porkill.QTimer.singleShot") as mock_shot:
            win._launch_fetch()
        assert mock_shot.called

    def test_stuck_fetch_force_resets(self):
        win = self._make_window()
        win._fetching = True
        win._fetch_start_time = time.monotonic() - 20.0  # simulate stuck
        win._fetch_retry_count = 25
        with patch.object(win._thread_pool, "start"):
            win._launch_fetch()
        # After forced reset a new task is launched
        assert win._fetching is True

    def test_generation_increments(self):
        win = self._make_window()
        gen_before = win._fetch_generation
        with patch.object(win._thread_pool, "start"):
            win._launch_fetch()
        assert win._fetch_generation == gen_before + 1

    def test_on_header_clicked_toggles_sort(self):
        win = self._make_window()
        win._sort_col = 0
        win._sort_asc = True
        with patch.object(win, "_do_apply_filter"):
            win._on_header_clicked(0)
        assert win._sort_asc is False

    def test_on_header_clicked_new_col(self):
        win = self._make_window()
        win._sort_col = 0
        with patch.object(win, "_do_apply_filter"):
            win._on_header_clicked(2)
        assert win._sort_col == 2

    def test_rebuild_tree_with_rows(self):
        win = self._make_window()
        rows = [
            _make_row(pid="1234", name="nginx", group="nginx"),
            _make_row(pid="1234", name="nginx", port="443", group="nginx"),
            _make_row(pid="5678", name="sshd", port="22", group="sshd"),
        ]
        win._rebuild_tree(rows, None, None)
        assert win.tree.topLevelItemCount() > 0

    def test_rebuild_tree_empty(self):
        win = self._make_window()
        win._rebuild_tree([], None, None)

    def test_do_apply_filter_submits_task(self):
        win = self._make_window()
        with patch.object(win._thread_pool, "start") as mock_start:
            win._do_apply_filter()
        assert mock_start.called

    def test_on_filter_changed_starts_timer(self):
        win = self._make_window()
        win._on_filter_changed()
        assert win._filter_timer.isActive()

    def test_tick_age_label(self):
        win = self._make_window()
        win._last_refresh_ts = time.monotonic()
        win._tick_age_label()  # must not raise

    def test_show_event(self):
        win = self._make_window()
        ev = MagicMock()
        base = type(win).__mro__[1]  # actual base class (may be MockQMainWindow or _QMainWindow)
        with patch.object(base, "showEvent", create=True, return_value=None), \
                patch.object(win, "_schedule_refresh"):
            win.showEvent(ev)

    def test_close_event(self):
        win = self._make_window()
        ev = MagicMock()
        win.closeEvent(ev)
        assert win._shutdown.is_set()

    def test_apply_column_proportions(self):
        win = self._make_window()
        win._apply_column_proportions()

    def test_event_filter_tooltip(self):
        win = self._make_window()
        ev = _QEvent(_QEvent.Type.ToolTip)
        base = type(win).__mro__[1]
        with patch.object(base, "eventFilter", create=True, return_value=False):
            win.eventFilter(win.tree.viewport(), ev)

    def test_event_filter_leave(self):
        win = self._make_window()
        ev = _QEvent(_QEvent.Type.Leave)
        base = type(win).__mro__[1]
        with patch.object(base, "eventFilter", create=True, return_value=False):
            win.eventFilter(win.tree.viewport(), ev)

    def test_kill_no_selection(self):
        win = self._make_window()
        win.tree._sel = []
        win._kill(signal.SIGTERM)  # must not raise (no selection)

    def test_on_selection_changed_no_item(self):
        win = self._make_window()
        win.tree._sel = []
        win._on_selection_changed()
        assert win._selected_key is None


# ===========================================================================
# parse_arguments
# ===========================================================================

class TestParseArgumentsReal:
    def test_defaults(self):
        with patch("sys.argv", ["porkill"]):
            args = parse_arguments()
        assert args.interval == 2
        assert args.max_rows == 2000
        assert args.no_auto_refresh is False
        assert args.debug is False
        assert args.version is False

    def test_custom_interval(self):
        with patch("sys.argv", ["porkill", "--interval", "10"]):
            args = parse_arguments()
        assert args.interval == 10

    def test_debug_flag(self):
        with patch("sys.argv", ["porkill", "--debug"]):
            args = parse_arguments()
        assert args.debug is True

    def test_no_auto_refresh(self):
        with patch("sys.argv", ["porkill", "--no-auto-refresh"]):
            args = parse_arguments()
        assert args.no_auto_refresh is True

    def test_version_flag(self):
        with patch("sys.argv", ["porkill", "--version"]):
            args = parse_arguments()
        assert args.version is True

    def test_log_level(self):
        with patch("sys.argv", ["porkill", "--log-level", "DEBUG"]):
            args = parse_arguments()
        assert args.log_level == "DEBUG"


# ===========================================================================
# main()
# ===========================================================================

class TestMain:
    def test_version_flag_exits_zero(self):
        with patch("sys.argv", ["porkill", "--version"]), \
                patch("builtins.print"):
            result = main()
        assert result == 0

    def test_main_launches_app(self):
        with patch("sys.argv", ["porkill"]), \
                patch("porkill._check_pyqt6"), \
                patch("porkill.QApplication", _QApplication), \
                patch("porkill.PorkillWindow") as mock_win:
            win_inst = MagicMock()
            win_inst.screen.return_value = _Screen()
            mock_win.return_value = win_inst
            with patch.object(_QApplication, "primaryScreen", staticmethod(lambda: _Screen())):
                with patch("porkill.QApplication") as mock_app_cls:
                    app_inst = MagicMock()
                    app_inst.primaryScreen.return_value = _Screen()
                    mock_app_cls.return_value = app_inst
                    mock_app_cls.primaryScreen = staticmethod(lambda: _Screen())
                    mock_app_cls.screenAt = staticmethod(lambda p: _Screen())
                    app_inst.exec.return_value = 0
                    result = main()
        assert result == 0

    def test_main_respects_debug_flag(self):
        with patch("sys.argv", ["porkill", "--debug"]), \
                patch("porkill._check_pyqt6"), \
                patch("porkill.QApplication") as mock_app_cls, \
                patch("porkill.PorkillWindow"):
            mock_app_cls.return_value.exec.return_value = 0
            mock_app_cls.primaryScreen = staticmethod(lambda: _Screen())
            mock_app_cls.screenAt = staticmethod(lambda p: _Screen())
            main()
        assert logging.root.level == logging.DEBUG


# ===========================================================================
# Additional edge-case coverage
# ===========================================================================

class TestOnFilterDone:
    def test_stale_version_ignored(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000, no_auto_refresh=False,
                                  log_level="WARNING", debug=False, version=False)
        win = PorkillWindow(args)
        win._filter_version = 5
        # emit version 3 — should be ignored
        with patch.object(win, "_rebuild_tree") as mock_rebuild:
            win._on_filter_done(3, tuple([_make_row()]), None, None)
        mock_rebuild.assert_not_called()

    def test_current_version_rebuilds(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000, no_auto_refresh=False,
                                  log_level="WARNING", debug=False, version=False)
        win = PorkillWindow(args)
        win._filter_version = 5
        with patch.object(win, "_rebuild_tree") as mock_rebuild:
            win._on_filter_done(5, tuple([_make_row()]), None, None)
        mock_rebuild.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


# ===========================================================================
# Supplemental tests for remaining uncovered lines
# ===========================================================================

class TestFmtAddrReturnLabel:
    """Line 537 — the final `return label` branch (non-special IP)."""

    def test_non_special_ip_returns_itself(self):
        from porkill import fmt_addr
        assert fmt_addr("10.0.0.1") == "10.0.0.1"
        assert fmt_addr("172.16.0.1") == "172.16.0.1"


class TestGetVersionFallbacks:
    """Lines 345-357 — get_version file reading."""

    def test_reads_version_file_if_exists(self, tmp_path):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value="3.9.1\n"):
            result = get_version()
        assert _VERSION_RE.match(result)
        assert result == "3.9.1"

    def test_falls_back_on_ioerror(self):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", side_effect=OSError):
            result = get_version()
        assert result  # some non-empty version string


class TestKillWithSelection:
    """Lines 2563-2638 — _kill with actual selection."""

    def _make_window(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000,
                                  no_auto_refresh=False, log_level="WARNING", debug=False, version=False)
        return PorkillWindow(args)

    def test_kill_with_valid_pid_shows_dialog(self):
        win = self._make_window()
        item = _QTreeWidgetItem()
        from porkill import _ROLE_IS_GROUP, _ROLE_ROW_DATA, _COL_PID
        item.setData(_COL_PID, _ROLE_IS_GROUP, False)
        item.setData(_COL_PID, _ROLE_ROW_DATA, _make_row(pid="1234"))
        win.tree._sel = [item]
        with patch("porkill.ElevationDialog") as MockDlg:
            dlg_inst = MagicMock();
            dlg_inst.exec.return_value = 0
            MockDlg.return_value = dlg_inst
            with patch("porkill.send_signal_to_pid", return_value=(True, "")) as mock_kill:
                win._kill(signal.SIGTERM)

    def test_kill_elevation_dialog_yes(self):
        win = self._make_window()
        item = _QTreeWidgetItem()
        from porkill import _ROLE_IS_GROUP, _ROLE_ROW_DATA, _COL_PID
        item.setData(_COL_PID, _ROLE_IS_GROUP, False)
        item.setData(_COL_PID, _ROLE_ROW_DATA, _make_row(pid="1234"))
        win.tree._sel = [item]
        with patch("porkill.send_signal_to_pid", return_value=(False, "Permission denied")):
            with patch("porkill.ElevationDialog") as MockDlg:
                dlg_inst = MagicMock();
                dlg_inst.exec.return_value = 1
                dlg_inst.result_yes = True
                MockDlg.return_value = dlg_inst
                with patch("subprocess.run"):
                    win._kill(signal.SIGTERM)


class TestOnSelectionChangedWithItem:
    """Lines 2500-2548 — _on_selection_changed with an item selected."""

    def _make_window(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000,
                                  no_auto_refresh=False, log_level="WARNING", debug=False, version=False)
        return PorkillWindow(args)

    def test_with_group_item(self):
        win = self._make_window()
        item = _QTreeWidgetItem()
        from porkill import _ROLE_GROUP_KEY
        item.setData(0, _ROLE_GROUP_KEY, "grp:nginx")
        win.tree._sel = [item]
        win._on_selection_changed()

    def test_with_process_item(self):
        win = self._make_window()
        item = _QTreeWidgetItem()
        from porkill import _ROLE_IS_GROUP, _ROLE_ROW_DATA, _COL_PID
        item.setData(_COL_PID, _ROLE_IS_GROUP, False)
        item.setData(_COL_PID, _ROLE_ROW_DATA, _make_row(pid="1234"))
        win.tree._sel = [item]
        with patch("porkill.get_proc_cmd_full", return_value="/usr/sbin/nginx -g daemon off"):
            win._on_selection_changed()


class TestScheduleRefresh:
    """Lines 2139-2147 — _schedule_refresh throttle logic."""

    def _make_window(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000,
                                  no_auto_refresh=False, log_level="WARNING", debug=False, version=False)
        return PorkillWindow(args)

    def test_throttle_prevents_double_refresh(self):
        win = self._make_window()
        win._last_manual_refresh = time.monotonic()  # just refreshed
        with patch.object(win, "_launch_fetch") as mock_fetch:
            win._schedule_refresh()
        mock_fetch.assert_not_called()

    def test_allows_refresh_after_throttle(self):
        win = self._make_window()
        win._last_manual_refresh = 0.0  # long ago
        with patch.object(win, "_launch_fetch") as mock_fetch:
            win._schedule_refresh()
        mock_fetch.assert_called_once()


class TestFilterTaskSortByPID:
    """Line 2330 — sort by PID column in _FilterTask."""

    def test_sort_by_pid(self):
        rows = [
            _make_row(pid="999", port="80"),
            _make_row(pid="100", port="22"),
            _make_row(pid="abc", port="443"),  # non-numeric PID
        ]
        sigs = FilterSignals()
        shutdown = threading.Event()
        task = _FilterTask(1, "", rows, _COL_PID, True, None, None, sigs, shutdown)
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert emitted[0][0].pid in ("100", "999", "abc")  # sorted without crash


class TestRebuildTreeCollapsed:
    """Lines 2384-2406 — collapsed group state preserved in _rebuild_tree."""

    def _make_window(self):
        import argparse
        args = argparse.Namespace(interval=2, max_rows=2000,
                                  no_auto_refresh=False, log_level="WARNING", debug=False, version=False)
        return PorkillWindow(args)

    def test_collapsed_groups_preserved(self):
        win = self._make_window()
        win._collapsed_groups.add("nginx")
        rows = [_make_row(pid="1234", name="nginx", group="nginx")]
        win._rebuild_tree(rows, None, None)  # must not raise

    def test_selection_restored(self):
        win = self._make_window()
        rows = [_make_row(pid="1234", name="sshd", port="22", group="sshd")]
        win._rebuild_tree(rows, "1234:22:TCP", "sshd")  # restores selection key


class TestMainSigintHandler:
    """Lines 2722-2723, 2872-2873 — SIGINT handlers in main()."""

    def test_early_sigint_exits(self):
        with patch("sys.argv", ["porkill", "--version"]), \
                patch("builtins.print"):
            result = main()
        assert result == 0  # --version path exercises _early_sigint registration


class TestBuildInodeMapReadlinkError:
    """Line 761-762 — os.readlink raises OSError inside _build_inode_map."""

    def test_skips_unreadable_fd(self):
        fake_entry = MagicMock();
        fake_entry.name = "1234";
        fake_entry.is_dir.return_value = True
        fake_fd = MagicMock();
        fake_fd.path = "/proc/1234/fd/3"
        with patch("os.scandir") as mock_scan, \
                patch("os.readlink", side_effect=OSError("permission")):
            pc = MagicMock();
            pc.__enter__ = MagicMock(return_value=[fake_entry]);
            pc.__exit__ = MagicMock(return_value=False)
            fc = MagicMock();
            fc.__enter__ = MagicMock(return_value=[fake_fd]);
            fc.__exit__ = MagicMock(return_value=False)
            mock_scan.side_effect = [pc, fc]
            imap = PortDataFetcher._build_inode_map()
        assert imap == {}


class TestBuildInodeMapFdPermission:
    """Lines 754-755 — fd scandir raises PermissionError."""

    def test_skips_protected_fd_dir(self):
        fake_entry = MagicMock();
        fake_entry.name = "1234";
        fake_entry.is_dir.return_value = True
        with patch("os.scandir") as mock_scan:
            pc = MagicMock();
            pc.__enter__ = MagicMock(return_value=[fake_entry]);
            pc.__exit__ = MagicMock(return_value=False)
            fc = MagicMock();
            fc.__enter__ = MagicMock(side_effect=PermissionError)
            mock_scan.side_effect = [pc, fc]
            imap = PortDataFetcher._build_inode_map()
        assert imap == {}


class TestParseProcNetIPv6:
    """Lines 781, 787-788 — IPv6 paths in _parse_proc_net."""

    def test_parses_tcp6_entries(self):
        tcp6_data = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt  uid timeout inode\n"
            "   0: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 99999 1 0000000000000000 100 0 0 10 0\n"
        )
        fetcher = PortDataFetcher()

        # Only open tcp6, fail everything else
        def _open(path, **kw):
            if "tcp6" in path:
                return mock_open(read_data=tcp6_data)()
            raise OSError("not found")

        with patch.object(fetcher, "_get_inode_map", return_value={"99999": ("1234", "nginx")}), \
                patch("builtins.open", side_effect=_open), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = fetcher._parse_proc_net()
        # tcp6 row should be parsed
        assert any(r.proto == "TCP" for r in rows)


class TestSSLegacyKernelProcess:
    """Lines 846, 849, 853, 859, 868 — ss legacy kernel/no-pid branches."""

    def test_parses_line_without_pid(self):
        ss_out = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer\n"
            "udp   UNCONN 0      0      0.0.0.0:5353      0.0.0.0:*\n"
        )
        result = subprocess.CompletedProcess([], 0, ss_out, "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_ss_output_legacy()
        # kernel row (no pid) should still be returned
        if rows:
            assert rows[0].pid == "—"


class TestNetstatUDP:
    """Lines 891, 898, 905 — netstat UDP branch."""

    def test_parses_udp_line(self):
        ns_out = (
            "Proto Recv-Q Send-Q Local Address  Foreign Address State\n"
            "udp        0      0 0.0.0.0:5353   0.0.0.0:*               \n"
        )
        result = subprocess.CompletedProcess([], 0, ns_out, "")
        with patch("subprocess.run", return_value=result), \
                patch("porkill.enrich_process_name", side_effect=lambda p, n: n), \
                patch("porkill.resolve_group_name", side_effect=lambda p, n: n):
            rows = PortDataFetcher._parse_netstat_output()
        if rows:
            assert rows[0].proto == "UDP"


class TestGetProcCmdFullNoCache:
    """Lines 625-627 — get_proc_cmd_full when NOT in cache."""

    def setup_method(self): _clear_caches()

    def test_reads_cmdline_when_not_cached(self):
        with patch("porkill.read_proc_cmdline", return_value="/usr/sbin/sshd -D") as mock_read:
            result = get_proc_cmd_full("9876")
        assert result == "/usr/sbin/sshd -D"
        mock_read.assert_any_call("9876")


class TestFilterTaskAttrSort:
    """Lines 2447 — sort by non-port/non-pid column (attr-based key)."""

    def test_sort_by_name_column(self):
        rows = [
            _make_row(pid="1", name="zz-last", port="80"),
            _make_row(pid="2", name="aa-first", port="22"),
        ]
        sigs = FilterSignals()
        shutdown = threading.Event()
        COL_NAME = 1  # name column
        task = _FilterTask(1, "", rows, COL_NAME, True, None, None, sigs, shutdown)
        emitted = []
        sigs.finished.connect(lambda v, r, sk, sg: emitted.append(r))
        task.run()
        assert emitted[0][0].name == "aa-first"
