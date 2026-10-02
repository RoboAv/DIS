"""Текстовый редактор с нумерацией строк и подсветкой синтаксиса."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..parser import (
    CONN,
    DECL,
    GROUP_KW,
    IDENT,
    LINK_HEAD,
    NOTE_AS,
    NOTE_OF,
    REL_HEAD,
    REL_TAIL,
    SHAPE_HEAD,
    STRUCT_HEAD,
    USE_CALL,
)
from ..theme import (
    DECORATIONS,
    FORMS,
    KIND_ALIASES,
    KIND_DEFAULTS,
    LINK_ALIASES,
    LINK_DEFAULTS,
)
from . import hotkeys, native, tooltip
from .names import (
    continues_name,
    index_at,
    is_reserved,
    name_from_selection,
    name_on_line,
    name_spans,
    places,
    plan_rename,
)
from .palette import colors as ui_colors

BLOCK_KEYWORDS = ("shape", "link", "struct", "use", "package", "namespace",
                  "group", "frame", "rectangle", "note", "end note", "endlegend",
                  "legend", "title", "caption", "footer", "set", "theme",
                  "direction", "hide", "as", "extends", "of")

DIRECTIVE_RE = re.compile(
    r"^\s*(@\w+|" + "|".join(sorted(BLOCK_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
KIND_RE = re.compile(
    r"^\s*(?:abstract\s+class|"
    + "|".join(sorted(KIND_DEFAULTS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)
_CROW_MARK = (
    r"\|\||\|o|o\||\}o|o\}|\{o|o\{|\}\||\|\}|\{\||\|\{"
)
CONNECTOR_RE = re.compile(
    rf"(<\||{_CROW_MARK}|[*o+x#}}{{])?(-{{1,}}|\.{{2,}}|={{2,}}|~{{2,}})"
    rf"(\[[^\]]*\])?(-{{0,}}|\.{{0,}}|={{0,}}|~{{0,}})"
    rf"(\|>|{_CROW_MARK}|[>*o+x#}}{{])?"
)
STRING_RE = re.compile(r'"[^"\n]*"')
COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
PARAM_RE = re.compile(r"\$\{?[\w\u0400-\u04FF]+\}?")
STEREO_RE = re.compile(r"<<[^>\n]*>>")
PROPERTY_RE = re.compile(r"^\s*[\w\u0400-\u04FF-]+\s*:")
VISIBILITY_RE = re.compile(r"^\s*(\{\s*\w+\s*\}\s*)*[-+#~]")
_LINE_COMMENT_RE = re.compile(r"^([ \t]*)(?://|') ?")
_NAME_EDGE = r"A-Za-z0-9_\u0400-\u04FF.:$"
_KIND_WORDS = {name.lower() for name in (*KIND_DEFAULTS, *KIND_ALIASES)}
_LINK_WORDS = {name.lower() for name in (*LINK_DEFAULTS, *LINK_ALIASES)}
_WORD = re.compile(rf"[A-Za-z0-9_\u0400-\u04FF][{_NAME_EDGE}]*")
_EXTENDS_BASE = re.compile(
    rf"\bextends\s+(?P<base>[A-Za-z0-9_\u0400-\u04FF][{_NAME_EDGE}]*)",
    re.IGNORECASE,
)
_SOLO = re.compile(rf"^\s*(?P<name>[A-Za-z0-9_\u0400-\u04FF][{_NAME_EDGE}]*)\s*$")
_GROUP_RE = re.compile(
    r"^\s*(?:"
    + "|".join(re.escape(word) for word in sorted(GROUP_KW, key=len, reverse=True))
    + rf")\s+(?P<a>{IDENT})(?:\s+as\s+(?P<b>{IDENT}))?",
    re.IGNORECASE,
)

# Служебные слова в любом месте строки, не только в начале.
# Если слово ещё и встроенный вид, на старте строки побеждает пометка kind.
_KEYWORDS = (
    *BLOCK_KEYWORDS,
    "end", "endnote", "end legend", "skinparam",
    "abstract", "static",
    "hidden", "invisible", "скрытая", "notowning", "notwoning",
    "left", "right", "top", "bottom", "up", "down", "same",
    "сверху", "снизу", "слева", "справа", "вверх", "вниз",
    "on", "off", "true", "false", "yes", "no",
    "да", "нет", "вкл", "выкл",
    "solid", "dashed", "dotted", "bold",
    "ortho", "straight",
    "пакет", "группа", "заметка", "заголовок", "подпись",
    "легенда", "тема", "направление", "опция", "конец",
    *DECORATIONS,
    *FORMS,
)
KEYWORD_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(word) for word in sorted(set(_KEYWORDS), key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def _is_comment_line(line: str) -> bool:
    stripped = line.lstrip(" \t")
    return stripped.startswith("'") or stripped.startswith("//")


def _should_uncomment(lines: list[str]) -> bool:
    """Снимать пометку, если каждая непустая строка уже комментарий."""
    content = [line for line in lines if line.strip()]
    return bool(content) and all(_is_comment_line(line) for line in content)


def _comment_line(line: str) -> str:
    indent = re.match(r"[ \t]*", line).group(0)
    return f"{indent}' {line[len(indent):]}"


def _uncomment_line(line: str) -> str:
    return _LINE_COMMENT_RE.sub(r"\1", line, count=1)


def _shifted_column(old: str, new: str, col: int) -> int:
    indent = len(old) - len(old.lstrip(" \t"))
    if col <= indent:
        return col
    return max(indent, col + len(new) - len(old))


def _split_comment(line: str) -> str:
    """Код строки без хвостового комментария ``'`` или ``//``."""
    quoted = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch == "'":
                return line[:i]
            if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def _comment_at(line: str) -> int | None:
    code = _split_comment(line)
    if len(code) < len(line):
        return len(code)
    return None


