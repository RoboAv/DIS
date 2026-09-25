"""Текстовый редактор с нумерацией строк и подсветкой синтаксиса."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..theme import KIND_DEFAULTS

BLOCK_KEYWORDS = ("shape", "link", "struct", "use", "package", "namespace",
                  "group", "frame", "rectangle", "note", "end note", "endlegend",
                  "legend", "title", "caption", "footer", "set", "theme",
                  "direction", "hide", "as", "extends", "of")

DIRECTIVE_RE = re.compile(
    r"^\s*(@\w+|" + "|".join(sorted(BLOCK_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
KIND_RE = re.compile(
    r"^\s*(?:" + "|".join(sorted(KIND_DEFAULTS, key=len, reverse=True)) +
    r"|abstract\s+class)\b",
    re.IGNORECASE,
)
CONNECTOR_RE = re.compile(r"(<\|?|[*o+x#}{])?(-{1,4}|\.{2,4}|={2,4}|~{2,4})"
                          r"(\[[^\]]*\])?(-{0,4}|\.{0,4}|={0,4}|~{0,4})(\|>|[>*o+x#}{])?")
STRING_RE = re.compile(r'"[^"\n]*"')
COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
PARAM_RE = re.compile(r"\$\{?[\w\u0400-\u04FF]+\}?")
STEREO_RE = re.compile(r"<<[^>\n]*>>")
PROPERTY_RE = re.compile(r"^\s*[\w\u0400-\u04FF-]+\s*:")
VISIBILITY_RE = re.compile(r"^\s*(\{\s*\w+\s*\}\s*)*[-+#~]")

PALETTES = {
    "light": {
        "bg": "#ffffff", "fg": "#1f2a33", "caret": "#1565c0",
        "gutter_bg": "#f2f4f7", "gutter_fg": "#93a3b1", "current": "#f6f9fc",
        "select": "#cfe3f7", "select_fg": "#10314f",
        "border": "#c6d0d8", "focus": "#1565c0",
        "comment": "#8a9aa6", "directive": "#8e24aa", "kind": "#1565c0",
        "string": "#2e7d32", "connector": "#c62828", "color": "#b8860b",
        "param": "#00838f", "stereo": "#6a4fa3", "prop": "#37474f",
        "vis": "#d98324", "error_bg": "#ffe3e3", "warn_bg": "#fff5d6",
    },
    "dark": {
        "bg": "#1b2127", "fg": "#dde6ee", "caret": "#6fb3f2",
        "gutter_bg": "#151a20", "gutter_fg": "#5d6b78", "current": "#222a32",
        "select": "#2e4256", "select_fg": "#f2f7fb",
        "border": "#3a4650", "focus": "#6fb3f2",
        "comment": "#6c7a87", "directive": "#c792ea", "kind": "#6fb3f2",
        "string": "#9fd28c", "connector": "#f28b82", "color": "#e0c179",
        "param": "#6fd8d3", "stereo": "#b39ddb", "prop": "#aebecb",
        "vis": "#f0b254", "error_bg": "#4a2226", "warn_bg": "#463a1c",
    },
}


class CodeEditor(ttk.Frame):
    """Текстовое поле с гуттером, подсветкой и пометками ошибок."""

    def __init__(self, master, on_change=None, on_cursor=None,
                 font_size: int = 11, palette: str = "light") -> None:
        super().__init__(master)
        self._on_change = on_change
        self._on_cursor = on_cursor
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
        self._bind_events()
        self._pending_paint: str | None = None

    # ----------------------------------------------------------- служебное --

    def _make_tags(self) -> None:
        c = self.colors
        self.text.tag_configure("current_line", background=c["current"])
        self.text.tag_configure("comment", foreground=c["comment"])
        self.text.tag_configure("directive", foreground=c["directive"])
        self.text.tag_configure("kind", foreground=c["kind"])
        self.text.tag_configure("string", foreground=c["string"])
        self.text.tag_configure("connector", foreground=c["connector"])
        self.text.tag_configure("color", foreground=c["color"])
        self.text.tag_configure("param", foreground=c["param"])
        self.text.tag_configure("stereo", foreground=c["stereo"])
        self.text.tag_configure("prop", foreground=c["prop"])
        self.text.tag_configure("vis", foreground=c["vis"])
        self.text.tag_configure("error_line", background=c["error_bg"])
        self.text.tag_configure("warn_line", background=c["warn_bg"])
        for name in ("comment", "directive", "kind", "string", "connector"):
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
        for tag in ("comment", "directive", "kind", "string", "connector",
                    "color", "param", "stereo", "prop", "vis"):
            self.text.tag_remove(tag, "1.0", "end")
        source = self.get_text()
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
            self._paint_line(index, line)
        self._paint_gutter()

    def _paint_line(self, index: int, line: str) -> None:
        directive = DIRECTIVE_RE.match(line)
        if directive:
            self._tag(index, directive.start(1), directive.end(1), "directive")
        kind = KIND_RE.match(line)
        if kind:
            self._tag(index, kind.start(), kind.end(), "kind")
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
        for match in CONNECTOR_RE.finditer(line):
            if not match.group(2):
                continue
            if line.strip().startswith(("'", "//")):
                continue
            self._tag(index, match.start(), match.end(), "connector")

    def _tag(self, line: int, start: int, end: int, tag: str) -> None:
        if end <= start:
            return
        self.text.tag_add(tag, f"{line}.{start}", f"{line}.{end}")

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
