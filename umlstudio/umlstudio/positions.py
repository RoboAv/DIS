"""Правка текста диаграммы: положения блоков и узлов связей.

Координаты живут в исходнике. Без строк ``at`` / ``via`` раскладка
считается как обычно.
"""

from __future__ import annotations

import re

from .parser import (
    AT_LINE,
    AT_SUFFIX,
    CONN,
    DECL,
    END_LINE,
    LABEL_LINE,
    PORTS_LINE,
    REL_HEAD,
    REL_TAIL,
    VIA_ATTR,
    VIA_LINE,
    has_lock,
)

_BARE = re.compile(r"^[A-Za-z0-9_\u0400-\u04FF][A-Za-z0-9_\u0400-\u04FF.:$]*$")


def schema_text(text: str) -> str:
    """Текст без координат: по нему видно, изменилась ли сама схема."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (AT_LINE.match(stripped) or VIA_LINE.match(stripped)
                or PORTS_LINE.match(stripped) or END_LINE.match(stripped)
                or LABEL_LINE.match(stripped)):
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


def set_node_ports(text: str, name: str,
                   points: list[tuple[float, float]]) -> str:
    """Записывает точки на границе блока. Пустой список строку убирает."""
    lines, newline, ends = _split(text)
    kept = [line for line in lines if not _port_names(line, name)]
    if points:
        body = "; ".join(f"{_fmt_num(px)}, {_fmt_num(py)}" for px, py in points)
        kept = _insert(kept, f"ports {_fmt_name(name)} {body}")
    return _join(kept, newline, ends)


def set_edge_end(text: str, kind: str, source: str, target: str, ordinal: int,
                 point: tuple[float, float]) -> str:
    """Записывает точку выхода (exit) или входа (entry) связи."""
    lines, newline, ends = _split(text)
    written = (f"{kind} {_fmt_name(source)} {_fmt_name(target)} #{ordinal} "
               f"{_fmt_num(point[0])}, {_fmt_num(point[1])}")
    found = None
    for index, line in enumerate(lines):
        if _end_names(line, kind, source, target, ordinal):
            found = index
            break
    if found is None:
        lines = _insert(lines, written)
    else:
        lines[found] = written
    return _join(lines, newline, ends)


def clear_edge_end(text: str, kind: str, source: str, target: str,
                   ordinal: int) -> str:
    """Убирает ручную точку входа или выхода: конец снова считает раскладка."""
    lines, newline, ends = _split(text)
    lines = [line for line in lines
             if not _end_names(line, kind, source, target, ordinal)]
    return _join(lines, newline, ends)


def set_edge_label_offset(text: str, source: str, target: str, ordinal: int,
                          offset: tuple[float, float] | None) -> str:
    """Записывает сдвиг подписи относительно связи. None строку убирает."""
    lines, newline, ends = _split(text)
    kept = [line for line in lines
            if not _label_names(line, source, target, ordinal)]
    if offset is not None:
        written = (f"labelat {_fmt_name(source)} {_fmt_name(target)} #{ordinal} "
                   f"{_fmt_num(offset[0])}, {_fmt_num(offset[1])}")
        kept = _insert(kept, written)
    return _join(kept, newline, ends)


def set_edge_geometry(text: str, source: str, target: str, ordinal: int,
                      waypoints: list[tuple[float, float]],
                      exit_at: tuple[float, float],
                      entry_at: tuple[float, float],
                      src_line: int | None = None) -> str:
    """Записывает ортогональный маршрут: узлы и точки входа и выхода."""
    if waypoints:
        text = set_edge_waypoints(
            text, source, target, ordinal, waypoints, src_line=src_line)
    else:
        text = clear_edge_waypoints(
            text, source, target, ordinal, src_line=src_line)
    text = set_edge_end(text, "exit", source, target, ordinal, exit_at)
    return set_edge_end(text, "entry", source, target, ordinal, entry_at)


def set_edge_straight(text: str, source: str, target: str, ordinal: int,
                      exit_at: tuple[float, float],
                      entry_at: tuple[float, float],
                      src_line: int | None = None) -> str:
    """Убирает промежуточные узлы: линия идёт от выхода сразу ко входу."""
    lines, newline, ends = _split(text)
    found = None
    already = False
    for index, line in enumerate(lines):
        if not _via_names(line, source, target, ordinal):
            continue
        matched = VIA_LINE.match(line.strip())
        already = bool(matched and has_lock(matched.group("pts")))
        found = index
        break
    written = _via_text(source, target, ordinal, "прямо", " lock" if already else "")
    if found is None:
        lines = _insert(lines, written)
    else:
        lines[found] = written
    if src_line:
        lines = _strip_inline_via(lines, src_line)
    text = _join(lines, newline, ends)
    text = set_edge_end(text, "exit", source, target, ordinal, exit_at)
    return set_edge_end(text, "entry", source, target, ordinal, entry_at)


def remove_object(text: str, name: str) -> str:
    """Удаляет объект, его блок и все связи и координаты, где он упомянут."""
    lines, newline, ends = _split(text)
    skip: set[int] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if _relation_ends(line) and name in _relation_ends(line):
            skip.add(index)
            index += 1
            continue
        if _declares(line, name) or line.strip() in (name, f'"{name}"'):
            end = _block_end(lines, index)
            skip.update(range(index, end))
            index = end
            continue
        if _directive_mentions(line, name):
            skip.add(index)
        index += 1
    kept = [line for index, line in enumerate(lines) if index not in skip]
    return _join(kept, newline, ends)


def remove_edge(text: str, source: str, target: str, ordinal: int,
                src_line: int | None = None) -> str:
    """Удаляет одну связь и её координаты. Более поздние номера той же пары сдвигаются."""
    lines, newline, ends = _split(text)
    seen = 0
    drop = None
    for index, line in enumerate(lines):
        if _relation_ends(line) != (source, target):
            continue
        seen += 1
        if seen == ordinal:
            drop = index
            break
    if drop is None and src_line and 1 <= src_line <= len(lines):
        drop = src_line - 1
    kept = []
    for index, line in enumerate(lines):
        if index == drop or _edge_directive(line, source, target, ordinal):
            continue
        kept.append(_renumber_directive(line, source, target, ordinal))
    return _join(kept, newline, ends)


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


def _port_names(line: str, name: str) -> bool:
    found = PORTS_LINE.match(line.strip())
    return bool(found) and _unquote(found.group("name")) == name


def _end_names(line: str, kind: str, source: str, target: str, ordinal: int) -> bool:
    found = END_LINE.match(line.strip())
    if not found:
        return False
    word = found.group("kind").lower()
    same = (kind == "exit" and word in ("exit", "выход")) or (
        kind == "entry" and word in ("entry", "вход"))
    if not same:
        return False
    if _unquote(found.group("a")) != source or _unquote(found.group("b")) != target:
        return False
    number = int(found.group("n")) if found.group("n") else 1
    return number == ordinal


def _label_names(line: str, source: str, target: str, ordinal: int) -> bool:
    found = LABEL_LINE.match(line.strip())
    if not found:
        return False
    if _unquote(found.group("a")) != source or _unquote(found.group("b")) != target:
        return False
    number = int(found.group("n")) if found.group("n") else 1
    return number == ordinal


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


def _relation_ends(line: str) -> tuple[str, str] | None:
    text = line.strip()
    head = REL_HEAD.match(text)
    if not head:
        return None
    rest = text[head.end():]
    conn = CONN.match(rest)
    if not conn:
        return None
    if not ((conn.group("l1") or "") + (conn.group("l2") or "")):
        return None
    tail = REL_TAIL.match(rest[conn.end():])
    if not tail:
        return None
    left, right = _unquote(head.group("left")), _unquote(tail.group("right"))
    if not left or not right:
        return None
    return left, right


def _brace_delta(text: str) -> int:
    depth, quoted, index = 0, False, 0
    while index < len(text):
        ch = text[index]
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch == "{":
                mod = re.match(
                    r"\{\s*(?:static|abstract|classifier|field|method)\s*\}",
                    text[index:],
                )
                if mod:
                    index += mod.end()
                    continue
                depth += 1
            elif ch == "}":
                depth -= 1
        index += 1
    return depth


def _block_end(lines: list[str], start: int) -> int:
    depth = _brace_delta(lines[start])
    index = start + 1
    if depth <= 0:
        if index < len(lines) and lines[index].strip().startswith("{"):
            depth = _brace_delta(lines[index])
            index += 1
        else:
            return start + 1
    while index < len(lines) and depth > 0:
        depth += _brace_delta(lines[index])
        index += 1
    return index


def _directive_mentions(line: str, name: str) -> bool:
    if _at_names(line, name) or _port_names(line, name):
        return True
    for pattern in (VIA_LINE, END_LINE, LABEL_LINE):
        found = pattern.match(line.strip())
        if not found:
            continue
        if name in (_unquote(found.group("a")), _unquote(found.group("b"))):
            return True
    return False


def _edge_directive(line: str, source: str, target: str, ordinal: int) -> bool:
    return (_via_names(line, source, target, ordinal)
            or _end_names(line, "exit", source, target, ordinal)
            or _end_names(line, "entry", source, target, ordinal)
            or _label_names(line, source, target, ordinal))


def _renumber_directive(line: str, source: str, target: str, ordinal: int) -> str:
    for pattern in (VIA_LINE, END_LINE, LABEL_LINE):
        found = pattern.match(line.strip())
        if not found:
            continue
        if (_unquote(found.group("a")) != source
                or _unquote(found.group("b")) != target):
            return line
        if not found.group("n"):
            return line
        number = int(found.group("n"))
        if number <= ordinal:
            return line
        return re.sub(rf"#{number}\b", f"#{number - 1}", line, count=1)
    return line


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
