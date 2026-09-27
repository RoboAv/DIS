"""Сочетания клавиш на латинской и русской раскладке.

Windows Tk при русской раскладке не отдаёт ни «f», ни Cyrillic_a: байт
из CP1251 он показывает как латинский keysym (а → agrave, р → eth).
Код клавиши при этом часто остаётся виртуальным кодом физической кнопки.
"""

from __future__ import annotations

import ctypes
import sys

# ЙЦУКЕН → QWERTY, та же физическая клавиша.
_ROWS = (
    ("йцукенгшщзхъ", "qwertyuiop[]"),
    ("фывапролджэ", "asdfghjkl;'"),
    ("ячсмитьбю", "zxcvbnm,."),
    ("ё", "`"),
)

_KEYSYMS = {
    "а": "Cyrillic_a", "б": "Cyrillic_be", "в": "Cyrillic_ve",
    "г": "Cyrillic_ghe", "д": "Cyrillic_de", "е": "Cyrillic_ie",
    "ё": "Cyrillic_io", "ж": "Cyrillic_zhe", "з": "Cyrillic_ze",
    "и": "Cyrillic_i", "й": "Cyrillic_shorti", "к": "Cyrillic_ka",
    "л": "Cyrillic_el", "м": "Cyrillic_em", "н": "Cyrillic_en",
    "о": "Cyrillic_o", "п": "Cyrillic_pe", "р": "Cyrillic_er",
    "с": "Cyrillic_es", "т": "Cyrillic_te", "у": "Cyrillic_u",
    "ф": "Cyrillic_ef", "х": "Cyrillic_ha", "ц": "Cyrillic_tse",
    "ч": "Cyrillic_che", "ш": "Cyrillic_sha", "щ": "Cyrillic_shcha",
    "ъ": "Cyrillic_hardsign", "ы": "Cyrillic_yeru", "ь": "Cyrillic_softsign",
    "э": "Cyrillic_e", "ю": "Cyrillic_yu", "я": "Cyrillic_ya",
}

# Имена keysym, которыми Windows Tk маскирует русские буквы.
_LATIN1_NAMES = {
    "eacute": "q", "odiaeresis": "w", "oacute": "e", "ecircumflex": "r",
    "aring": "t", "iacute": "y", "atilde": "u", "oslash": "i",
    "ugrave": "o", "ccedilla": "p", "otilde": "[", "uacute": "]",
    "ocircumflex": "a", "ucircumflex": "s", "acircumflex": "d", "agrave": "f",
    "idiaeresis": "g", "eth": "h", "icircumflex": "j", "ediaeresis": "k",
    "adiaeresis": "l", "ae": ";", "yacute": "'",
    "ydiaeresis": "z", "division": "x", "ntilde": "c", "igrave": "v",
    "egrave": "b", "ograve": "n", "udiaeresis": "m", "aacute": ",",
    "thorn": ".", "ssharp": "z",
}

_MODIFIERS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R",
    "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Super_L", "Super_R",
    "ISO_Level3_Shift",
}


def _cyrillic_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for ru_row, lat_row in _ROWS:
        for ru, lat in zip(ru_row, lat_row):
            out[ru] = lat
            out[ru.upper()] = lat
            sym = _KEYSYMS.get(ru)
            if not sym:
                continue
            out[sym] = lat
            tail = sym.split("_", 1)[1]
            out["Cyrillic_" + tail.upper()] = lat
    return out


_CYR = _cyrillic_map()


def layout_keysyms() -> list[str]:
    """Имена keysym русской раскладки в том виде, как их видит Windows Tk."""
    names: set[str] = set()
    for name in _LATIN1_NAMES:
        names.add(name)
        names.add(name[:1].upper() + name[1:])
    return sorted(names)


def _from_unicode(num: int) -> str | None:
    if 0x0400 <= num <= 0x04FF:
        return _CYR.get(chr(num).lower())
    return None


def _from_cp1251(num: int) -> str | None:
    if num in (0xA8, 0xB8):
        return "`"
    if not 0xC0 <= num <= 0xFF:
        return None
    try:
        char = bytes([num]).decode("cp1251")
    except UnicodeDecodeError:
        return None
    return _CYR.get(char.lower())


def _vk_key(code: int) -> str | None:
    if 65 <= code <= 90:
        return chr(code).lower()
    if 48 <= code <= 57:
        return chr(code)
    if code in (187, 107):
        return "="
    if code in (189, 109):
        return "-"
    return None


def latin_key(event) -> str | None:
    """Латинская буква, цифра, «=» или «-». Буква в нижнем регистре."""
    keysym = str(getattr(event, "keysym", "") or "")
    number = int(getattr(event, "keysym_num", 0) or 0)
    if len(keysym) == 1 and keysym.isascii() and keysym.isalpha():
        return keysym.lower()
    if len(keysym) == 1 and keysym.isdigit():
        return keysym
    mapped = _CYR.get(keysym)
    if mapped is None and len(keysym) == 1:
        mapped = _CYR.get(keysym.lower())
    if mapped:
        return mapped
    # Windows Tk не знает кириллические keysym: в событии «??», а номер —
    # код Unicode (а = 1072). Сам keycode при этом остаётся VK физической клавиши.
    mapped = _from_unicode(number)
    if mapped:
        return mapped
    char = str(getattr(event, "char", "") or "")
    if len(char) == 1 and ord(char) >= 32:
        mapped = _CYR.get(char.lower())
        if mapped:
            return mapped
    mapped = _from_cp1251(number)
    if mapped:
        return mapped
    mapped = _LATIN1_NAMES.get(keysym.lower())
    if mapped:
        return mapped
    if sys.platform == "win32":
        mapped = _vk_key(int(getattr(event, "keycode", 0) or 0))
        if mapped:
            return mapped
    if keysym in ("equal", "plus", "KP_Add"):
        return "="
    if keysym in ("minus", "KP_Subtract"):
        return "-"
    return None


def _key_down(vk: int) -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.GetKeyState(vk) & 0x8000)


def control_down(event) -> bool:
    state = int(getattr(event, "state", 0) or 0)
    return bool(state & 0x0004) or _key_down(0x11)


def shift_down(event) -> bool:
    state = int(getattr(event, "state", 0) or 0)
    if state & 0x0001 or _key_down(0x10):
        return True
    keysym = str(getattr(event, "keysym", "") or "")
    return len(keysym) == 1 and keysym.isascii() and keysym.isupper()


def alt_down(event) -> bool:
    """Только реально нажатый Alt, без бита NumLock."""
    if _key_down(0x12):
        return True
    if sys.platform == "win32":
        return False
    state = int(getattr(event, "state", 0) or 0)
    return bool(state & 0x0008 or state & 0x20000)


def is_modifier(event) -> bool:
    return str(getattr(event, "keysym", "") or "") in _MODIFIERS