def _names_re(names: set[str]) -> re.Pattern[str] | None:
    clean = [name for name in names if name]
    if not clean:
        return None
    body = "|".join(re.escape(name) for name in sorted(clean, key=len, reverse=True))
    return re.compile(rf"(?<![{_NAME_EDGE}])(?:{body})(?![{_NAME_EDGE}])")


def _is_type_name(kind: str, shapes: set[str]) -> bool:
    raw = kind.strip()
    return raw in shapes or raw.lower() in _KIND_WORDS


def _declared_id(name_tok: str | None, alias_tok: str | None) -> str | None:
    """Имя объекта: голый идентификатор, а не подпись в кавычках."""
    if not name_tok:
        return None
    token = alias_tok if alias_tok and name_tok.startswith('"') else name_tok
    if not token or token.startswith('"') or is_reserved(token):
        return None
    return token


def _remember(bucket: set[str], token: str | None, skip: set[str]) -> None:
    ident = _declared_id(token, None)
    if ident and ident not in skip:
        bucket.add(ident)


def _relation_ends(text: str) -> tuple[str, str] | None:
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
    left, right = head.group("left"), tail.group("right")
    if not left or not right:
        return None
    return left, right


def _remember_def(bucket: set[str], token: str | None) -> None:
    if token and not token.startswith('"'):
        bucket.add(token)


def _code_lines(text: str):
    """Строки без комментариев: номер и код до хвостового ``'`` / ``//``."""
    in_block = False
    for index, line in enumerate(text.split("\n"), start=1):
        if in_block:
            if "'/" in line:
                in_block = False
            continue
        if "/'" in line and "'/" not in line:
            in_block = True
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("'") or stripped.startswith("//"):
            continue
        yield index, _split_comment(line)


