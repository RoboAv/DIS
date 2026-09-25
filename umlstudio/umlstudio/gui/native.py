"""Оформление системной части окна: заголовок с кнопками, рамка.

Заголовок окна рисует не Tk, а сама Windows, поэтому цвет задаётся через
DWM. На других системах и на старых сборках Windows вызовы просто ничего
не делают.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

# атрибуты DwmSetWindowAttribute
DARK_MODE = 20          # Windows 10 начиная со сборки 18985
DARK_MODE_LEGACY = 19   # более ранние сборки Windows 10
BORDER_COLOR = 34       # только Windows 11
CAPTION_COLOR = 35      # только Windows 11
CAPTION_TEXT_COLOR = 36  # только Windows 11

GA_ROOT = 2
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # размер, место, кадр
SWP_QUIET = 0x0004 | 0x0010                             # порядок и фокус
RDW_FLAGS = 0x0001 | 0x0100 | 0x0400  # стереть, обновить, вместе с рамкой

WINDOWS = sys.platform.startswith("win")


def _colorref(color: str) -> int:
    """Переводит #rrggbb в порядок байтов, принятый в Windows."""
    value = color.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (blue << 16) | (green << 8) | red


def _handle(window: tk.Misc) -> int:
    """Настоящее окно с заголовком, а не внутреннее окно Tk."""
    own = window.winfo_id()
    return ctypes.windll.user32.GetAncestor(own, GA_ROOT) or own


def _set(handle: int, attribute: int, value: ctypes.c_int) -> bool:
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(
        handle, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0


def apply_chrome(window: tk.Misc, dark: bool,
                 caption: str = "", text: str = "") -> bool:
    """Переключает заголовок и рамку окна на тёмное или светлое оформление."""
    if not WINDOWS:
        return False
    try:
        handle = _handle(window)
        flag = ctypes.c_int(1 if dark else 0)
        changed = (_set(handle, DARK_MODE, flag)
                   or _set(handle, DARK_MODE_LEGACY, flag))
        # точные цвета заголовка понимает только Windows 11
        if caption:
            _set(handle, CAPTION_COLOR, ctypes.c_int(_colorref(caption)))
            _set(handle, BORDER_COLOR, ctypes.c_int(_colorref(caption)))
        if text:
            _set(handle, CAPTION_TEXT_COLOR, ctypes.c_int(_colorref(text)))
        if changed and window.winfo_viewable():
            _repaint(handle)
        return changed
    except (OSError, AttributeError, ValueError, tk.TclError):
        return False


def _repaint(handle: int) -> None:
    """Просит Windows перерисовать заголовок уже открытого окна.

    Размер меняется только через системный вызов: если делать это через Tk,
    окно запомнит размер как заданный вручную и перестанет подстраиваться
    под содержимое.
    """
    user32 = ctypes.windll.user32
    user32.SetWindowPos(handle, 0, 0, 0, 0, 0, SWP_FLAGS)
    user32.RedrawWindow(handle, None, None, RDW_FLAGS)
    box = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(box)):
        return
    width = box.right - box.left
    height = box.bottom - box.top
    for extra in (1, 0):
        user32.SetWindowPos(handle, 0, box.left, box.top, width,
                            height + extra, SWP_QUIET)
