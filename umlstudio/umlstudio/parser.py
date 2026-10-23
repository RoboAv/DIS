"""Разбор текстового описания диаграммы в объектную модель.

Синтаксис близок к PlantUML, но расширен тремя конструкциями:

* ``shape``  — объявление собственного вида объекта (форма, цвета, секции);
* ``link``   — объявление собственного вида связи;
* ``struct`` — переиспользуемая структура (шаблон из объектов и связей).
"""

from __future__ import annotations

import re

from .errors import Diagnostic
from .model import (
    Compartment,
    Diagram,
    Edge,
    Group,
    LinkDef,
    Member,
    Node,
    ShapeDef,
    StructDef,
)
from .theme import (
    HEAD_SYMBOLS,
    KIND_DEFAULTS,
    LINE_STYLES,
    LINE_SYMBOLS,
    LINK_DEFAULTS,
    TAIL_SYMBOLS,
    normalize_kind,
    normalize_link,
)

# --------------------------------------------------------------- шаблоны ---

_W = r"A-Za-z0-9_\u0400-\u04FF"
IDENT = rf'(?:"[^"]*"|[{_W}][{_W}.:$]*)'

REL_HEAD = re.compile(rf'^\s*(?P<left>{IDENT})\s*(?:"(?P<lmult>[^"]*)"\s*)?')
_CROW = (
    r"\|\|"
    r"|\|o|o\|"
    r"|\}o|o\}|\{o|o\{"
    r"|\}\||\|\}|\{\||\|\{"
)
CONN = re.compile(
    rf"(?P<tail><\||{_CROW}|[<*o+x#}}{{])?"
    rf"(?P<l1>-{{1,}}|\.{{2,}}|={{2,}}|~{{2,}})"
    rf"(?:\[(?P<attrs>[^\]]*)\])?"
    rf"(?P<l2>-{{0,}}|\.{{0,}}|={{0,}}|~{{0,}})"
    rf"(?P<head>\|>|{_CROW}|[>*o+x#}}{{])?"
)
REL_TAIL = re.compile(
    rf'^\s*(?:"(?P<rmult>[^"]*)"\s*)?(?P<right>{IDENT})\s*(?::\s*(?P<label>.*?))?\s*$'
)