def _collect_symbols(text: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Имена своих видов, связей, объектов и структур."""
    shapes: set[str] = set()
    links: set[str] = set()
    structs: set[str] = set()
    code_lines = list(_code_lines(text))
    for _, code in code_lines:
        shape = SHAPE_HEAD.match(code)
        if shape:
            _remember_def(shapes, shape.group("name"))
            continue
        link = LINK_HEAD.match(code)
        if link:
            _remember_def(links, link.group("name"))
            continue
        defined = STRUCT_HEAD.match(code)
        if defined:
            _remember_def(structs, defined.group("name"))

    skip = shapes | links | structs
    entities: set[str] = set()
    for _, code in code_lines:
        if SHAPE_HEAD.match(code) or LINK_HEAD.match(code) or STRUCT_HEAD.match(code):
            continue
        noted = NOTE_OF.match(code)
        if noted:
            _remember(entities, noted.group("target"), skip)
            continue
        noted = NOTE_AS.match(code)
        if noted:
            _remember(entities, noted.group("alias"), skip)
            continue
        group = _GROUP_RE.match(code)
        if group:
            ident = _declared_id(group.group("a"), group.group("b"))
            if ident and ident not in skip:
                entities.add(ident)
            continue
        ends = _relation_ends(code)
        if ends:
            _remember(entities, ends[0], skip)
            _remember(entities, ends[1], skip)
            continue
        decl = DECL.match(code)
        if decl and _is_type_name(decl.group("kind"), shapes):
            ident = _declared_id(decl.group("name"), decl.group("alias"))
            if ident and ident not in skip:
                entities.add(ident)
            continue
        solo = _SOLO.match(code)
        if solo:
            _remember(entities, solo.group("name"), skip)
    return shapes, links, entities, structs


PALETTES = {
    "light": {
        "bg": "#ffffff", "fg": "#1f2a33", "caret": "#1565c0",
        "gutter_bg": "#f2f4f7", "gutter_fg": "#93a3b1", "current": "#f6f9fc",
        "select": "#cfe3f7", "select_fg": "#10314f",
        "border": "#c6d0d8", "focus": "#1565c0",
        "comment": "#8a9aa6", "directive": "#8e24aa", "kind": "#1565c0",
        "custom": "#00796b", "entity": "#c2185b",
        "string": "#2e7d32", "connector": "#c62828", "color": "#b8860b",
        "param": "#00838f", "stereo": "#6a4fa3", "prop": "#37474f",
        "vis": "#d98324", "error_bg": "#ffe3e3", "warn_bg": "#fff5d6",
        "find_bg": "#ffe08a", "find_fg": "#1f2a33", "find_cur": "#ffb300",
    },
    "dark": {
        "bg": "#1b2127", "fg": "#dde6ee", "caret": "#6fb3f2",
        "gutter_bg": "#151a20", "gutter_fg": "#5d6b78", "current": "#222a32",
        "select": "#2e4256", "select_fg": "#f2f7fb",
        "border": "#3a4650", "focus": "#6fb3f2",
        "comment": "#6c7a87", "directive": "#c792ea", "kind": "#6fb3f2",
        "custom": "#1de9b6", "entity": "#ff80ab",
        "string": "#9fd28c", "connector": "#f28b82", "color": "#e0c179",
        "param": "#6fd8d3", "stereo": "#b39ddb", "prop": "#aebecb",
        "vis": "#f0b254", "error_bg": "#4a2226", "warn_bg": "#463a1c",
        "find_bg": "#6b5420", "find_fg": "#fff8e1", "find_cur": "#c48a12",
    },
}


class CodeEditor(ttk.Frame):
    """Текстовое поле с гуттером, подсветкой и пометками ошибок."""

    def __init__(self, master, on_change=None, on_cursor=None,
                 on_message=None, on_ctrl=None,
                 font_size: int = 11, palette: str = "light") -> None:
        super().__init__(master)
        self._on_change = on_change
        self._on_cursor = on_cursor
        self._on_message = on_message
        self._on_ctrl = on_ctrl
        self._find_on = False
        self._replace_on = False
        self._palette_name = palette
        self.colors = PALETTES[palette]
        self._mono = tkfont.Font(family="Consolas", size=font_size)
        if "Consolas" not in tkfont.families():
            self._mono.configure(family="Courier New")

        self.gutter = tk.Canvas(self, width=52, highlightthickness=0,
                                bg=self.colors["gutter_bg"], takefocus=0)
        self.gutter.pack(side="left", fill="y")

        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self._scroll_y)
        self.vbar.pack(side="right", fill="y")

        holder = ttk.Frame(self)
        holder.pack(side="left", fill="both", expand=True)
        self.hbar = ttk.Scrollbar(holder, orient="horizontal")
        self.hbar.pack(side="bottom", fill="x")

        self.text = tk.Text(
            holder, wrap="none", undo=True, maxundo=-1, autoseparators=True,
            font=self._mono, relief="flat", padx=8, pady=6,
            insertwidth=2, tabs=("1c",),
        )
        self._paint_frame()
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(yscrollcommand=self._on_text_scroll,
                            xscrollcommand=self.hbar.set)
        self.hbar.configure(command=self.text.xview)

        self._make_tags()
        self._build_find_bar()
        self._bind_events()
        self._pending_paint: str | None = None

    # ----------------------------------------------------------- служебное --

    def _make_tags(self) -> None:
        c = self.colors
        self.text.tag_configure("current_line", background=c["current"])
        self.text.tag_configure("comment", foreground=c["comment"])
        self.text.tag_configure("directive", foreground=c["directive"])
        self.text.tag_configure("kind", foreground=c["kind"])
        self.text.tag_configure("custom", foreground=c["custom"])
        self.text.tag_configure("entity", foreground=c["entity"])
        self.text.tag_configure("string", foreground=c["string"])
        self.text.tag_configure("connector", foreground=c["connector"])
        self.text.tag_configure("color", foreground=c["color"])
        self.text.tag_configure("param", foreground=c["param"])
        self.text.tag_configure("stereo", foreground=c["stereo"])
        self.text.tag_configure("prop", foreground=c["prop"])
        self.text.tag_configure("vis", foreground=c["vis"])
        self.text.tag_configure("error_line", background=c["error_bg"])
        self.text.tag_configure("warn_line", background=c["warn_bg"])
        self.text.tag_configure("find_hit", background=c["find_bg"],
                                foreground=c["find_fg"])
        self.text.tag_configure("find_current", background=c["find_cur"],
                                foreground=c["find_fg"])
        for name in ("prop", "vis", "connector", "entity", "directive",
                     "kind", "custom", "stereo", "color", "param",
                     "string", "comment"):
            self.text.tag_raise(name)
        self.text.tag_lower("current_line")
        self.text.tag_lower("error_line")
        self.text.tag_lower("warn_line")

    def _bind_events(self) -> None:
        self.text.bind("<KeyRelease>", self._changed)
        self.text.bind("<<Paste>>", lambda e: self.after(10, self._changed))
        self.text.bind("<<Cut>>", lambda e: self.after(10, self._changed))
        self.text.bind("<<Undo>>", lambda e: self.after(10, self._changed))
        self.text.bind("<<Redo>>", lambda e: self.after(10, self._changed))
        self.text.bind("<ButtonRelease-1>", self._cursor_moved)
        self.text.bind("<Configure>", lambda e: self._paint_gutter())
        self.text.bind("<MouseWheel>", self._wheel)
        self.text.bind("<Return>", self._auto_indent)
        self.text.bind("<Tab>", self._insert_tab)
        self.text.bind("<Shift-Tab>", self._unindent)
        self._bind_shortcuts(self.text)
        self.text.bind("<F2>", self._on_rename_key)
        self.text.bind("<Escape>", self._on_escape)

    def _scroll_y(self, *args) -> None:
        self.text.yview(*args)
        self._paint_gutter()

    def _on_text_scroll(self, first, last) -> None:
        self.vbar.set(first, last)
        self._paint_gutter()

    def _wheel(self, event) -> str | None:
        if event.state & 0x0004:      # Ctrl
            self.change_font_size(1 if event.delta > 0 else -1)
            return "break"
        self.text.yview_scroll(-1 * (event.delta // 120), "units")
        self._paint_gutter()
        return "break"

    # -------------------------------------------------------------- ввод ----

    def _auto_indent(self, event) -> str:
        line = self.text.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith("{"):
            indent += "  "
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        self._changed()
        return "break"

    def _insert_tab(self, event) -> str:
        if self.text.tag_ranges("sel"):
            self._shift_selection("  ")
        else:
            self.text.insert("insert", "  ")
        self._changed()
        return "break"

    def _unindent(self, event) -> str:
        first = int(self.text.index("sel.first").split(".")[0]) \
            if self.text.tag_ranges("sel") else \
            int(self.text.index("insert").split(".")[0])
        last = int(self.text.index("sel.last").split(".")[0]) \
            if self.text.tag_ranges("sel") else first
        for line in range(first, last + 1):
            start = f"{line}.0"
            prefix = self.text.get(start, f"{line}.2")
            if prefix == "  ":
                self.text.delete(start, f"{line}.2")
            elif prefix[:1] in (" ", "\t"):
                self.text.delete(start, f"{line}.1")
        self._changed()
        return "break"

    def _shift_selection(self, prefix: str) -> None:
        first = int(self.text.index("sel.first").split(".")[0])
        last = int(self.text.index("sel.last").split(".")[0])
        for line in range(first, last + 1):
            self.text.insert(f"{line}.0", prefix)

    def toggle_comments(self) -> None:
        """Закомментировать выделенные строки или текущую. Повтор снимает пометку."""
        had_sel = bool(self.text.tag_ranges("sel"))
        first, last = self._comment_span()
        row_s, col_s = self.text.index("insert").split(".")
        row, col = int(row_s), int(col_s)
        lines = [self.text.get(f"{n}.0", f"{n}.end") for n in range(first, last + 1)]
        uncomment = _should_uncomment(lines)
        cursor_line = lines[row - first] if first <= row <= last else None

        self._begin_edit()
        try:
            for offset, line in enumerate(lines):
                updated = _uncomment_line(line) if uncomment else _comment_line(line)
                if updated == line:
                    continue
                n = first + offset
                self.text.delete(f"{n}.0", f"{n}.end")
                self.text.insert(f"{n}.0", updated)
        finally:
            self._end_edit()

        self.text.tag_remove("sel", "1.0", "end")
        if had_sel:
            self.text.tag_add("sel", f"{first}.0", f"{last}.end")
            self.text.mark_set("insert", f"{last}.end")
        elif cursor_line is not None:
            updated = _uncomment_line(cursor_line) if uncomment else _comment_line(cursor_line)
            self.text.mark_set("insert", f"{row}.{_shifted_column(cursor_line, updated, col)}")
        self.text.see("insert")
        self._changed()

    def _comment_span(self) -> tuple[int, int]:
        """Строки выделения. Курсор в начале следующей строки в диапазон не входит."""
        if not self.text.tag_ranges("sel"):
            line = int(self.text.index("insert").split(".")[0])
            return line, line
        first = int(self.text.index("sel.first").split(".")[0])
        last_line, last_col = self.text.index("sel.last").split(".")
        last = int(last_line)
        if last_col == "0" and last > first:
            last -= 1
        return first, last

    def _changed(self, event=None) -> None:
        self.schedule_paint()
        self._cursor_moved()
        if self._on_change:
            self._on_change()

    def _cursor_moved(self, event=None) -> None:
        self.text.tag_remove("current_line", "1.0", "end")
        self.text.tag_add("current_line", "insert linestart",
                          "insert lineend+1c")
        if self._on_cursor:
            row, col = self.text.index("insert").split(".")
            self._on_cursor(int(row), int(col) + 1)

    # ---------------------------------------------------------- интерфейс --

    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_text(self, value: str, keep_undo: bool = False) -> None:
        if not keep_undo:
            self.text.configure(undo=False)
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        if not keep_undo:
            self.text.configure(undo=True)
            self.text.edit_reset()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self.schedule_paint()
        self._cursor_moved()

    def insert_snippet(self, snippet: str) -> None:
        line = self.text.get("insert linestart", "insert lineend")
        prefix = "" if not line.strip() else "\n"
        self.text.insert("insert lineend", prefix + snippet)
        self.text.mark_set("insert", f"insert+{len(snippet)}c")
        self.text.see("insert")
        self._changed()

    def goto_line(self, line: int) -> None:
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{max(1, line - 2)}.0")
        self.text.focus_set()
        self._cursor_moved()

    def change_font_size(self, delta: int) -> None:
        size = max(7, min(28, self._mono.cget("size") + delta))
        self._mono.configure(size=size)
        self._paint_gutter()

    def font_size(self) -> int:
        return int(self._mono.cget("size"))

    def set_palette(self, name: str) -> None:
        if name not in PALETTES:
            name = "light"
        self._palette_name = name
        self.colors = PALETTES[name]
        self._paint_frame()
        self.gutter.configure(bg=self.colors["gutter_bg"])
        self._make_tags()
        self._paint_find_status()
        self.paint()

    def _paint_frame(self) -> None:
        """Фон, курсор, выделение и обводка фокуса текстового поля."""
        c = self.colors
        self.text.configure(bg=c["bg"], fg=c["fg"],
                            insertbackground=c["caret"],
                            selectbackground=c["select"],
                            selectforeground=c["select_fg"],
                            highlightthickness=1,
                            highlightbackground=c["border"],
                            highlightcolor=c["focus"])

    def mark_diagnostics(self, diagnostics) -> None:
        self.text.tag_remove("error_line", "1.0", "end")
        self.text.tag_remove("warn_line", "1.0", "end")
        for item in diagnostics:
            if item.line <= 0:
                continue
            tag = "error_line" if item.severity == "error" else "warn_line"
            self.text.tag_add(tag, f"{item.line}.0", f"{item.line}.end+1c")
        self._paint_gutter(diagnostics)

    # ------------------------------------------------------------ подсветка --

    def schedule_paint(self) -> None:
        if self._pending_paint:
            self.after_cancel(self._pending_paint)
        self._pending_paint = self.after(90, self.paint)

    def paint(self) -> None:
        self._pending_paint = None
        for tag in ("comment", "directive", "kind", "custom", "entity",
                    "string", "connector", "color", "param", "stereo",
                    "prop", "vis"):
            self.text.tag_remove(tag, "1.0", "end")
        source = self.get_text()
        shapes, links, entities, structs = _collect_symbols(source)
        custom_re = _names_re(shapes | links | structs)
        entity_re = _names_re(entities)
        in_block = False
        for index, line in enumerate(source.split("\n"), start=1):
            if in_block:
                self._tag(index, 0, len(line), "comment")
                if "'/" in line:
                    in_block = False
                continue
            if "/'" in line and "'/" not in line:
                in_block = True
                self._tag(index, 0, len(line), "comment")
                continue
            stripped = line.strip()
            if stripped.startswith("'") or stripped.startswith("//"):
                self._tag(index, 0, len(line), "comment")
                continue
            self._paint_line(index, line, custom_re, entity_re, structs)
        self.text.tag_raise("find_hit")
        self.text.tag_raise("find_current")
        self._paint_gutter()

    def _paint_line(
        self,
        index: int,
        line: str,
        custom_re: re.Pattern[str] | None,
        entity_re: re.Pattern[str] | None,
        structs: set[str],
    ) -> None:
        comment_at = _comment_at(line)
        if comment_at is not None:
            self._tag(index, comment_at, len(line), "comment")
        directive = DIRECTIVE_RE.match(line)
        if directive:
            self._tag(index, directive.start(1), directive.end(1), "directive")
        kind = KIND_RE.match(line)
        if kind:
            self._tag(index, kind.start(), kind.end(), "kind")
        for match in _EXTENDS_BASE.finditer(line):
            base = match.group("base")
            if base.lower() in _KIND_WORDS or base.lower() in _LINK_WORDS:
                self._tag(index, match.start("base"), match.end("base"), "kind")
        if PROPERTY_RE.match(line) and ":" in line:
            self._tag(index, 0, line.index(":"), "prop")
        vis = VISIBILITY_RE.match(line)
        if vis:
            self._tag(index, vis.start(), vis.end(), "vis")
        for match in STRING_RE.finditer(line):
            self._tag(index, match.start(), match.end(), "string")
        for match in STEREO_RE.finditer(line):
            self._tag(index, match.start(), match.end(), "stereo")
        for match in COLOR_RE.finditer(line):
            self._tag(index, match.start(), match.end(), "color")
        for match in PARAM_RE.finditer(line):
            self._tag(index, match.start(), match.end(), "param")
        for match in KEYWORD_RE.finditer(line):
            self._tag(index, match.start(), match.end(), "directive")
        for match in CONNECTOR_RE.finditer(line):
            if not match.group(2):
                continue
            if line.strip().startswith(("'", "//")):
                continue
            self._tag(index, match.start(), match.end(), "connector")
            bracket = match.group(3)
            if not bracket:
                continue
            origin = match.start(3) + 1
            for word in _WORD.finditer(bracket[1:-1]):
                if word.group().lower() in _LINK_WORDS:
                    self._tag(index, origin + word.start(),
                              origin + word.end(), "kind")
        if custom_re is not None:
            for match in custom_re.finditer(line):
                self._tag(index, match.start(), match.end(), "custom")
        if entity_re is not None:
            for match in entity_re.finditer(line):
                self._tag(index, match.start(), match.end(), "entity")
        self._paint_struct_params(index, _split_comment(line), structs)

    def _paint_struct_params(self, index: int, code: str, structs: set[str]) -> None:
        """Параметры ``struct Имя(А, Б)`` и аргументы вызова структуры."""
        defined = STRUCT_HEAD.match(code)
        if defined:
            self._tag_words(index, defined, "params", "param")
            return
        call = USE_CALL.match(code)
        if call and call.group("name") in structs:
            self._tag_words(index, call, "args", "param")

    def _tag_words(self, index: int, match: re.Match[str], group: str, tag: str) -> None:
        inner = match.group(group) or ""
        origin = match.start(group)
        for word in _WORD.finditer(inner):
            self._tag(index, origin + word.start(), origin + word.end(), tag)

    def _tag(self, line: int, start: int, end: int, tag: str) -> None:
        if end <= start:
            return
        self.text.tag_add(tag, f"{line}.{start}", f"{line}.{end}")

    # ---------------------------------------------------- поиск и замена ---

    def _build_find_bar(self) -> None:
        self._find_var = tk.StringVar()
        self._replace_var = tk.StringVar()
        self._case_var = tk.BooleanVar(value=False)
        self._find_status = tk.StringVar(value="")
        bar = ttk.Frame(self, padding=(8, 4))
        self._find_bar = bar

        row = ttk.Frame(bar)
        row.pack(fill="x")
        ttk.Label(row, text="Найти").pack(side="left")
        self._find_entry = ttk.Entry(row, textvariable=self._find_var, width=28)
        self._find_entry.pack(side="left", padx=(6, 4))
        next_btn = ttk.Button(row, text="Далее", command=self.find_next, width=8)
        next_btn.pack(side="left")
        prev_btn = ttk.Button(row, text="Назад", command=self.find_prev, width=8)
        prev_btn.pack(side="left", padx=(4, 0))
        case = ttk.Checkbutton(row, text="регистр", variable=self._case_var,
                               command=self._mark_matches)
        case.pack(side="left", padx=(8, 0))
        close = ttk.Button(row, text="×", width=3, command=self.close_find)
        close.pack(side="right")
        self._find_status_label = ttk.Label(row, textvariable=self._find_status)
        self._find_status_label.pack(side="right", padx=(0, 8))

        replace = ttk.Frame(bar)
        self._replace_row = replace
        ttk.Label(replace, text="Заменить").pack(side="left")
        self._replace_entry = ttk.Entry(replace, textvariable=self._replace_var,
                                        width=28)
        self._replace_entry.pack(side="left", padx=(6, 4))
        one = ttk.Button(replace, text="Заменить", command=self.replace_one,
                         width=10)
        one.pack(side="left")
        every = ttk.Button(replace, text="Все", command=self.replace_all, width=6)
        every.pack(side="left", padx=(4, 0))

        tooltip.attach(self._find_entry, "Текст поиска  ·  Enter — далее, "
                                          "Shift+Enter — назад, Esc — закрыть")
        tooltip.attach(next_btn, "Следующее совпадение  ·  Enter")
        tooltip.attach(prev_btn, "Предыдущее совпадение  ·  Shift+Enter")
        tooltip.attach(case, "Различать заглавные и строчные буквы")
        tooltip.attach(close, "Закрыть панель поиска  ·  Esc")
        tooltip.attach(self._replace_entry, "На что заменить текущее совпадение")
        tooltip.attach(one, "Заменить текущее совпадение и перейти к следующему")
        tooltip.attach(every, "Заменить все совпадения в тексте")

        self._find_entry.bind("<Return>", lambda e: self.find_next() or "break")
        self._find_entry.bind("<Shift-Return>", lambda e: self.find_prev() or "break")
        self._find_entry.bind("<Escape>", lambda e: self.close_find() or "break")
        self._replace_entry.bind("<Return>", lambda e: self.replace_one() or "break")
        self._replace_entry.bind("<Escape>", lambda e: self.close_find() or "break")
        self._bind_shortcuts(self._find_entry)
        self._bind_shortcuts(self._replace_entry)
        self._find_var.trace_add("write", lambda *_: self._mark_matches())
        self._case_var.trace_add("write", lambda *_: self._mark_matches())
        self._paint_find_status()

    def _paint_find_status(self) -> None:
        muted = ui_colors(self._palette_name)["muted"]
        self._find_status_label.configure(foreground=muted)

    def open_find(self) -> None:
        """Показать поиск. Повторное Ctrl+F в поле ищет следующее."""
        if (self._find_on and not self._replace_on
                and self.focus_get() is self._find_entry):
            self.find_next()
            return
        self._show_find(replace=False)

    def open_replace(self) -> None:
        """Показать поиск с заменой. Повторное Ctrl+H ищет следующее."""
        focused = self.focus_get() in (self._find_entry, self._replace_entry)
        if self._find_on and self._replace_on and focused:
            self.find_next()
            return
        self._show_find(replace=True)

    def _show_find(self, replace: bool) -> None:
        self._replace_on = replace
        if replace:
            self._replace_row.pack(fill="x", pady=(4, 0))
        else:
            self._replace_row.pack_forget()
        if not self._find_on:
            self._find_bar.pack(side="top", fill="x", before=self.gutter)
            self._find_on = True
        selected = self._plain_selection()
        if selected is not None and "\n" not in selected and len(selected) <= 80:
            self._find_var.set(selected)
        self._find_entry.focus_set()
        self._find_entry.selection_range(0, "end")
        self._find_entry.icursor("end")
        self._mark_matches()

    def close_find(self) -> None:
        if not self._find_on:
            return
        self._find_on = False
        self._replace_on = False
        self._find_bar.pack_forget()
        self._replace_row.pack_forget()
        self.text.tag_remove("find_hit", "1.0", "end")
        self.text.tag_remove("find_current", "1.0", "end")
        self._find_status.set("")
        self.text.focus_set()

    def find_next(self) -> None:
        self._find(backwards=False)

    def find_prev(self) -> None:
        self._find(backwards=True)

    def _find(self, backwards: bool) -> None:
        needle = self._find_var.get()
        if not needle:
            self._find_status.set("Введите текст")
            return
        ranges = self._match_ranges(needle)
        if not ranges:
            self._find_status.set("Не найдено")
            self._mark_matches()
            return
        if backwards:
            origin = self.text.index("insert")
            if self.text.tag_ranges("sel"):
                origin = self.text.index("sel.first")
            earlier = [pair for pair in ranges
                       if self.text.compare(pair[0], "<", origin)]
            chosen = earlier[-1] if earlier else ranges[-1]
        else:
            origin = self.text.index("insert")
            later = [pair for pair in ranges
                     if self.text.compare(pair[0], ">=", origin)]
            chosen = later[0] if later else ranges[0]
        start, end = chosen
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", start, end)
        self.text.mark_set("insert", start if backwards else end)
        self.text.see(start)
        self._cursor_moved()
        number = ranges.index(chosen) + 1
        self._find_status.set(f"{number} из {len(ranges)}")
        self._mark_matches(current=start)

    def replace_one(self) -> None:
        needle = self._find_var.get()
        if not needle:
            self._find_status.set("Введите текст")
            return
        if not self._selection_is(needle):
            self.find_next()
            if not self._selection_is(needle):
                return
        self._begin_edit()
        try:
            self.text.delete("sel.first", "sel.last")
            self.text.insert("insert", self._replace_var.get())
        finally:
            self._end_edit()
        self._changed()
        self.find_next()

    def replace_all(self) -> None:
        needle = self._find_var.get()
        if not needle:
            self._find_status.set("Введите текст")
            return
        repl = self._replace_var.get()
        ranges = self._match_ranges(needle)
        if not ranges:
            self._find_status.set("Не найдено")
            return
        self._begin_edit()
        try:
            for start, end in reversed(ranges):
                self.text.delete(start, end)
                self.text.insert(start, repl)
        finally:
            self._end_edit()
        self._find_status.set(f"Заменено: {len(ranges)}")
        self._changed()
        self._mark_matches()

    def _plain_selection(self) -> str | None:
        if not self.text.tag_ranges("sel"):
            return None
        return self.text.get("sel.first", "sel.last")

    def _selection_is(self, needle: str) -> bool:
        selected = self._plain_selection()
        if selected is None:
            return False
        if self._case_var.get():
            return selected == needle
        return selected.lower() == needle.lower()

    def _match_ranges(self, needle: str) -> list[tuple[str, str]]:
        ranges: list[tuple[str, str]] = []
        if not needle:
            return ranges
        nocase = not self._case_var.get()
        start = "1.0"
        while True:
            idx = self.text.search(needle, start, nocase=nocase, stopindex="end")
            if not idx:
                break
            end = self.text.index(f"{idx}+{len(needle)}c")
            if self.text.compare(end, "<=", idx):
                break
            ranges.append((idx, end))
            start = end
        return ranges

    def _mark_matches(self, current: str | None = None) -> None:
        self.text.tag_remove("find_hit", "1.0", "end")
        self.text.tag_remove("find_current", "1.0", "end")
        if not self._find_on:
            return
        needle = self._find_var.get()
        ranges = self._match_ranges(needle)
        for start, end in ranges:
            tag = "find_current" if current and start == current else "find_hit"
            self.text.tag_add(tag, start, end)
        self.text.tag_raise("find_hit")
        self.text.tag_raise("find_current")
        if not needle:
            self._find_status.set("")
        elif not ranges:
            self._find_status.set("Не найдено")
        elif current is None:
            self._find_status.set(f"найдено: {len(ranges)}")

    # ------------------------------------------------------- переименование --

    def rename_symbol(self) -> None:
        """Спросить новое имя и заменить все вхождения имени под курсором."""
        name, error = self._current_name()
        if not name:
            self._tell(error or "Выделите имя объекта или поставьте на него курсор")
            return
        if is_reserved(name):
            self._tell(f"«{name}» — служебное слово, его нельзя переименовать")
            return
        count = len(name_spans(self.get_text(), name))
        if count == 0:
            self._tell(f"Имя «{name}» в тексте не найдено")
            return
        new = _ask_rename(self.winfo_toplevel(), name, count, self._palette_name)
        if new is None or new.strip() == name:
            return
        replaced, problem = self.replace_name(name, new.strip())
        if problem:
            self._tell(problem)
            return
        self._tell(f"«{name}» → «{new.strip()}», {places(replaced)}")

    def replace_name(self, old: str, new: str) -> tuple[int, str]:
        """Заменяет все вхождения. Возвращает число замен и текст ошибки."""
        text = self.get_text()
        plan, error = plan_rename(text, old, new)
        if error or not plan:
            return 0, error
        self._begin_edit()
        try:
            for start, end, value in reversed(plan):
                self.text.delete(index_at(text, start), index_at(text, end))
                self.text.insert(index_at(text, start), value)
        finally:
            self._end_edit()
        first = plan[0]
        cursor = index_at(text, first[0])
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", cursor, f"{cursor}+{len(first[2])}c")
        self.text.mark_set("insert", f"{cursor}+{len(first[2])}c")
        self.text.see(cursor)
        self._changed()
        return len(plan), ""

    def _current_name(self) -> tuple[str | None, str]:
        if self.text.tag_ranges("sel"):
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
            selected = self.text.get(start, end)
            if "\n" in selected:
                return None, "Имя должно быть на одной строке"
            core = selected.strip()
            if not core:
                return None, "Выделите имя объекта"
            leading = len(selected) - len(selected.lstrip())
            trailing = len(selected) - len(selected.rstrip())
            core_start = self.text.index(f"{start}+{leading}c")
            core_end = self.text.index(f"{end}-{trailing}c") if trailing else end
            before = self.text.get(f"{core_start}-1c", core_start)
            after = self.text.get(core_end, f"{core_end}+1c")
            name = name_from_selection(core, before, after)
            if name:
                return name, ""
            if continues_name(before[-1:]) or continues_name(after[:1]):
                return None, "Выделите имя целиком"
            return None, "Выделите имя объекта или поставьте на него курсор"
        line_no = self.text.index("insert").split(".")[0]
        column = int(self.text.index("insert").split(".")[1])
        line = self.text.get(f"{line_no}.0", f"{line_no}.end")
        name = name_on_line(line, column)
        if name:
            return name, ""
        return None, "Поставьте курсор на имя объекта или выделите его"

    def _on_rename_key(self, event=None) -> str:
        self.rename_symbol()
        return "break"

    def _on_escape(self, event=None) -> str | None:
        if self._find_on:
            self.close_find()
            return "break"
        return None

    def _bind_shortcuts(self, widget) -> None:
        """Ловит Ctrl+клавиша и на латинице, и на русской раскладке Windows."""
        widget.bind("<KeyPress>", self._on_any_key)
        widget.bind("<Control-KeyPress>", self._on_ctrl_key)
        for sequence in (
            "<Control-h>", "<Control-H>",
            "<Control-slash>", "<Control-question>", "<Control-KP_Divide>",
            "<Control-Shift-z>", "<Control-Shift-Z>",
            "<Control-Shift-Key-z>", "<Control-Shift-Key-Z>",
        ):
            self._safe_bind(widget, sequence, self._on_ctrl_key)
        for name in hotkeys.layout_keysyms():
            self._safe_bind(widget, f"<Control-{name}>", self._on_ctrl_key)
            self._safe_bind(widget, f"<Control-Shift-{name}>", self._on_ctrl_key)

    @staticmethod
    def _safe_bind(widget, sequence: str, handler) -> None:
        try:
            widget.bind(sequence, handler)
        except tk.TclError:
            pass

    def _on_any_key(self, event):
        if not hotkeys.control_down(event) or hotkeys.is_modifier(event):
            return None
        return self._on_ctrl_key(event)

    def _on_ctrl_key(self, event) -> str | None:
        if self._on_ctrl and self._on_ctrl(event):
            return "break"
        return None

    def _tell(self, message: str) -> None:
        if message and self._on_message:
            self._on_message(message)

    def _begin_edit(self) -> None:
        self.text.edit_separator()
        self.text.configure(autoseparators=False)

    def _end_edit(self) -> None:
        self.text.configure(autoseparators=True)
        self.text.edit_separator()

    def select_all(self) -> None:
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        self.text.see("insert")

    # -------------------------------------------------------------- гуттер --

    def _paint_gutter(self, diagnostics=None) -> None:
        canvas = self.gutter
        canvas.delete("all")
        if diagnostics is not None:
            self._diag_lines = {d.line: d.severity for d in diagnostics
                                if d.line > 0}
        marks = getattr(self, "_diag_lines", {})
        colors = self.colors
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            y = info[1]
            number = index.split(".")[0]
            severity = marks.get(int(number))
            if severity:
                fill = "#d64545" if severity == "error" else "#c08c1f"
                canvas.create_oval(6, y + 6, 13, y + 13, fill=fill, outline="")
            canvas.create_text(46, y, anchor="ne", text=number,
                               fill=colors["gutter_fg"], font=self._mono)
            index = self.text.index(f"{index}+1line")
            if self.text.compare(index, ">", "end-1c"):
                break


def _ask_rename(parent: tk.Misc, old: str, count: int, palette: str) -> str | None:
    """Модальный ввод нового имени. None — отмена."""
    dialog = tk.Toplevel(parent)
    dialog.title("Переименовать")
    dialog.transient(parent)
    dialog.resizable(False, False)
    c = ui_colors(palette)
    dialog.configure(background=c["bg"])
    native.apply_chrome(dialog, palette == "dark", c["bg"], c["fg"])
    result: dict[str, str | None] = {"value": None}

    frame = ttk.Frame(dialog, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=f"Новое имя для «{old}»").pack(anchor="w")
    ttk.Label(frame, text=f"Будет заменено {places(count)}",
              foreground=c["muted"]).pack(anchor="w", pady=(2, 8))
    value = tk.StringVar(value=old)
    entry = ttk.Entry(frame, textvariable=value, width=36)
    entry.pack(fill="x")
    error = ttk.Label(frame, text="", foreground="#c62828")
    error.pack(anchor="w", pady=(4, 0))

    def accept(_event=None) -> str:
        text = value.get().strip()
        if not text:
            error.configure(text="Введите новое имя")
            return "break"
        if text == old:
            dialog.destroy()
            return "break"
        result["value"] = text
        dialog.destroy()
        return "break"

    def cancel(_event=None) -> None:
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="Отмена", command=cancel).pack(side="right")
    ok = ttk.Button(buttons, text="Переименовать", command=accept)
    ok.pack(side="right", padx=(0, 8))
    entry.bind("<Return>", accept)
    dialog.bind("<Escape>", lambda e: cancel())
    dialog.protocol("WM_DELETE_WINDOW", cancel)
    dialog.update_idletasks()
    dialog.geometry(f"+{parent.winfo_rootx() + 80}+{parent.winfo_rooty() + 80}")
    dialog.grab_set()
    entry.focus_set()
    entry.selection_range(0, "end")
    entry.icursor("end")
    dialog.wait_window()
    return result["value"]
