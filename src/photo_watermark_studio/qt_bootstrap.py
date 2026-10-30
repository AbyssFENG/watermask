# -*- coding: utf-8 -*-
"""让 Qt 使用 Windows 自带的 ICU，而不是环境里另一份不兼容的 icuuc.dll。"""
from __future__ import annotations

import sys


def ensure_qt_dlls() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    import os
    from pathlib import Path

    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    icu = Path(system_root) / "System32" / "icuuc.dll"
    if not icu.is_file():
        return
    try:
        # Qt 6.10+ 需要不带版本后缀的 ucnv_* 符号。Anaconda 等环境里的
        # icuuc.dll 只导出 ucnv_open_78 这类符号，必须先占用这个 DLL 名称。
        ctypes.WinDLL(str(icu))
    except OSError:
        return