DECL = re.compile(
    rf"^\s*(?P<kind>abstract\s+class|[{_W}]+)\s+(?P<name>{IDENT})"
    rf"(?:\s+as\s+(?P<alias>{IDENT}))?(?P<rest>.*)$"
)
GROUP_KW = ("package", "namespace", "group", "frame", "rectangle", "пакет", "группа")
STEREO = re.compile(r"<<\s*(?P<s>[^>]*?)\s*>>")
COLOR = re.compile(r"(?<![\w>])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
SEP_TITLED = re.compile(r"^\s*(?P<m>-{2,}|\.{2,}|={2,}|_{2,})\s*(?P<t>.*?)\s*\1\s*$")
SEP_PLAIN = re.compile(r"^\s*(?:-{2,}|\.{2,}|={2,}|_{2,})\s*$")
MODIFIER = re.compile(
    r"^\s*\{\s*(?P<m>static|abstract|classifier|field|method)\s*\}\s*",
    re.IGNORECASE,
)
STRUCT_HEAD = re.compile(rf"^\s*struct\s+(?P<name>[{_W}]+)\s*\((?P<params>[^)]*)\)")
SHAPE_HEAD = re.compile(
    rf"^\s*shape\s+(?P<name>{IDENT})(?:\s+extends\s+(?P<base>[{_W}]+))?"
)
LINK_HEAD = re.compile(rf"^\s*link\s+(?P<name>{IDENT})")
USE_CALL = re.compile(rf"^\s*(?:use\s+)?(?P<name>[{_W}]+)\s*\((?P<args>.*)\)\s*$")
NOTE_OF = re.compile(
    rf"^\s*note\s+(?P<pos>top|bottom|left|right|сверху|снизу|слева|справа)"
    rf"\s+(?:of|от|у)\s+(?P<target>{IDENT})\s*(?::\s*(?P<text>.*))?$"
)
NOTE_AS = re.compile(rf'^\s*note\s+(?:"(?P<text>[^"]*)"\s+)?as\s+(?P<alias>{IDENT})\s*$')
KV = re.compile(r"^\s*(?P<k>[\w.\u0400-\u04FF-]+)\s*[:=]\s*(?P<v>.*?)\s*$")

_NUMR = r"-?\d+(?:\.\d+)?"
_LOCK = r"lock|locked|блок|замок"
_POS_WORD = r"(?<!\w)(?:at|положение)(?!\w)"
_VIA_WORD = r"(?<!\w)(?:via|через|узлы)(?!\w)"
AT_LINE = re.compile(
    rf"^\s*{_POS_WORD}\s+(?P<name>{IDENT})\s+"
    rf"(?P<x>{_NUMR})\s*,\s*(?P<y>{_NUMR})"
    rf"(?:\s+(?P<lock>{_LOCK}))?\s*$",
    re.IGNORECASE,
)
VIA_LINE = re.compile(
    rf"^\s*(?:via|через)\s+(?P<a>{IDENT})\s+(?P<b>{IDENT})"
    rf"(?:\s+#(?P<n>\d+))?\s+(?P<pts>.+?)\s*$",
    re.IGNORECASE,
)
AT_SUFFIX = re.compile(
    rf"{_POS_WORD}\s+(?P<x>{_NUMR})\s*,\s*(?P<y>{_NUMR})"
    rf"(?:\s+(?P<lock>{_LOCK}))?\s*$",
    re.IGNORECASE,
)
VIA_ATTR = re.compile(
    rf"{_VIA_WORD}\s*=\s*(?P<pts>{_NUMR}(?:\s*,\s*|\s+){_NUMR}"
    rf"(?:\s*;\s*{_NUMR}(?:\s*,\s*|\s+){_NUMR})*)",
    re.IGNORECASE,
)
PORTS_LINE = re.compile(
    rf"^\s*(?:ports|точки)\s+(?P<name>{IDENT})\s+(?P<pts>.+)\s*$",
    re.IGNORECASE,
)
END_LINE = re.compile(
    rf"^\s*(?P<kind>exit|entry|выход|вход)\s+(?P<a>{IDENT})\s+(?P<b>{IDENT})"
    rf"(?:\s+#(?P<n>\d+))?\s+(?P<x>{_NUMR})\s*,\s*(?P<y>{_NUMR})\s*$",
    re.IGNORECASE,
)
LABEL_LINE = re.compile(
    rf"^\s*(?P<kind>labelat|сдвиг)\s+(?P<a>{IDENT})\s+(?P<b>{IDENT})"
    rf"(?:\s+#(?P<n>\d+))?\s+(?P<x>{_NUMR})\s*,\s*(?P<y>{_NUMR})\s*$",
    re.IGNORECASE,
)

TRUE_WORDS = {"on", "true", "1", "yes", "y", "да", "вкл"}
FALSE_WORDS = {"off", "false", "0", "no", "n", "нет", "выкл"}

DIR_WORDS = {
    "top": "up", "up": "up", "сверху": "up", "вверх": "up",
    "bottom": "down", "down": "down", "снизу": "down", "вниз": "down",
    "left": "left", "слева": "left",
    "right": "right", "справа": "right",
}

OPTION_ALIASES = {
    "fontsize": "font_size",
    "font-size": "font_size",
    "шрифт": "font",
    "размер": "font_size",
    "тема": "theme",
    "направление": "direction",
    "фон": "bg",
    "тень": "shadow",
    "nodesep": "node_sep",
    "node-sep": "node_sep",
    "ranksep": "rank_sep",
    "rank-sep": "rank_sep",
    "отступ": "padding",
    "edges": "edge_style",
    "edge": "edge_style",
    "сетка": "grid",
    "скругление": "rounded",
}
BOOL_OPTIONS = {"shadow", "transparent", "hide_empty", "grid", "legend_box"}
NUM_OPTIONS = {"font_size", "node_sep", "rank_sep", "padding", "rounded",
               "title_size", "scale", "stroke_width"}

MAX_EXPANSION_DEPTH = 8


def _line_span(left: str, right: str) -> int:
    """Минимальный охват уровней по длине линии.

    ``--`` (и любой коннектор из двух символов линии) остаётся базовым.
    Каждый следующий ``-``, ``.``, ``=`` или ``~`` добавляет ещё один уровень:
    ``---`` длиннее минимума, ``----`` ещё длиннее.
    """
    return max(1, len(left) + len(right) - 1)


def _unquote(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _multiline(text: str) -> str:
    """Разворачивает экранированный перевод строки в настоящий."""
    return _unquote(text).replace("\\n", "\n")


def _as_bool(value: str, default: bool = True) -> bool:
    v = str(value).strip().lower()
    if v in TRUE_WORDS:
        return True
    if v in FALSE_WORDS:
        return False
    return default


def split_comments(line: str, in_block: bool = False
                  ) -> tuple[str, bool, list[tuple[int, int]]]:
    """Убирает комментарии, не сдвигая остальной текст строки.

    ``'`` и ``//`` закрывают строку, ``/' ... '/`` — блок. Текст в двойных
    кавычках не режется. Комментарии заменяются пробелами, поэтому код до
    них остаётся на своих местах.
    """
    spans, in_block = _comment_spans(line, in_block)
    if not spans:
        return line, in_block, spans
    chars = list(line)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars), in_block, spans


def _comment_spans(line: str, in_block: bool) -> tuple[list[tuple[int, int]], bool]:
    spans: list[tuple[int, int]] = []
    length = len(line)
    index = 0
    if in_block:
        end = line.find("'/")
        if end < 0:
            if length:
                spans.append((0, length))
            return spans, True
        spans.append((0, end + 2))
        index = end + 2
    quoted = False
    while index < length:
        ch = line[index]
        if quoted:
            if ch == '"':
                quoted = False
            index += 1
            continue
        if ch == '"':
            quoted = True
            index += 1
            continue
        if line.startswith("/'", index):
            end = line.find("'/", index + 2)
            if end < 0:
                spans.append((index, length))
                return spans, True
            spans.append((index, end + 2))
            index = end + 2
            continue
        if ch == "'" or line.startswith("//", index):
            spans.append((index, length))
            break
        index += 1
    return spans, False


def _split_args(text: str) -> list[str]:
    """Делит список аргументов по запятым, не трогая запятые внутри кавычек."""
    out, buf, quoted = [], [], False
    for ch in text:
        if ch == '"':
            quoted = not quoted
            continue
        if ch == "," and not quoted:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail or out:
        out.append(tail)
    return [a for a in out if a != ""] if len(out) != 1 else out


class Parser:
    """Преобразует текст в :class:`Diagram`, собирая диагностику по пути."""

    def __init__(self) -> None:
        self.d = Diagram()
        self.diags: list[Diagnostic] = []
        self._note_seq = 0
        self._group_seq = 0
        self._depth = 0
        self._vias: list[tuple] = []
        self._pending_at: list[tuple] = []
        self._pending_ports: list[tuple] = []
        self._ends: list[tuple] = []
        self._label_offs: list[tuple] = []

    # ------------------------------------------------------------ public --

    def parse(self, text: str) -> tuple[Diagram, list[Diagnostic]]:
        lines = self._preprocess(text)
        lines = self._extract_definitions(lines)
        self._parse_lines(lines, group=None)
        self._finish()
        return self.d, self.diags

    # ------------------------------------------------------- диагностика --

    def _err(self, line: int, message: str, text: str = "") -> None:
        self.diags.append(Diagnostic(line, message, "error", text))

    def _warn(self, line: int, message: str, text: str = "") -> None:
        self.diags.append(Diagnostic(line, message, "warning", text))

    # -------------------------------------------------- предобработка -----

    def _preprocess(self, text: str) -> list[tuple[int, str]]:
        """Убирает комментарии и пустые строки, сохраняя номера строк."""
        out: list[tuple[int, str]] = []
        in_block = False
        for no, raw in enumerate(text.splitlines(), start=1):
            line, in_block, _spans = split_comments(raw.rstrip(), in_block)
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("@"):
                head = stripped[1:].strip()
                if head.lower().startswith("startuml"):
                    rest = head[8:].strip()
                if rest and not self.d.title:
                    self.d.title = _multiline(rest)
                    continue
                if head.lower().startswith(("enduml", "end")):
                    continue
                continue
            out.append((no, line))
        return out

    # ------------------------------------------------- блоки в фигурных ---

    @staticmethod
    def _opens_block(text: str) -> bool:
        """Есть ли на строке незакрытая '{' вне кавычек и вне модификаторов."""
        depth, quoted, i = 0, False, 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                quoted = not quoted
            elif not quoted:
                if ch == "{":
                    mod = re.match(
                        r"\{\s*(?:static|abstract|classifier|field|method)\s*\}",
                        text[i:],
                    )
                    if mod:
                        i += mod.end()
                        continue
                    depth += 1
                elif ch == "}":
                    depth -= 1
            i += 1
        return depth > 0

    @staticmethod
    def _closes_block(text: str) -> bool:
        return text.strip() == "}" or text.strip().endswith("}")

    def _read_block(
        self, lines: list[tuple[int, str]], index: int
    ) -> tuple[str, list[tuple[int, str]], int]:
        """Читает ``... { body }``.

        Возвращает (заголовок без '{', строки тела, индекс следующей строки).
        Открывающая скобка может стоять как на строке ``index``, так и ниже.
        """
        no, text = lines[index]
        head = text
        i = index
        if not self._opens_block(text):
            # ищем '{' на следующей непустой строке
            if i + 1 < len(lines) and lines[i + 1][1].strip().startswith("{"):
                i += 1
                head = text
                rest = lines[i][1].strip()[1:]
                body_first = [(lines[i][0], rest)] if rest.strip() else []
            else:
                return head, [], index + 1
        else:
            cut = head.rindex("{")
            body_first = []
            trailing = head[cut + 1:]
            head = head[:cut]
            if trailing.strip():
                body_first = [(no, trailing)]

        body: list[tuple[int, str]] = list(body_first)
        depth = 1
        i += 1
        while i < len(lines) and depth > 0:
            lno, ltext = lines[i]
            opened = self._count_braces(ltext)
            if depth + opened <= 0:
                stripped = ltext.strip()
                tail = stripped[: stripped.rindex("}")] if "}" in stripped else ""
                if tail.strip():
                    body.append((lno, tail))
                depth = 0
                i += 1
                break
            body.append((lno, ltext))
            depth += opened
            i += 1
        if depth > 0:
            self._err(no, "не закрыта фигурная скобка", text)
        return head.strip(), body, i

    @staticmethod
    def _count_braces(text: str) -> int:
        depth, quoted, i = 0, False, 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                quoted = not quoted
            elif not quoted:
                if ch == "{":
                    mod = re.match(
                        r"\{\s*(?:static|abstract|classifier|field|method)\s*\}",
                        text[i:],
                    )
                    if mod:
                        i += mod.end()
                        continue
                    depth += 1
                elif ch == "}":
                    depth -= 1
            i += 1
        return depth

    # --------------------------------- первый проход: свои виды и шаблоны --

    def _extract_definitions(
        self, lines: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        """Вынимает блоки shape/link/struct, чтобы их можно было объявлять где угодно."""
        rest: list[tuple[int, str]] = []
        i = 0
        while i < len(lines):
            no, text = lines[i]
            low = text.strip().lower()
            if low.startswith("shape "):
                head, body, i = self._read_block(lines, i)
                self._def_shape(no, head, body)
                continue
            if low.startswith("link "):
                head, body, i = self._read_block(lines, i)
                self._def_link(no, head, body)
                continue
            if STRUCT_HEAD.match(text):
                head, body, i = self._read_block(lines, i)
                self._def_struct(no, head, body)
                continue
            rest.append((no, text))
            i += 1
        return rest

    def _def_shape(self, no: int, head: str, body: list[tuple[int, str]]) -> None:
        m = SHAPE_HEAD.match(head)
        if not m:
            self._err(no, "ожидалось: shape <Имя> { ... }", head)
            return
        name = _unquote(m.group("name"))
        raw_base = _unquote(m.group("base") or "class")
        # имена пользовательских видов регистрозависимы, встроенных — нет
        base = raw_base if raw_base in self.d.shapes else normalize_kind(raw_base)
        if base not in self.d.shapes and base not in KIND_DEFAULTS:
            self._warn(no, f"неизвестный базовый вид объекта: {raw_base}", head)
            base = "class"
        shape = ShapeDef(name=name, base=base, src_line=no)
        inherited = self.d.shapes.get(base)
        if inherited is not None:
            shape.form = inherited.form
            shape.accent = inherited.accent
            shape.fill = inherited.fill
            shape.stroke = inherited.stroke
            shape.text = inherited.text
            shape.stroke_width = inherited.stroke_width
            shape.dashed = inherited.dashed
            shape.stereotype = inherited.stereotype
            shape.sections = list(inherited.sections)
            shape.font_size = inherited.font_size
            shape.compartments = inherited.compartments
        elif base in KIND_DEFAULTS:
            defaults = KIND_DEFAULTS[base]
            shape.form = defaults.get("form", "rect")
            shape.accent = defaults.get("accent")
            shape.stereotype = defaults.get("stereotype", "")
            shape.compartments = defaults.get("compartments", False)
            shape.title_italic = defaults.get("title_italic", False)
            shape.title_underline = defaults.get("title_underline", False)

        for lno, line in body:
            kv = KV.match(line)
            if not kv:
                self._warn(lno, "в блоке shape ожидается «свойство: значение»", line)
                continue
            key = kv.group("k").strip().lower()
            val = _unquote(kv.group("v"))
            if key in ("form", "форма", "shape"):
                shape.form = val.strip().lower()
            elif key in ("accent", "акцент", "color", "цвет"):
                shape.accent = val
            elif key in ("fill", "заливка", "background"):
                shape.fill = val
            elif key in ("stroke", "border", "обводка", "рамка"):
                shape.stroke = val
            elif key in ("text", "текст", "font-color"):
                shape.text = val
            elif key in ("stroke-width", "width", "толщина"):
                shape.stroke_width = _num(val, 1.4)
            elif key in ("dashed", "пунктир"):
                shape.dashed = _as_bool(val)
            elif key in ("stereotype", "icon", "стереотип", "метка"):
                shape.stereotype = val
            elif key in ("sections", "секции", "compartments"):
                shape.sections = [s for s in _split_args(val) if s]
            elif key in ("font-size", "fontsize", "размер"):
                shape.font_size = int(_num(val, 13))
            elif key in ("members", "содержимое"):
                shape.compartments = _as_bool(val)
            elif key in ("italic", "курсив"):
                shape.title_italic = _as_bool(val)
            elif key in ("underline", "подчёркивание", "подчеркивание"):
                shape.title_underline = _as_bool(val)
            else:
                self._warn(lno, f"неизвестное свойство вида объекта: {key}", line)
        if shape.sections:
            shape.compartments = True
        self.d.shapes[name] = shape

    def _def_link(self, no: int, head: str, body: list[tuple[int, str]]) -> None:
        m = LINK_HEAD.match(head)
        if not m:
            self._err(no, "ожидалось: link <имя> { ... }", head)
            return
        name = _unquote(m.group("name"))
        link = LinkDef(name=name, src_line=no)
        for lno, line in body:
            kv = KV.match(line)
            if not kv:
                self._warn(lno, "в блоке link ожидается «свойство: значение»", line)
                continue
            key = kv.group("k").strip().lower()
            val = _unquote(kv.group("v")).strip()
            if key in ("line", "линия", "style", "стиль"):
                link.line = val.lower() if val.lower() in LINE_STYLES else "solid"
            elif key in ("head", "конец", "target", "цель"):
                link.head = val.lower().replace("-", "_")
            elif key in ("tail", "начало", "source", "источник"):
                link.tail = val.lower().replace("-", "_")
            elif key in ("color", "цвет"):
                link.color = val
            elif key in ("width", "толщина"):
                link.width = _num(val, 1.4)
            elif key in ("label", "подпись"):
                link.label = val
            else:
                self._warn(lno, f"неизвестное свойство связи: {key}", line)
        self.d.links[name] = link

    def _def_struct(self, no: int, head: str, body: list[tuple[int, str]]) -> None:
        m = STRUCT_HEAD.match(head)
        if not m:
            self._err(no, "ожидалось: struct <Имя>(парам1, парам2) { ... }", head)
            return
        name = m.group("name")
        params = [p for p in _split_args(m.group("params")) if p]
        self.d.structs[name] = StructDef(name, params, list(body), no)

    # -------------------------------------------- основной проход по тексту --

    def _parse_lines(self, lines: list[tuple[int, str]], group: str | None) -> None:
        i = 0
        while i < len(lines):
            no, text = lines[i]
            stripped = text.strip()
            if not stripped or stripped == "}":
                i += 1
                continue
            low = stripped.lower()
            first = low.split(maxsplit=1)[0]

            # --- директивы уровня документа ---
            if first in ("title", "заголовок"):
                rest = stripped[len(first):].strip()
                if rest:
                    self.d.title = _multiline(rest)
                    i += 1
                else:
                    block, i = self._read_until(lines, i + 1, ("end title", "endtitle"))
                    self.d.title = "\n".join(t for _, t in block).strip()
                continue
            if first in ("caption", "подпись", "footer"):
                self.d.caption = _multiline(stripped[len(first):].strip())
                i += 1
                continue
            if low in ("legend", "легенда"):
                block, i = self._read_until(
                    lines, i + 1, ("endlegend", "end legend", "конец легенды")
                )
                self.d.legend = [t.strip() for _, t in block]
                continue
            if first in ("theme", "тема"):
                self.d.options["theme"] = stripped.split(maxsplit=1)[-1].strip().lower()
                i += 1
                continue
            if first in ("direction", "направление"):
                self._set_option(no, "direction", stripped.split(maxsplit=1)[-1])
                i += 1
                continue
            if low in ("left to right direction", "слева направо"):
                self.d.options["direction"] = "LR"
                i += 1
                continue
            if low in ("top to bottom direction", "сверху вниз"):
                self.d.options["direction"] = "TB"
                i += 1
                continue
            if first in ("set", "!set", "опция"):
                self._parse_set(no, stripped.split(maxsplit=1)[-1])
                i += 1
                continue
            if low.startswith("hide empty"):
                self.d.options["hide_empty"] = True
                i += 1
                continue
            if low.startswith("skinparam"):
                self._parse_set(no, stripped.split(maxsplit=1)[-1])
                i += 1
                continue
            if first in ("at", "положение") and AT_LINE.match(stripped):
                self._parse_at(no, stripped)
                i += 1
                continue
            if first in ("via", "через") and VIA_LINE.match(stripped):
                self._parse_via(no, stripped)
                i += 1
                continue
            if first in ("ports", "точки") and PORTS_LINE.match(stripped):
                self._parse_ports(no, stripped)
                i += 1
                continue
            if first in ("exit", "entry", "выход", "вход") and END_LINE.match(stripped):
                self._parse_end(no, stripped)
                i += 1
                continue
            if first in ("labelat", "сдвиг") and LABEL_LINE.match(stripped):
                self._parse_label_off(no, stripped)
                i += 1
                continue

            # --- заметки ---
            if first in ("note", "заметка"):
                i = self._parse_note(lines, i, group)
                continue

            # --- контейнеры ---
            if first in GROUP_KW and (self._opens_block(text) or
                                      self._next_is_brace(lines, i)):
                head, body, i = self._read_block(lines, i)
                gname = self._make_group(no, head, group)
                self._parse_lines(body, gname)
                continue

            # --- использование структуры ---
            use = USE_CALL.match(stripped)
            if use and use.group("name") in self.d.structs:
                self._expand_struct(no, use.group("name"),
                                    _split_args(use.group("args")), group)
                i += 1
                continue
            if low.startswith("use "):
                self._err(no, "неизвестная структура в use", stripped)
                i += 1
                continue

            # --- связь ---
            rel = self._try_relation(stripped)
            if rel is not None:
                self._add_relation(no, rel, group)
                i += 1
                continue

            # --- объявление объекта ---
            handled, i = self._try_declaration(lines, i, group)
            if not handled:
                self._warn(no, "строка не распознана и пропущена", stripped)

    def _next_is_brace(self, lines: list[tuple[int, str]], i: int) -> bool:
        return i + 1 < len(lines) and lines[i + 1][1].strip().startswith("{")

    def _read_until(
        self, lines: list[tuple[int, str]], start: int, enders: tuple[str, ...]
    ) -> tuple[list[tuple[int, str]], int]:
        out: list[tuple[int, str]] = []
        i = start
        while i < len(lines):
            low = lines[i][1].strip().lower()
            if low in enders:
                return out, i + 1
            out.append(lines[i])
            i += 1
        return out, i

    # ------------------------------------------------------------ опции ---

    def _parse_set(self, no: int, text: str) -> None:
        m = KV.match(text)
        if m:
            self._set_option(no, m.group("k"), m.group("v"))
            return
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            self._set_option(no, parts[0], parts[1])
        elif parts:
            self._set_option(no, parts[0], "on")

    def _set_option(self, no: int, key: str, value: str) -> None:
        key = key.strip().lower().replace(" ", "_")
        key = OPTION_ALIASES.get(key, key)
        value = _unquote(value)
        if key in BOOL_OPTIONS:
            self.d.options[key] = _as_bool(value)
        elif key in NUM_OPTIONS:
            self.d.options[key] = _num(value, 0)
        elif key == "direction":
            v = value.strip().upper()
            self.d.options["direction"] = v if v in ("TB", "LR", "BT", "RL") else "TB"
        else:
            self.d.options[key] = value

    # ------------------------------------------------------------ группы --

    def _make_group(self, no: int, head: str, parent: str | None) -> str:
        parts = head.split(maxsplit=1)
        kind = parts[0].strip().lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        style: dict = {}
        color = COLOR.search(rest)
        if color:
            style["fill"] = color.group(0)
            rest = rest[: color.start()] + rest[color.end():]
        stereo = STEREO.search(rest)
        if stereo:
            style["stereotype"] = stereo.group("s")
            rest = rest[: stereo.start()] + rest[stereo.end():]
        rest = rest.strip()

        name, label = "", ""
        m = re.match(rf"^(?P<a>{IDENT})(?:\s+as\s+(?P<b>{IDENT}))?$", rest)
        if m:
            a = m.group("a")
            b = m.group("b")
            if b:
                if a.startswith('"'):
                    label, name = _unquote(a), _unquote(b)
                else:
                    name, label = _unquote(a), _unquote(b)
            else:
                label = _unquote(a)
                name = label
        if not name:
            self._group_seq += 1
            name = f"__group{self._group_seq}"
            label = rest or ""
        if name in self.d.groups:
            self._group_seq += 1
            name = f"{name}__{self._group_seq}"
        # Связь, записанная раньше пакета, успевает завести пустой объект
        # с тем же именем. Пакет забирает имя себе.
        stub = self.d.nodes.get(name)
        if stub is not None and stub.style.get("_implicit"):
            del self.d.nodes[name]
        kind = "package" if kind in ("пакет", "группа") else kind
        self.d.groups[name] = Group(
            name=name, label=label or name, kind=kind, parent=parent,
            style=style, src_line=no,
        )
        return name

    # ------------------------------------------------------- объявления ---

    def _try_declaration(
        self, lines: list[tuple[int, str]], index: int, group: str | None
    ) -> tuple[bool, int]:
        no, text = lines[index]
        stripped = text.strip()

        head, body, next_i = stripped, [], index + 1
        if self._opens_block(text) or self._next_is_brace(lines, index):
            head, body, next_i = self._read_block(lines, index)

        m = DECL.match(head)
        kind_raw = m.group("kind").strip().lower() if m else ""
        kind = normalize_kind(kind_raw)
        known = kind in KIND_DEFAULTS or kind_raw in self.d.shapes or \
            m is not None and m.group("kind").strip() in self.d.shapes

        if m and known:
            shape_key = m.group("kind").strip()
            kind = shape_key if shape_key in self.d.shapes else kind
            name_tok, alias_tok = m.group("name"), m.group("alias")
            rest = m.group("rest") or ""
        else:
            # одиночный идентификатор -> объект по умолчанию
            solo = re.match(rf"^\s*(?P<name>{IDENT})\s*$", head)
            if not solo:
                return False, next_i
            kind = normalize_kind(self.d.opt("default_kind", "class"))
            name_tok, alias_tok, rest = solo.group("name"), None, ""

        name, label = _unquote(name_tok), ""
        if alias_tok:
            if name_tok.startswith('"'):
                label, name = _unquote(name_tok), _unquote(alias_tok)
            else:
                name, label = _unquote(name_tok), _unquote(alias_tok)
        elif name_tok.startswith('"'):
            label = _unquote(name_tok)

        style: dict = {}
        stereo = STEREO.search(rest)
        stereotype = ""
        if stereo:
            stereotype = stereo.group("s")
            rest = rest[: stereo.start()] + rest[stereo.end():]
        color = COLOR.search(rest)
        if color:
            style["fill"] = color.group(0)
            rest = rest[: color.start()] + rest[color.end():]
        pin = None
        pinned = False
        located = AT_SUFFIX.search(rest)
        if located:
            pin = (float(located.group("x")), float(located.group("y")))
            pinned = bool(located.group("lock"))
            rest = (rest[: located.start()] + rest[located.end():]).strip()
        leftover = rest.strip().strip("{}").strip()
        if leftover:
            self._warn(no, f"непонятный остаток объявления: {leftover}", stripped)

        node = self.d.nodes.get(name)
        if node is None:
            node = Node(name=name, kind=kind, src_line=no)
            self.d.nodes[name] = node
        else:
            node.kind = kind
            node.style.pop("_implicit", None)
        if label:
            node.label = label
        if stereotype:
            node.stereotype = stereotype
        node.style.update(style)
        if pin is not None:
            node.pin = pin
            node.locked = pinned
        if group and node.group is None:
            node.group = group
        if body:
            self._parse_node_body(node, body)
        return True, next_i

    def _parse_node_body(self, node: Node, body: list[tuple[int, str]]) -> None:
        shape = self.d.shapes.get(node.kind)
        sections = {s.lower(): s for s in (shape.sections if shape else [])}
        current = Compartment()
        comps: list[Compartment] = [current]

        for lno, raw in body:
            line = raw.strip()
            if not line:
                continue
            titled = SEP_TITLED.match(line)
            if titled and titled.group("t"):
                current = Compartment(title=titled.group("t"))
                comps.append(current)
                continue
            if SEP_PLAIN.match(line):
                current = Compartment()
                comps.append(current)
                continue
            head = line.rstrip(":").strip().lower()
            if line.endswith(":") and head in sections:
                current = Compartment(title=sections[head])
                comps.append(current)
                continue
            member = self._parse_member(line)
            if member is not None:
                current.members.append(member)

        comps = [c for c in comps if not c.is_empty()]
        if len(comps) == 1 and not comps[0].title and not sections:
            comps = self._auto_split(comps[0])
        node.compartments.extend(comps)

    @staticmethod
    def _parse_member(line: str) -> Member | None:
        """Разбирает строку тела объекта.

        Модификаторы ``{static}`` и ``{abstract}`` допускаются как до знака
        видимости, так и после него.
        """
        mods: set[str] = set()
        text = line

        def eat_modifiers(value: str) -> str:
            while True:
                found = MODIFIER.match(value)
                if not found:
                    return value
                mods.add(found.group("m").lower())
                value = value[found.end():]

        text = eat_modifiers(text)
        visibility = ""
        if text[:1] in ("+", "-", "#", "~"):
            visibility, text = text[0], text[1:].lstrip()
        text = eat_modifiers(text).strip()
        if not text:
            return None
        return Member(
            text=text,
            visibility=visibility,
            static="static" in mods or "classifier" in mods,
            abstract="abstract" in mods,
        )

    @staticmethod
    def _auto_split(comp: Compartment) -> list[Compartment]:
        """Делит тело на «поля» и «операции», как это делает PlantUML."""
        fields = [m for m in comp.members if "(" not in m.text]
        methods = [m for m in comp.members if "(" in m.text]
        if not fields or not methods:
            return [comp]
        return [Compartment(members=fields), Compartment(members=methods)]

    # ------------------------------------------------------------ связи ---

    def _try_relation(self, text: str) -> dict | None:
        head = REL_HEAD.match(text)
        if not head:
            return None
        rest = text[head.end():]
        conn = CONN.match(rest)
        if not conn:
            return None
        symbols = (conn.group("l1") or "") + (conn.group("l2") or "")
        if not symbols:
            return None
        tail_part = REL_TAIL.match(rest[conn.end():])
        if not tail_part:
            return None
        left = _unquote(head.group("left"))
        right = _unquote(tail_part.group("right"))
        if not left or not right:
            return None
        return {
            "left": left,
            "right": right,
            "lmult": head.group("lmult") or "",
            "rmult": tail_part.group("rmult") or "",
            "label": (tail_part.group("label") or "").strip(),
            "tail": conn.group("tail") or "",
            "head": conn.group("head") or "",
            "l1": conn.group("l1") or "",
            "l2": conn.group("l2") or "",
            "attrs": conn.group("attrs"),
        }

    def _add_relation(self, no: int, rel: dict, group: str | None) -> None:
        for key in ("left", "right"):
            name = rel[key]
            if name in self.d.groups or name in self.d.nodes:
                continue
            node = self.d.ensure_node(
                name, normalize_kind(self.d.opt("default_kind", "class")), no
            )
            node.style["_implicit"] = True
            if group and node.group is None:
                node.group = group

        line_char = (rel["l1"] + rel["l2"]).strip()
        style = LINE_SYMBOLS.get(line_char[0] if line_char else "-", "solid")
        edge = Edge(
            a=rel["left"],
            b=rel["right"],
            a_mult=rel["lmult"],
            b_mult=rel["rmult"],
            label=rel["label"],
            tail=TAIL_SYMBOLS.get(rel["tail"], "none"),
            head=HEAD_SYMBOLS.get(rel["head"], "none"),
            line=style,
            min_span=_line_span(rel["l1"], rel["l2"]),
            src_line=no,
        )
        if rel["tail"] and rel["head"] == "" and rel["tail"] in ("<|", "<"):
            edge.head = "none"
        self._apply_edge_attrs(no, edge, rel["attrs"])
        if edge.head == "none" and edge.tail == "none" and not edge.kind:
            edge.kind = "line"
        self.d.edges.append(edge)

    def _apply_edge_attrs(self, no: int, edge: Edge, attrs: str | None) -> None:
        edge.kind = self._guess_kind(edge)
        if not attrs:
            return
        located = VIA_ATTR.search(attrs)
        if located:
            edge.waypoints = parse_points(located.group("pts"))
            attrs = (attrs[: located.start()] + " " + attrs[located.end():]).strip(" ,")
        if not attrs:
            return
        faces: list[str] = []
        for token in _split_args(attrs):
            tok = token.strip()
            if not tok:
                continue
            low = tok.lower()
            kv = KV.match(tok)
            if low.startswith("#"):
                edge.color = tok
            elif low in LINE_STYLES:
                edge.line = low
            elif low in ("hidden", "invisible", "скрытая"):
                edge.color = "hidden"
            elif low in ("notowning", "notwoning"):
                edge.notowning = True
            elif low in ("lock", "locked", "блок", "замок"):
                edge.locked = True
            elif low in DIR_WORDS:
                faces.append(DIR_WORDS[low])
            elif normalize_link(low) in LINK_DEFAULTS or tok in self.d.links:
                self._apply_link_kind(edge, tok)
            elif kv:
                self._apply_edge_kv(no, edge, kv.group("k").lower(), kv.group("v"))
            else:
                self._warn(no, f"неизвестный параметр связи: {tok}")
        if edge.notowning and faces:
            edge.direction = faces[0]
            if len(faces) > 1:
                edge.arrive = faces[1]
        elif faces:
            edge.direction = faces[-1]

    def _apply_link_kind(self, edge: Edge, name: str) -> None:
        custom = self.d.links.get(name)
        if custom is not None:
            data = custom.as_style()
            edge.kind = custom.name
        else:
            key = normalize_link(name)
            data = dict(LINK_DEFAULTS.get(key, {}))
            edge.kind = key
        edge.line = data.get("line", edge.line)
        edge.head = data.get("head", edge.head)
        edge.tail = data.get("tail", edge.tail)
        if data.get("color"):
            edge.color = data["color"]
        if data.get("width"):
            edge.width = data["width"]
        if data.get("label") and not edge.label:
            edge.label = data["label"]

    def _apply_edge_kv(self, no: int, edge: Edge, key: str, value: str) -> None:
        value = _unquote(value).strip()
        if key in ("head", "конец"):
            edge.head = value.lower().replace("-", "_")
        elif key in ("tail", "начало"):
            edge.tail = value.lower().replace("-", "_")
        elif key in ("color", "цвет"):
            edge.color = value
        elif key in ("width", "толщина"):
            edge.width = _num(value, 1.4)
        elif key in ("label", "подпись"):
            edge.label = value
        elif key in ("line", "линия", "style", "стиль"):
            if value.lower() in LINE_STYLES:
                edge.line = value.lower()
        elif key in ("dir", "direction", "направление"):
            edge.direction = DIR_WORDS.get(value.lower(), "")
        elif key in ("notowning", "notwoning"):
            edge.notowning = _as_bool(value)
        elif key in ("arrive", "to", "вход"):
            edge.arrive = DIR_WORDS.get(value.lower(), "")
        else:
            self._warn(no, f"неизвестный параметр связи: {key}")

    @staticmethod
    def _guess_kind(edge: Edge) -> str:
        if edge.head == "triangle" or edge.tail == "triangle":
            return "realization" if edge.line in ("dashed", "dotted") else "inheritance"
        if "diamond_filled" in (edge.head, edge.tail):
            return "composition"
        if "diamond" in (edge.head, edge.tail):
            return "aggregation"
        if edge.line in ("dashed", "dotted") and "arrow" in (edge.head, edge.tail):
            return "dependency"
        if "arrow" in (edge.head, edge.tail):
            return "association"
        return "line"

    # --------------------------------------------------------- заметки ----

    def _parse_note(
        self, lines: list[tuple[int, str]], index: int, group: str | None
    ) -> int:
        no, text = lines[index]
        stripped = text.strip()

        m = NOTE_OF.match(stripped)
        if m:
            target = _unquote(m.group("target"))
            body = m.group("text") or ""
            next_i = index + 1
            if not body.strip():
                body_lines, next_i = self._collect_note_body(lines, index)
                body = "\n".join(body_lines)
            self._note_seq += 1
            name = f"__note{self._note_seq}"
            node = Node(name=name, kind="note", label=body.strip(), src_line=no,
                        group=self.d.nodes[target].group
                        if target in self.d.nodes else group)
            self.d.nodes[name] = node
            self.d.ensure_node(target, "class", no)
            pos = m.group("pos")
            direction = DIR_WORDS.get(pos, "same")
            if direction == "up":
                self.d.edges.append(Edge(a=name, b=target, kind="note",
                                         line="dotted", head="none", tail="none",
                                         src_line=no))
            else:
                beside = direction if direction in ("left", "right", "same") else ""
                self.d.edges.append(Edge(a=target, b=name, kind="note",
                                         line="dotted", head="none", tail="none",
                                         direction=beside,
                                         src_line=no))
            return next_i

        m = NOTE_AS.match(stripped)
        if m:
            alias = _unquote(m.group("alias"))
            body = m.group("text") or ""
            next_i = index + 1
            if not body:
                body_lines, next_i = self._collect_note_body(lines, index)
                body = "\n".join(body_lines)
            self.d.nodes[alias] = Node(alias, "note", label=body.strip(),
                                       group=group, src_line=no)
            return next_i

        rest = stripped.split(maxsplit=1)
        if len(rest) == 2 and ":" in rest[1]:
            alias, body = rest[1].split(":", 1)
            alias = _unquote(alias.strip())
            node = self.d.ensure_node(alias, "note", no, group)
            node.kind = "note"
            node.label = body.strip()
            return index + 1
        if len(rest) == 2:
            self._note_seq += 1
            name = f"__note{self._note_seq}"
            self.d.nodes[name] = Node(name, "note", label=_unquote(rest[1]),
                                      group=group, src_line=no)
            return index + 1
        self._warn(no, "не удалось разобрать заметку", stripped)
        return index + 1

    def _collect_note_body(
        self, lines: list[tuple[int, str]], index: int
    ) -> tuple[list[str], int]:
        if self._opens_block(lines[index][1]):
            _, body, next_i = self._read_block(lines, index)
            return [t.strip() for _, t in body], next_i
        body, next_i = self._read_until(
            lines, index + 1, ("end note", "endnote", "конец заметки")
        )
        return [t.strip() for _, t in body], next_i

    # ------------------------------------------------ структуры-шаблоны ---

    def _expand_struct(
        self, no: int, name: str, args: list[str], group: str | None
    ) -> None:
        struct = self.d.structs.get(name)
        if struct is None:
            self._err(no, f"структура «{name}» не объявлена")
            return
        if self._depth >= MAX_EXPANSION_DEPTH:
            self._err(no, "слишком глубокая вложенность структур")
            return
        if len(args) < len(struct.params):
            self._warn(
                no,
                f"структуре «{name}» нужно {len(struct.params)} аргумент(ов), "
                f"передано {len(args)}",
            )
        mapping = {p: (args[i] if i < len(args) else "")
                   for i, p in enumerate(struct.params)}
        expanded: list[tuple[int, str]] = []
        for _, line in struct.body:
            expanded.append((no, _substitute(line, mapping)))
        self._depth += 1
        try:
            self._parse_lines(expanded, group)
        finally:
            self._depth -= 1

    # ----------------------------------------------------------- финал ---

    def _finish(self) -> None:
        known = set(self.d.nodes) | set(self.d.groups)
        for edge in list(self.d.edges):
            if edge.a not in known or edge.b not in known:
                self.d.edges.remove(edge)
                self._warn(edge.src_line, "связь ссылается на неизвестный объект")
        if self.d.opt("hide_empty"):
            for node in self.d.nodes.values():
                node.compartments = [c for c in node.compartments if c.members]
        for no, name, x, y, locked in self._pending_at:
            if not self._assign_at(name, x, y, locked):
                self._warn(no, f"положение: нет объекта {name}")
        for no, name, points in self._pending_ports:
            if not self._assign_ports(name, points):
                self._warn(no, f"точки: нет объекта {name}")
        self._apply_vias()
        self._apply_ends()
        self._apply_label_offs()

    def _assign_at(self, name: str, x: float, y: float, locked: bool) -> bool:
        target = self.d.nodes.get(name)
        if target is None:
            target = self.d.groups.get(name)
        if target is None:
            return False
        target.pin = (x, y)
        target.locked = locked
        return True

    def _parse_at(self, no: int, stripped: str) -> None:
        found = AT_LINE.match(stripped)
        if not found:
            self._warn(no, "ожидалось: at Имя x, y [lock]", stripped)
            return
        name = _unquote(found.group("name"))
        x, y = float(found.group("x")), float(found.group("y"))
        locked = bool(found.group("lock"))
        if not self._assign_at(name, x, y, locked):
            self._pending_at.append((no, name, x, y, locked))

    def _parse_via(self, no: int, stripped: str) -> None:
        found = VIA_LINE.match(stripped)
        if not found:
            self._warn(no, "ожидалось: via A B [#n] x, y; ... [lock]", stripped)
            return
        points = parse_points(found.group("pts"))
        straight = _straight_mark(found.group("pts"))
        if not points and not straight and not has_lock(found.group("pts")):
            self._warn(no, "у via нет координат", stripped)
            return
        index = int(found.group("n")) if found.group("n") else None
        self._vias.append((
            no, _unquote(found.group("a")), _unquote(found.group("b")),
            index, points, has_lock(found.group("pts")), straight,
        ))

    def _apply_vias(self) -> None:
        buckets: dict[tuple[str, str], list[Edge]] = {}
        for edge in self.d.edges:
            buckets.setdefault((edge.a, edge.b), []).append(edge)
        for no, a, b, index, points, locked, straight in self._vias:
            edges = buckets.get((a, b), [])
            if not edges:
                self._warn(no, f"via: нет связи {a} -> {b}")
                continue
            if index is None:
                target = next((item for item in edges if not item.waypoints), edges[-1])
            elif index < 1 or index > len(edges):
                self._warn(no, f"via: у {a} -> {b} нет связи #{index}")
                continue
            else:
                target = edges[index - 1]
            if straight:
                target.straight = True
                target.waypoints = []
            elif points:
                target.waypoints = points
                target.straight = False
            target.locked = locked

    def _parse_ports(self, no: int, stripped: str) -> None:
        found = PORTS_LINE.match(stripped)
        if not found:
            self._warn(no, "ожидалось: ports Имя x, y; ...", stripped)
            return
        points = parse_points(found.group("pts"))
        if not points:
            self._warn(no, "у ports нет координат", stripped)
            return
        name = _unquote(found.group("name"))
        if not self._assign_ports(name, points):
            self._pending_ports.append((no, name, points))

    def _assign_ports(self, name: str, points: list[tuple[float, float]]) -> bool:
        target = self.d.nodes.get(name)
        if target is None:
            target = self.d.groups.get(name)
        if target is None:
            return False
        target.ports = list(points)
        return True

    def _parse_end(self, no: int, stripped: str) -> None:
        found = END_LINE.match(stripped)
        if not found:
            self._warn(no, "ожидалось: exit A B [#n] x, y", stripped)
            return
        index = int(found.group("n")) if found.group("n") else None
        self._ends.append((
            no, found.group("kind").lower(),
            _unquote(found.group("a")), _unquote(found.group("b")),
            index, (float(found.group("x")), float(found.group("y"))),
        ))

    def _apply_ends(self) -> None:
        buckets: dict[tuple[str, str], list[Edge]] = {}
        for edge in self.d.edges:
            buckets.setdefault((edge.a, edge.b), []).append(edge)
        for no, kind, a, b, index, point in self._ends:
            edges = buckets.get((a, b), [])
            if not edges:
                self._warn(no, f"{kind}: нет связи {a} -> {b}")
                continue
            if index is None:
                target = edges[0]
            elif index < 1 or index > len(edges):
                self._warn(no, f"{kind}: у {a} -> {b} нет связи #{index}")
                continue
            else:
                target = edges[index - 1]
            if kind in ("exit", "выход"):
                target.exit_at = point
            else:
                target.entry_at = point

    def _parse_label_off(self, no: int, stripped: str) -> None:
        found = LABEL_LINE.match(stripped)
        if not found:
            self._warn(no, "ожидалось: labelat A B [#n] dx, dy", stripped)
            return
        index = int(found.group("n")) if found.group("n") else None
        self._label_offs.append((
            no, _unquote(found.group("a")), _unquote(found.group("b")),
            index, (float(found.group("x")), float(found.group("y"))),
        ))

    def _apply_label_offs(self) -> None:
        buckets: dict[tuple[str, str], list[Edge]] = {}
        for edge in self.d.edges:
            buckets.setdefault((edge.a, edge.b), []).append(edge)
        for no, a, b, index, point in self._label_offs:
            edges = buckets.get((a, b), [])
            if not edges:
                self._warn(no, f"сдвиг: нет связи {a} -> {b}")
                continue
            if index is None:
                target = edges[0]
            elif index < 1 or index > len(edges):
                self._warn(no, f"сдвиг: у {a} -> {b} нет связи #{index}")
                continue
            else:
                target = edges[index - 1]
            target.label_off = point


def _substitute(line: str, mapping: dict[str, str]) -> str:
    """Подставляет параметры структуры.

    Поддерживаются обе записи: ``${Name}`` и ``$Name``. Во второй берётся
    самое длинное имя параметра, совпавшее с началом слова, поэтому
    ``$NameApi`` превращается в ``OrderApi``.
    """
    if not mapping:
        return line
    keys = sorted(mapping, key=len, reverse=True)
    out: list[str] = []
    i = 0
    while i < len(line):
        if line[i] != "$":
            out.append(line[i])
            i += 1
            continue
        if line.startswith("${", i):
            end = line.find("}", i + 2)
            if end > 0 and line[i + 2:end] in mapping:
                out.append(mapping[line[i + 2:end]])
                i = end + 1
                continue
        for key in keys:
            if line.startswith(key, i + 1):
                out.append(mapping[key])
                i += 1 + len(key)
                break
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


def parse_points(text: str) -> list[tuple[float, float]]:
    """Пары координат из ``x, y; x, y`` или ``x y; x y``."""
    cleaned = re.sub(rf"\s+(?:{_LOCK})\s*$", "", text.strip(), flags=re.IGNORECASE)
    number = re.compile(_NUMR)
    points: list[tuple[float, float]] = []
    for chunk in cleaned.split(";"):
        nums = [float(item) for item in number.findall(chunk)]
        if len(nums) >= 2:
            points.append((nums[0], nums[1]))
    return points


def has_lock(text: str) -> bool:
    return re.search(rf"(?<!\w)(?:{_LOCK})(?!\w)", text, re.IGNORECASE) is not None


def _straight_mark(text: str) -> bool:
    """``прямо`` / ``straight`` вместо координат: у связи только вход и выход."""
    cleaned = re.sub(rf"\s+(?:{_LOCK})\s*$", "", text.strip(), flags=re.IGNORECASE)
    return cleaned.lower() in ("прямо", "straight", "direct")


def _num(value: str, default: float) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return default


def parse(text: str) -> tuple[Diagram, list[Diagnostic]]:
    """Разбирает текст диаграммы, возвращая модель и список диагностик."""
    return Parser().parse(text)
