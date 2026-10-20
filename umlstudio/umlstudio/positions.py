"""Правка текста диаграммы: положения блоков и узлов связей.

Координаты живут в исходнике. Без строк ``at`` / ``via`` раскладка
считается как обычно.
"""

from __future__ import annotations

import re

from .parser import AT_LINE, AT_SUFFIX, DECL, VIA_ATTR, VIA_LINE, has_lock

_BARE = re.compile(r"^[A-Za-z0-9_\u0400-\u04FF][A-Za-z0-9_\u0400-\u04FF.:$]*$")


def schema_text(text: str) -> str:
    """Текст без координат: по нему видно, изменилась ли сама схема."""
    kept: list[str] = []
    for line in text.splitlines():
        if AT_LINE.match(line.strip()) or VIA_LINE.match(line.strip()):
            continue
        cleaned = AT_SUFFIX.sub("", line)
        cleaned = VIA_ATTR.sub("", cleaned)
        cleaned = re.sub(r"\[\s*,", "[", cleaned)
        cleaned = re.sub(r",\s*,", ",", cleaned)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        cleaned = re.sub(r"\[\s*\]", "", cleaned)
        kept.append(cleaned)
    return "\n".join(kept)


def set_node_position(text: str, name: str, x: float, y: float,
                      locked: bool | None = None) -> str:
    """Записывает левый верх блока. ``locked=None`` не трогает блокировку."""
    lines, newline, ends = _split(text)
    xs, ys = _fmt_num(x), _fmt_num(y)
    found = False
    for index, line in enumerate(lines):
        if _at_names(line, name):
            flag = _flag(line, locked, at_line=True)
            lines[index] = f"at {_fmt_name(name)} {xs}, {ys}{flag}"
            found = True
        elif _declares(line, name) and AT_SUFFIX.search(line):
            flag = _flag(line, locked, at_line=False)
            lines[index] = AT_SUFFIX.sub(f"at {xs}, {ys}{flag}", line)
            found = True
    if not found:
        flag = " lock" if locked else ""
        lines = _insert(lines, f"at {_fmt_name(name)} {xs}, {ys}{flag}")
    return _join(lines, newline, ends)


def set_edge_waypoints(text: str, source: str, target: str, ordinal: int,
                       points: list[tuple[float, float]],
                       locked: bool | None = None,
                       src_line: int | None = None) -> str:
    """Записывает промежуточные узлы связи с номером ``ordinal`` (с 1)."""
    lines, newline, ends = _split(text)
    body = "; ".join(f"{_fmt_num(px)}, {_fmt_num(py)}" for px, py in points)
    found = None
    already = False
    for index, line in enumerate(lines):
        if not _via_names(line, source, target, ordinal):
            continue
        matched = VIA_LINE.match(line.strip())
        already = bool(matched and has_lock(matched.group("pts")))
        found = index
        break
    use_lock = already if locked is None else locked
    written = _via_text(source, target, ordinal, body, " lock" if use_lock else "")
    if found is None:
        lines = _insert(lines, written)
    else:
        lines[found] = written
    if src_line:
        lines = _strip_inline_via(lines, src_line)
    return _join(lines, newline, ends)


def clear_edge_waypoints(text: str, source: str, target: str, ordinal: int,
                         src_line: int | None = None) -> str:
    """Убирает ручные узлы связи: маршрут снова считает раскладка."""
    lines, newline, ends = _split(text)
    lines = [line for line in lines if not _via_names(line, source, target, ordinal)]
    if src_line:
        lines = _strip_inline_via(lines, src_line)
    return _join(lines, newline, ends)


def edge_ordinal(edges, index: int) -> int:
    """Номер связи среди рёбер с теми же концами, начиная с 1."""
    edge = edges[index]
    number = 0
    for cursor, item in enumerate(edges):
        if item.a == edge.a and item.b == edge.b:
            number += 1
            if cursor == index:
                return number
    return 1


def _via_text(source: str, target: str, ordinal: int, body: str, flag: str) -> str:
    return (f"via {_fmt_name(source)} {_fmt_name(target)} #{ordinal} "
            f"{body}{flag}")


def _flag(line: str, locked: bool | None, at_line: bool) -> str:
    if locked is None:
        if at_line:
            found = AT_LINE.match(line.strip())
            locked = bool(found and found.group("lock"))
        else:
            found = AT_SUFFIX.search(line)
            locked = bool(found and found.group("lock"))
    return " lock" if locked else ""


def _at_names(line: str, name: str) -> bool:
    found = AT_LINE.match(line.strip())
    return bool(found) and _unquote(found.group("name")) == name


def _via_names(line: str, source: str, target: str, ordinal: int) -> bool:
    found = VIA_LINE.match(line.strip())
    if not found:
        return False
    if _unquote(found.group("a")) != source or _unquote(found.group("b")) != target:
        return False
    number = int(found.group("n")) if found.group("n") else 1
    return number == ordinal


def _declares(line: str, name: str) -> bool:
    found = DECL.match(line.strip())
    if not found:
        return False
    name_tok, alias = found.group("name"), found.group("alias")
    if alias and str(name_tok).startswith('"'):
        resolved = _unquote(alias)
    else:
        resolved = _unquote(name_tok)
    return resolved == name


def _strip_inline_via(lines: list[str], src_line: int) -> list[str]:
    index = src_line - 1
    if index < 0 or index >= len(lines):
        return lines
    cleaned = VIA_ATTR.sub("", lines[index])
    cleaned = re.sub(r"\[\s*,", "[", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r",\s*\]", "]", cleaned)
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    lines[index] = cleaned
    return lines


def _fmt_name(name: str) -> str:
    if _BARE.fullmatch(name or ""):
        return name
    return '"' + (name or "").replace('"', "") + '"'


def _fmt_num(value: float) -> str:
    number = round(float(value), 1)
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}"


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _insert(lines: list[str], directive: str) -> list[str]:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip().lower() in ("@enduml", "@end"):
            lines.insert(index, directive)
            return lines
    lines.append(directive)
    return lines


def _split(text: str) -> tuple[list[str], str, bool]:
    newline = "\r\n" if "\r\n" in text else "\n"
    ends = text.endswith(("\n", "\r\n"))
    return text.splitlines(), newline, ends


def _join(lines: list[str], newline: str, ends: bool) -> str:
    body = newline.join(lines)
    if ends:
        body += newline
    return body
