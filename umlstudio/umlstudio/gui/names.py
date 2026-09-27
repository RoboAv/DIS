"""Имена объектов в тексте: границы слова и все вхождения."""

from __future__ import annotations

import re

from ..theme import KIND_ALIASES, KIND_DEFAULTS

# Символы, которые могут стоять внутри имени, а не только по краям.
_BODY = "A-Za-z0-9_\u0400-\u04FF.:$"
_BODY_RE = re.compile(rf"[{_BODY}]")
BARE = re.compile(rf"[A-Za-z_\u0400-\u04FF][{_BODY}]*")
_TOKEN = re.compile(rf"[A-Za-z_\u0400-\u04FF][{_BODY}]*")
_QUOTED = re.compile(r'"([^"\n]*)"')

_EXTRA = {
    "shape", "link", "struct", "use", "package", "namespace", "group",
    "frame", "rectangle", "note", "end", "endlegend", "legend", "title",
    "caption", "footer", "set", "theme", "direction", "hide", "as",
    "extends", "of", "abstract", "static", "class", "interface", "enum",
    "solid", "dashed", "dotted", "bold", "hidden", "invisible",
    "up", "down", "left", "right", "top", "bottom", "same",
    "on", "off", "true", "false", "yes", "no", "endnote",
}

RESERVED = {word.lower() for word in (
    list(KIND_DEFAULTS) + list(KIND_ALIASES) + list(_EXTRA)
)}


def continues_name(char: str) -> bool:
    """Символ продолжает имя, а не отделяет его."""
    return len(char) == 1 and _BODY_RE.fullmatch(char) is not None


def is_bare(name: str) -> bool:
    return BARE.fullmatch(name) is not None


def is_reserved(name: str) -> bool:
    return name.lower() in RESERVED


def name_spans(text: str, name: str) -> list[tuple[int, int]]:
    """Все вхождения имени: отдельное слово, кавычки, ``$имя`` и ``${имя}``."""
    if not name:
        return []
    spans: set[tuple[int, int]] = set()
    bare = re.compile(
        rf"(?<![{_BODY}]){re.escape(name)}(?![{_BODY}])"
    )
    for match in bare.finditer(text):
        spans.add((match.start(), match.end()))
    if is_bare(name) and "$" not in name and "." not in name and ":" not in name:
        dollar = re.compile(
            rf"(?<![{_BODY}])\${re.escape(name)}(?![{_BODY}]|}})"
        )
        for match in dollar.finditer(text):
            spans.add((match.start() + 1, match.end()))
    return sorted(spans)


def index_at(text: str, offset: int) -> str:
    """Смещение в строке Python -> индекс текстового поля Tk (``строка.столбец``)."""
    line = text.count("\n", 0, offset) + 1
    newline = text.rfind("\n", 0, offset)
    column = offset if newline < 0 else offset - newline - 1
    return f"{line}.{column}"


def name_on_line(line: str, column: int) -> str | None:
    """Имя под курсором: целиком кавычки, иначе слово, на котором стоит столбец."""
    for match in _QUOTED.finditer(line):
        if match.start() < column <= match.end() and match.group(1):
            return match.group(1)
    inside = [m for m in _TOKEN.finditer(line) if m.start() < column <= m.end()]
    if inside:
        return inside[-1].group()
    at_start = [m for m in _TOKEN.finditer(line) if m.start() == column]
    if at_start:
        return at_start[0].group()
    return None


def name_from_selection(selected: str, before: str, after: str) -> str | None:
    """Имя из выделения. None, если выделен фрагмент слова или не имя."""
    if "\n" in selected:
        return None
    core = selected.strip()
    if not core:
        return None
    if len(core) >= 2 and core[0] == '"' and core[-1] == '"':
        inner = core[1:-1]
        if inner and '"' not in inner:
            return inner
        return None
    if core.startswith("${") and core.endswith("}") and len(core) > 3:
        inner = core[2:-1]
        return inner if is_bare(inner) else None
    if core.startswith("$") and is_bare(core[1:]):
        return core[1:]
    if is_bare(core):
        if continues_name(before[-1:]) or continues_name(after[:1]):
            return None
        return core
    if before == '"' and after == '"':
        return core
    return None


def plan_rename(text: str, old: str, new: str) -> tuple[list[tuple[int, int, str]], str]:
    """План замены. Второй элемент — текст ошибки, если заменить нельзя."""
    new = new.strip()
    if not new:
        return [], "Введите новое имя"
    if new == old:
        return [], ""
    if '"' in new or "\n" in new or "\r" in new:
        return [], "В имени не должно быть кавычек и переводов строки"
    if is_reserved(new):
        return [], f"«{new}» — служебное слово, таким именем назвать нельзя"
    spans = name_spans(text, old)
    if not spans:
        return [], f"Имя «{old}» в тексте не найдено"
    bare = is_bare(new)
    plan: list[tuple[int, int, str]] = []
    for start, end in spans:
        in_quotes = (
            start > 0 and end < len(text)
            and text[start - 1] == '"' and text[end:end + 1] == '"'
        )
        in_param = (
            (start >= 2 and text[start - 2:start] == "${")
            or (start >= 1 and text[start - 1] == "$" and not in_quotes)
        )
        if in_param and not bare:
            return [], (
                "Такое имя нельзя подставить в $параметр — "
                "запишите его одним словом"
            )
        value = new if bare or in_quotes else f'"{new}"'
        plan.append((start, end, value))
    return plan, ""


def places(count: int) -> str:
    """«1 вхождение», «2 вхождения», «5 вхождений»."""
    mod10, mod100 = count % 10, count % 100
    if 11 <= mod100 <= 14:
        word = "вхождений"
    elif mod10 == 1:
        word = "вхождение"
    elif 2 <= mod10 <= 4:
        word = "вхождения"
    else:
        word = "вхождений"
    return f"{count} {word}"
