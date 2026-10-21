"""Главное окно UML Studio."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, api
from ..parser import parse
from ..positions import (
    clear_edge_end,
    clear_edge_waypoints,
    edge_ordinal,
    schema_text,
    set_edge_end,
    set_edge_geometry,
    set_edge_label_offset,
    set_edge_waypoints,
    set_node_ports,
    set_node_position,
)
from . import native, tooltip
from .dialogs import HelpWindow, LinkDesigner, ShapeDesigner, StructDesigner
from . import hotkeys
from .editor import CodeEditor
from .examples import EXAMPLES, STARTER
from .palette import colors as ui_colors
from .palette import paint_popdowns
from .preview import Preview
from .scene import InteractiveCanvas

FILE_TYPES = [
    ("Диаграмма UML Studio", "*.uml"),
    ("PlantUML", "*.puml *.plantuml *.iuml"),
    ("Текстовый файл", "*.txt"),
    ("Все файлы", "*.*"),
]

DIAGRAM_THEMES = ("light", "dark", "mono", "blueprint")

SNIPPETS: dict[str, str] = {
    "Класс": """class НовыйКласс {
  + поле: string
  - скрытое: int
  --
  + метод(аргумент): bool
}""",
    "Интерфейс": """interface НовыйИнтерфейс {
  + операция(): void
}""",
    "Перечисление": """enum Состояние {
  ПЕРВОЕ
  ВТОРОЕ
}""",
    "Сущность": """entity Сущность {
  + id: uuid
  + название: string
}""",
    "Пакет": """package "Новый пакет" {
  class Внутри
}""",
    "Заметка": """note right of ОбъектA
  поясняющий текст
end note""",
    "Набор связей": """A --> B : ассоциация
A <|-- C : наследование
A ..> D : зависимость
A "1" *-- "0..*" E : композиция""",
    "Заголовок и легенда": """title Заголовок диаграммы
caption подпись под картинкой

legend
пояснение к обозначениям
endlegend""",
    "Настройки оформления": """set theme = light
set direction = TB
set node_sep = 44
set rank_sep = 68
set shadow = on""",
}


@dataclass
class _Job:
    seq: int
    text: str
    scale: float
    theme: str
    honor_manual: bool = True
    interactive: bool = False


class RenderWorker:
    """Фоновый поток отрисовки: в работе всегда только последняя заявка."""

    def __init__(self) -> None:
        self._pending: _Job | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._results: queue.Queue = queue.Queue()
        self._alive = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, job: _Job) -> None:
        with self._lock:
            self._pending = job
        self._wake.set()

    def poll(self):
        try:
            return self._results.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._alive = False
        self._wake.set()

    def _loop(self) -> None:
        while self._alive:
            self._wake.wait(0.25)
            with self._lock:
                job = self._pending
                self._pending = None
                self._wake.clear()
            if job is None:
                continue
            try:
                if job.interactive:
                    result = api.layout_only(job.text, theme=job.theme,
                                             honor_manual=job.honor_manual)
                else:
                    result = api.build(job.text, scale=job.scale, supersample=2,
                                       theme=job.theme,
                                       honor_manual=job.honor_manual)
            except Exception:
                result = api.RenderResult(error=traceback.format_exc(limit=3))
            self._results.put((job, result))


class App(tk.Tk):
    """Редактор текста диаграммы с постоянным предпросмотром PNG."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.title("UML Studio")
        self.geometry("1360x860")
        self.minsize(900, 600)

        self.settings = _load_settings()
        self.path: Path | None = None
        self.dirty = False
        self.ui_palette = self.settings.get("ui_palette", "light")
        self._base_theme: str | None = None
        self.diagram_theme = tk.StringVar(
            value=self.settings.get("diagram_theme", "light"))
        self.auto_render = tk.BooleanVar(
            value=bool(self.settings.get("auto_render", True)))
        self.export_scale = tk.IntVar(value=int(self.settings.get("export_scale", 2)))
        self.show_problems = tk.BooleanVar(value=True)
        self.interactive = tk.BooleanVar(
            value=bool(self.settings.get("interactive", False)))
        self.positions_locked = tk.BooleanVar(
            value=bool(self.settings.get("positions_locked", True)))
        self.last_result: api.RenderResult | None = None
        self._diagram = None
        self._schema_key: str | None = None
        self._honor = True
        self._position_edit = False
        self._seq = 0
        self._applied_seq = -1
        self._render_after: str | None = None
        self._busy = False

        self.worker = RenderWorker()
        self._build_ui()
        self._bind_keys()
        self._apply_ui_palette(self.ui_palette)
        self._sync_lock_caption()
        if self.interactive.get():
            self._show_mode(render=False)

        if path:
            self._load_file(Path(path))
        else:
            self.editor.set_text(STARTER)
            self._set_title()
        self.after(80, self._poll_worker)
        self.render_now()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------- интерфейс ---

    def _build_ui(self) -> None:
        self._build_menu()

        self.toolbar = ttk.Frame(self, padding=(8, 6))
        self.toolbar.pack(side="top", fill="x")
        self._build_toolbar()

        self.status = ttk.Frame(self, padding=(10, 4))
        self.status.pack(side="bottom", fill="x")
        self.status_text = ttk.Label(self.status, text="Готово")
        self.status_text.pack(side="left")
        self.cursor_text = ttk.Label(self.status, text="строка 1, столбец 1")
        self.cursor_text.pack(side="right")
        self.zoom_text = ttk.Label(self.status, text="масштаб 100%")
        self.zoom_text.pack(side="right", padx=(0, 16))
        self._build_zoom_bar(self.status)

        self.panes = ttk.PanedWindow(self, orient="horizontal")
        self.panes.pack(fill="both", expand=True)

        left = ttk.Frame(self.panes)
        self.editor = CodeEditor(left, on_change=self._on_text_change,
                                 on_cursor=self._on_cursor,
                                 on_message=self._status,
                                 on_ctrl=self._on_ctrl,
                                 font_size=int(self.settings.get("editor_font", 11)),
                                 palette=self.ui_palette)
        self.editor.pack(fill="both", expand=True)
        self.problems = _ProblemList(left, on_select=self.editor.goto_line)
        self.problems.pack(fill="x")
        self.panes.add(left, weight=3)

        right = ttk.Frame(self.panes)
        self.preview = Preview(right, on_zoom_change=self._on_zoom,
                               on_scale_request=self._on_scale_request)
        self.scene = InteractiveCanvas(
            right, on_node_moved=self._on_node_moved,
            on_edge_moved=self._on_edge_moved,
            on_edge_cleared=self._on_edge_cleared,
            on_node_lock=self._on_node_lock,
            on_edge_lock=self._on_edge_lock,
            on_ports=self._on_ports,
            on_edge_end=self._on_edge_end,
            on_label=self._on_label,
            on_orthogonal=self._on_orthogonal,
            on_message=self._status,
            on_zoom_change=self._on_zoom,
        )
        self.preview.pack(fill="both", expand=True)
        self.panes.add(right, weight=4)
        self.after(200, lambda: self._restore_sash())

    def _build_menu(self) -> None:
        self.menubar = menubar = tk.Menu(self)

        files = tk.Menu(menubar, tearoff=0)
        files.add_command(label="Новый", accelerator="Ctrl+N",
                          command=self.new_file)
        files.add_command(label="Открыть…", accelerator="Ctrl+O",
                          command=self.open_file)
        files.add_separator()
        files.add_command(label="Сохранить", accelerator="Ctrl+S",
                          command=self.save_file)
        files.add_command(label="Сохранить как…", accelerator="Ctrl+Shift+S",
                          command=self.save_file_as)
        files.add_separator()
        files.add_command(label="Экспорт PNG…", accelerator="Ctrl+E",
                          command=self.export_png)
        files.add_command(label="Быстрый экспорт рядом с файлом",
                          accelerator="F9", command=self.quick_export)
        scale_menu = tk.Menu(files, tearoff=0)
        for factor in (1, 2, 3, 4):
            scale_menu.add_radiobutton(label=f"{factor}x", value=factor,
                                       variable=self.export_scale)
        files.add_cascade(label="Размер экспорта", menu=scale_menu)
        files.add_separator()
        files.add_command(label="Выход", command=self._on_close)
        menubar.add_cascade(label="Файл", menu=files)

        edit = tk.Menu(menubar, tearoff=0)
        edit.add_command(label="Отменить", accelerator="Ctrl+Z",
                         command=lambda: self._text_event("<<Undo>>"))
        edit.add_command(label="Повторить", accelerator="Ctrl+Shift+Z",
                         command=lambda: self._text_event("<<Redo>>"))
        edit.add_separator()
        edit.add_command(label="Вырезать", command=lambda: self._text_event("<<Cut>>"))
        edit.add_command(label="Копировать",
                         command=lambda: self._text_event("<<Copy>>"))
        edit.add_command(label="Вставить",
                         command=lambda: self._text_event("<<Paste>>"))
        edit.add_command(label="Выделить всё", accelerator="Ctrl+A",
                         command=lambda: self.editor.select_all())
        edit.add_command(label="Закомментировать строки", accelerator="Ctrl+/",
                         command=lambda: self.editor.toggle_comments())
        edit.add_separator()
        edit.add_command(label="Найти…", accelerator="Ctrl+F",
                         command=lambda: self.editor.open_find())
        edit.add_command(label="Заменить…", accelerator="Ctrl+H",
                         command=lambda: self.editor.open_replace())
        edit.add_command(label="Переименовать…", accelerator="F2",
                         command=lambda: self.editor.rename_symbol())
        edit.add_separator()
        edit.add_command(label="Крупнее шрифт", accelerator="Ctrl+колесо",
                         command=lambda: self.editor.change_font_size(1))
        edit.add_command(label="Мельче шрифт",
                         command=lambda: self.editor.change_font_size(-1))
        menubar.add_cascade(label="Правка", menu=edit)

        insert = tk.Menu(menubar, tearoff=0)
        insert.add_command(label="Свой вид объекта…", accelerator="Ctrl+1",
                           command=self.design_shape)
        insert.add_command(label="Свой вид связи…", accelerator="Ctrl+2",
                           command=self.design_link)
        insert.add_command(label="Свою структуру…", accelerator="Ctrl+3",
                           command=self.design_struct)
        insert.add_separator()
        for name, snippet in SNIPPETS.items():
            insert.add_command(label=name,
                               command=lambda s=snippet: self.editor.insert_snippet(s))
        menubar.add_cascade(label="Вставка", menu=insert)

        view = tk.Menu(menubar, tearoff=0)
        view.add_checkbutton(label="Обновлять автоматически",
                             variable=self.auto_render,
                             command=self._on_auto_toggle)
        view.add_command(label="Обновить сейчас", accelerator="F5",
                         command=self.render_now)
        view.add_separator()
        view.add_checkbutton(label="Интерактивная область",
                             variable=self.interactive,
                             command=self._show_mode)
        view.add_checkbutton(label="Блокировать положения",
                             variable=self.positions_locked,
                             command=self._on_lock_toggle)
        view.add_separator()
        view.add_command(label="Увеличить", accelerator="Ctrl+=",
                         command=lambda: self._active_view().zoom_in())
        view.add_command(label="Уменьшить", accelerator="Ctrl+-",
                         command=lambda: self._active_view().zoom_out())
        view.add_command(label="По размеру окна", accelerator="Ctrl+0",
                         command=lambda: self._active_view().fit())
        view.add_command(label="Реальный размер", accelerator="Ctrl+1",
                         command=lambda: self._active_view().reset_zoom())
        view.add_separator()
        theme_menu = tk.Menu(view, tearoff=0)
        for name in DIAGRAM_THEMES:
            theme_menu.add_radiobutton(label=name, value=name,
                                       variable=self.diagram_theme,
                                       command=self.render_now)
        view.add_cascade(label="Тема диаграммы", menu=theme_menu)
        ui_menu = tk.Menu(view, tearoff=0)
        ui_menu.add_command(label="Светлое",
                            command=lambda: self._apply_ui_palette("light"))
        ui_menu.add_command(label="Тёмное",
                            command=lambda: self._apply_ui_palette("dark"))
        view.add_cascade(label="Оформление редактора", menu=ui_menu)
        view.add_checkbutton(label="Показывать список проблем",
                             variable=self.show_problems,
                             command=self._toggle_problems)
        menubar.add_cascade(label="Вид", menu=view)

        samples = tk.Menu(menubar, tearoff=0)
        for name in EXAMPLES:
            samples.add_command(label=name,
                                command=lambda n=name: self.load_example(n))
        menubar.add_cascade(label="Примеры", menu=samples)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Справка по синтаксису", accelerator="F1",
                              command=self.show_help)
        help_menu.add_command(label="О программе", command=self.show_about)
        menubar.add_cascade(label="Справка", menu=help_menu)

        self.configure(menu=menubar)

    def _button(self, parent, label: str, command, hint: str,
                style: str = "TButton", **pack) -> ttk.Button:
        """Кнопка с надписью и всплывающей подсказкой."""
        button = ttk.Button(parent, text=label, command=command, style=style)
        button.pack(**pack)
        tooltip.attach(button, hint)
        return button

    def _build_toolbar(self) -> None:
        bar = self.toolbar
        for label, command, hint in (
            ("Новый", self.new_file,
             "Начать пустую диаграмму  ·  Ctrl+N"),
            ("Открыть", self.open_file,
             "Открыть файл с описанием диаграммы  ·  Ctrl+O"),
            ("Сохранить", self.save_file,
             "Сохранить текст диаграммы  ·  Ctrl+S"),
            ("Экспорт PNG", self.export_png,
             "Сохранить картинку в PNG с выбором места  ·  Ctrl+E"),
        ):
            self._button(bar, label, command, hint, side="left", padx=(0, 3))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        self._button(bar, "Обновить", self.render_now,
                     "Перерисовать диаграмму прямо сейчас  ·  F5",
                     side="left", padx=(0, 3))
        auto = ttk.Checkbutton(bar, text="авто", variable=self.auto_render,
                               command=self._on_auto_toggle)
        auto.pack(side="left")
        tooltip.attach(auto, "Автоматически перерисовывать диаграмму "
                             "через мгновение после правки текста")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        mode = ttk.Checkbutton(bar, text="интерактив", variable=self.interactive,
                               command=self._show_mode)
        mode.pack(side="left", padx=(0, 4))
        tooltip.attach(mode, "Справа вместо картинки — область, где блоки "
                             "и связи можно перетаскивать")
        self._lock_button = ttk.Checkbutton(
            bar, text="Заблокировать", variable=self.positions_locked,
            command=self._on_lock_toggle)
        self._lock_button.pack(side="left")
        tooltip.attach(
            self._lock_button,
            "Заблокировать: блоки, сдвинутые вручную, остаются на месте "
            "при изменении схемы. Разблокировать: раскладка двигает их. "
            "Правый щелчок блокирует один объект",
        )
        self._button(
            bar, "Добавить точку", self._add_point,
            "На выбранный блок — точка на границе, на выбранную связь — узел линии",
            side="left", padx=(8, 3))
        self._button(
            bar, "Удалить точку", self._delete_point,
            "Удалить выбранную точку входа, выхода, узла или свободную точку блока. "
            "Если выбрана связь — убирает все её промежуточные узлы",
            side="left")
        self._button(
            bar, "Удалить узлы", self._clear_bends,
            "Убрать все промежуточные узлы выбранной связи",
            side="left", padx=(0, 3))
        self._button(
            bar, "Ортогонально", self._orthogonalize,
            "Выровнять изменённую связь по горизонтали и вертикали, "
            "сдвинув узлы как можно меньше",
            side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        self._button(bar, "Свой объект…", self.design_shape,
                     "Собрать собственный вид объекта: форма, цвета, "
                     "стереотип, секции  ·  Ctrl+1", side="left", padx=(0, 3))
        self._button(bar, "Своя связь…", self.design_link,
                     "Собрать собственный вид связи: линия, цвет, "
                     "окончания  ·  Ctrl+2", side="left", padx=(0, 3))
        self._button(bar, "Своя структура…", self.design_struct,
                     "Собрать шаблон из объектов и связей, который "
                     "разворачивается одной строкой  ·  Ctrl+3", side="left")

        self._button(bar, "Справка", self.show_help,
                     "Открыть справку по синтаксису  ·  F1",
                     side="right", padx=(6, 0))
        theme_box = ttk.Combobox(bar, textvariable=self.diagram_theme,
                                 state="readonly", values=list(DIAGRAM_THEMES),
                                 width=9)
        theme_box.pack(side="right", padx=(4, 0))
        tooltip.attach(theme_box, "Цветовая тема картинки. Строка "
                                  "«set theme = …» в тексте имеет приоритет")
        ttk.Label(bar, text="тема:").pack(side="right", padx=(8, 0))
        self.diagram_theme.trace_add("write", lambda *_: self.render_now())

    def _build_zoom_bar(self, parent) -> None:
        """Кнопки масштаба рядом с показанием масштаба в строке состояния."""
        # предпросмотр создаётся позже, поэтому вызовы отложенные
        zoom = ttk.Frame(parent)
        zoom.pack(side="right", padx=(0, 10))
        self._button(zoom, "−", lambda: self._active_view().zoom_out(),
                     "Уменьшить  ·  Ctrl+−  или  Ctrl+колесо",
                     style="Zoom.TButton", side="left")
        self._button(zoom, "по размеру", lambda: self._active_view().fit(),
                     "Вписать диаграмму в окно  ·  Ctrl+0  "
                     "или двойной щелчок по картинке",
                     style="Zoom.TButton", side="left", padx=3)
        self._button(zoom, "100%", lambda: self._active_view().reset_zoom(),
                     "Показать картинку в настоящем размере",
                     style="Zoom.TButton", side="left")
        self._button(zoom, "+", lambda: self._active_view().zoom_in(),
                     "Увеличить  ·  Ctrl+=  или  Ctrl+колесо",
                     style="Zoom.TButton", side="left", padx=(3, 0))

    def _bind_keys(self) -> None:
        self.bind_all("<KeyPress>", self._on_ctrl_global)
        self.bind_all("<Control-KeyPress>", self._on_ctrl_global)
        for sequence in ("<Control-Shift-z>", "<Control-Shift-Z>"):
            self.bind_all(sequence, self._on_ctrl_global)
        for name in hotkeys.layout_keysyms():
            for sequence in (f"<Control-{name}>", f"<Control-Shift-{name}>"):
                try:
                    self.bind_all(sequence, self._on_ctrl_global)
                except tk.TclError:
                    pass
        self.bind_all("<F9>", lambda e: self.quick_export())
        self.bind_all("<F5>", lambda e: self.render_now())
        self.bind_all("<F1>", lambda e: self.show_help())

    def _editor_handles_ctrl(self, widget) -> bool:
        editor = getattr(self, "editor", None)
        if editor is None:
            return False
        return widget in (editor.text, editor._find_entry, editor._replace_entry)

    def _on_ctrl_global(self, event):
        if not hotkeys.control_down(event) or hotkeys.is_modifier(event):
            return None
        if self._editor_handles_ctrl(event.widget):
            return None
        if self._on_ctrl(event):
            return "break"
        return None

    def _on_ctrl(self, event) -> bool:
        """Обрабатывает Ctrl+клавиша. True — событие дальше передавать не нужно."""
        if not hotkeys.control_down(event) or hotkeys.alt_down(event):
            return False
        key = hotkeys.latin_key(event)
        if not key:
            return False
        shift = hotkeys.shift_down(event)
        in_editor = event.widget is self.editor.text

        if key == "a" and not shift:
            if in_editor:
                self.editor.select_all()
                return True
            if event.widget.winfo_class() in ("TEntry", "Entry"):
                event.widget.selection_range(0, "end")
                event.widget.icursor("end")
                return True
            return False
        if key in "cvx" and not in_editor:
            return False
        if key == "z":
            if not in_editor and event.widget.winfo_class() in ("Text", "Entry", "TEntry"):
                return False
            self._text_event("<<Redo>>" if shift else "<<Undo>>")
            return True
        if in_editor and key == "y" and not shift:
            self._text_event("<<Redo>>")
            return True
        if in_editor and key == "c" and not shift:
            self._text_event("<<Copy>>")
            return True
        if in_editor and key == "x" and not shift:
            self._text_event("<<Cut>>")
            return True
        if in_editor and key == "v" and not shift:
            self._text_event("<<Paste>>")
            return True
        if in_editor and key == "/":
            self.editor.toggle_comments()
            return True

        if key == "f" and not shift:
            self.editor.open_find()
            return True
        if key == "h" and not shift:
            self.editor.open_replace()
            return True
        if key == "n" and not shift:
            self.new_file()
            return True
        if key == "o" and not shift:
            self.open_file()
            return True
        if key == "s" and shift:
            self.save_file_as()
            return True
        if key == "s":
            self.save_file()
            return True
        if key == "e" and not shift:
            self.export_png()
            return True
        if key == "=":
            self._active_view().zoom_in()
            return True
        if key == "-":
            self._active_view().zoom_out()
            return True
        if key == "0" and not shift:
            self._active_view().fit()
            return True
        if key == "1" and not shift:
            self.design_shape()
            return True
        if key == "2" and not shift:
            self.design_link()
            return True
        if key == "3" and not shift:
            self.design_struct()
            return True
        return False

    def _status(self, text: str) -> None:
        self.status_text.configure(text=text)

    def _text_event(self, event: str) -> None:
        try:
            self.editor.text.event_generate(event)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ палитра --

    def _apply_ui_palette(self, name: str) -> None:
        self.ui_palette = name if name in ("light", "dark") else "light"
        dark = self.ui_palette == "dark"
        c = ui_colors(self.ui_palette)
        style = ttk.Style(self)
        if self._base_theme is None:
            self._base_theme = style.theme_use()
        style.theme_use("clam" if dark else self._base_theme)
        self.configure(background=c["bg"])
        self._style_widgets(style, c, dark)
        self._paint_menus(self.menubar, c, dark)
        self.editor.set_palette(self.ui_palette)
        self.preview.set_backdrop(self.ui_palette)
        self.scene.set_backdrop(self.ui_palette)
        self.problems.set_palette(self.ui_palette)
        tooltip.set_palette(self.ui_palette)
        # заголовок с кнопками сворачивания рисует сама Windows
        native.apply_chrome(self, dark, c["bg"], c["fg"])
        for child in self.winfo_children():
            setter = getattr(child, "set_palette", None)
            if isinstance(child, tk.Toplevel) and setter is not None:
                setter(self.ui_palette)

    def _style_widgets(self, style: ttk.Style, c: dict[str, str],
                       dark: bool) -> None:
        """Цвета элементов ttk, включая рамки и обводку выбора."""
        bg, fg, field = c["bg"], c["fg"], c["field"]
        border, focus, accent = c["border"], c["focus"], c["accent"]
        if dark:
            # clam рисует элементы сам, поэтому цвета задаются сразу для всех
            style.configure(".", background=bg, foreground=fg,
                            fieldbackground=field, bordercolor=border,
                            lightcolor=bg, darkcolor=bg,
                            troughcolor=c["trough"], arrowcolor=fg,
                            focuscolor=focus, insertcolor=fg,
                            selectbackground=accent,
                            selectforeground=c["accent_fg"])
            # clam для выключенных и наведённых элементов держит свои
            # светлые цвета, поэтому карту состояний задаём заново
            style.map(".", background=[("disabled", bg), ("active", bg)],
                      foreground=[("disabled", c["muted"])],
                      fieldbackground=[("disabled", bg), ("readonly", field)],
                      arrowcolor=[("disabled", c["muted"])])
            style.configure("TButton", background=c["button"],
                            bordercolor=border)
            style.map("TButton",
                      background=[("pressed", c["button_pressed"]),
                                  ("active", c["button_active"])],
                      bordercolor=[("focus", focus), ("active", focus)],
                      lightcolor=[("pressed", c["button_pressed"])],
                      darkcolor=[("pressed", c["button_pressed"])])
            style.configure("TCheckbutton", indicatorbackground=field,
                            indicatorforeground=c["accent_fg"])
            style.map("TCheckbutton",
                      indicatorbackground=[("selected", accent),
                                           ("active", c["button_active"])],
                      bordercolor=[("focus", focus)])
            style.configure("TScrollbar", background=c["button"],
                            bordercolor=border, arrowcolor=fg)
            style.map("TScrollbar",
                      background=[("active", c["button_active"])])
            # clam для наведения и нажатия держит свои светлые цвета
            for element in ("TCombobox", "TSpinbox"):
                style.map(element,
                          background=[("active", c["button_active"]),
                                      ("pressed", c["button_active"])],
                          arrowcolor=[("disabled", c["muted"])],
                          bordercolor=[("focus", focus), ("hover", focus)])
            style.map("TEntry", bordercolor=[("focus", focus)])
            style.configure("Treeview.Heading", background=c["button"],
                            foreground=fg, relief="flat")
            style.configure("TSeparator", background=border)
            style.configure("Sash", sashthickness=6, gripcount=0,
                            background=border, bordercolor=border,
                            lightcolor=border, darkcolor=border)
            style.configure("TNotebook.Tab", background=c["button"])
        else:
            # системная тема цвета кнопок и обводку задаёт сама
            for element in ("TFrame", "TPanedwindow", "TLabelframe"):
                style.configure(element, background=bg)
            style.configure("TLabel", background=bg, foreground=fg)
            style.configure("TLabelframe.Label", background=bg, foreground=fg)
            style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("Zoom.TButton", padding=(5, 0))
        style.configure("Treeview", background=field, fieldbackground=field,
                        foreground=fg, bordercolor=border)
        style.map("Treeview", background=[("selected", accent)],
                  foreground=[("selected", c["accent_fg"])])
        style.configure("TEntry", fieldbackground=field, foreground=fg,
                        insertcolor=fg)
        style.configure("TSpinbox", fieldbackground=field, foreground=fg,
                        insertcolor=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg)
        # у списка «только для чтения» своё состояние оформления
        style.map("TCombobox", fieldbackground=[("readonly", field)],
                  foreground=[("readonly", fg)])
        style.configure("ComboboxPopdownFrame", background=border,
                        bordercolor=border)
        paint_popdowns(self, c)

    def _paint_menus(self, menu: tk.Menu, c: dict[str, str],
                     dark: bool) -> None:
        """Цвета выпадающих меню; строку самого меню рисует система."""
        menu.configure(background=c["bg"], foreground=c["fg"],
                       activebackground=c["accent"],
                       activeforeground=c["accent_fg"],
                       activeborderwidth=0, borderwidth=0,
                       disabledforeground=c["muted"],
                       selectcolor=c["focus"], relief="flat")
        for child in menu.winfo_children():
            if isinstance(child, tk.Menu):
                self._paint_menus(child, c, dark)

    def _toggle_problems(self) -> None:
        if self.show_problems.get():
            self.problems.pack(fill="x")
            self._refresh_problems()
        else:
            self.problems.pack_forget()

    def _restore_sash(self) -> None:
        position = self.settings.get("sash")
        try:
            if position:
                self.panes.sashpos(0, int(position))
        except (tk.TclError, ValueError):
            pass

    # ----------------------------------------------------------- отрисовка --

    def _on_text_change(self) -> None:
        if not self.dirty:
            self.dirty = True
            self._set_title()
        if self._position_edit:
            self._position_edit = False
            self.render_now()
            return
        if self.auto_render.get():
            self._schedule_render(380)

    def _on_auto_toggle(self) -> None:
        if self.auto_render.get():
            self.render_now()

    def _schedule_render(self, delay: int = 250) -> None:
        if self._render_after:
            self.after_cancel(self._render_after)
        self._render_after = self.after(delay, self.render_now)

    def render_now(self) -> None:
        self._render_after = None
        self._seq += 1
        text = self.editor.get_text()
        interactive = bool(self.interactive.get())
        self._honor = self._honor_manual(text)
        scale = 1.0 if interactive else max(1.0, min(3.0, round(self.preview.zoom, 2)))
        self.worker.submit(_Job(
            self._seq, text, scale, self.diagram_theme.get(),
            self._honor, interactive,
        ))
        if not self._busy:
            self._busy = True
            self.status_text.configure(text="Отрисовка…")

    def _on_scale_request(self, zoom: float) -> None:
        if self.interactive.get():
            return
        self._schedule_render(220)

    def _poll_worker(self) -> None:
        item = self.worker.poll()
        while item is not None:
            job, result = item
            if job.seq >= self._applied_seq:
                self._applied_seq = job.seq
                self._apply_result(job, result)
            item = self.worker.poll()
        self.after(70, self._poll_worker)

    def _apply_result(self, job: _Job, result: api.RenderResult) -> None:
        self._busy = False
        self.last_result = result
        self._diagram = result.diagram
        if job.interactive:
            if self.interactive.get():
                self.scene.show(result.diagram, result.error)
        elif self.interactive.get():
            pass
        elif result.image is not None:
            self.preview.set_image(result.image, job.scale)
        elif result.error:
            self.preview.clear()
        self.editor.mark_diagnostics(result.diagnostics)
        self._refresh_problems()
        self._update_status(job, result)

    def _refresh_problems(self) -> None:
        if not self.show_problems.get():
            return
        diagnostics = self.last_result.diagnostics if self.last_result else []
        extra = []
        if self.last_result and self.last_result.error:
            extra.append(self.last_result.error.strip().split("\n")[-1])
        self.problems.update_items(diagnostics, extra)

    def _update_status(self, job: _Job, result: api.RenderResult) -> None:
        if result.error:
            self.status_text.configure(text=f"Ошибка отрисовки: {result.error}")
            return
        if result.image is not None:
            width, height = result.size
            base = (round(width / max(job.scale, 0.01)),
                    round(height / max(job.scale, 0.01)))
        elif result.diagram is not None:
            base = (round(result.diagram.width), round(result.diagram.height))
        else:
            base = (0, 0)
        errors = len(result.errors)
        warnings = len(result.warnings)
        parts = [f"{base[0]}×{base[1]} px", f"{result.duration * 1000:.0f} мс"]
        if result.diagram is not None:
            parts.append(f"объектов: {len(result.diagram.nodes)}")
            parts.append(f"связей: {len(result.diagram.edges)}")
        if errors:
            parts.append(f"ошибок: {errors}")
        if warnings:
            parts.append(f"предупреждений: {warnings}")
        self.status_text.configure(text="  ·  ".join(parts))

    def _on_zoom(self, zoom: float) -> None:
        self.zoom_text.configure(text=f"масштаб {zoom * 100:.0f}%")

    def _active_view(self):
        return self.scene if self.interactive.get() else self.preview

    def _show_mode(self, render: bool = True) -> None:
        if self.interactive.get():
            self.preview.pack_forget()
            self.scene.pack(fill="both", expand=True)
        else:
            self.scene.pack_forget()
            self.preview.pack(fill="both", expand=True)
        self._on_zoom(self._active_view().zoom)
        if render:
            self.render_now()

    def _sync_lock_caption(self) -> None:
        locked = bool(self.positions_locked.get())
        self._lock_button.configure(
            text="Заблокировать" if locked else "Разблокировать")

    def _on_lock_toggle(self) -> None:
        self._sync_lock_caption()
        if self.positions_locked.get():
            self._status("Положения заблокированы: ручные координаты "
                         "сохраняются при изменении схемы")
        else:
            self._status("Положения разблокированы: при изменении схемы "
                         "ручные координаты уступают раскладке")
        self.render_now()

    def _honor_manual(self, text: str) -> bool:
        """Ручные координаты держатся, пока схема не изменилась или кнопка зажата."""
        key = schema_text(text)
        if self._schema_key is None:
            self._schema_key = key
            return True
        changed = key != self._schema_key
        self._schema_key = key
        if not changed:
            return True
        return bool(self.positions_locked.get())

    def _write_text(self, text: str) -> None:
        if text == self.editor.get_text():
            return
        self._position_edit = True
        self.editor.replace_text(text)

    def _on_node_moved(self, name: str, x: float, y: float) -> None:
        self._write_text(set_node_position(self.editor.get_text(), name, x, y))

    def _on_edge_moved(self, index: int, points: list[tuple[float, float]]) -> None:
        edge = self._edge(index)
        if edge is None or not points:
            return
        self._write_text(set_edge_waypoints(
            self.editor.get_text(), edge.a, edge.b,
            edge_ordinal(self._diagram.edges, index), points,
            src_line=edge.src_line,
        ))

    def _add_point(self) -> None:
        if not self.interactive.get():
            self._status("Точки добавляются в интерактивном режиме")
            return
        self.scene.add_point()

    def _delete_point(self) -> None:
        if not self.interactive.get():
            self._status("Точки удаляются в интерактивном режиме")
            return
        self.scene.delete_point()

    def _clear_bends(self) -> None:
        if not self.interactive.get():
            self._status("Узлы убираются в интерактивном режиме")
            return
        self.scene.clear_bends()

    def _orthogonalize(self) -> None:
        if not self.interactive.get():
            self._status("Выравнивание доступно в интерактивном режиме")
            return
        self.scene.orthogonalize()

    def _on_ports(self, name: str, points: list[tuple[float, float]]) -> None:
        self._write_text(set_node_ports(self.editor.get_text(), name, points))

    def _on_edge_end(self, index: int, kind: str,
                     point: tuple[float, float] | None) -> None:
        edge = self._edge(index)
        if edge is None:
            return
        ordinal = edge_ordinal(self._diagram.edges, index)
        text = self.editor.get_text()
        if point is None:
            updated = clear_edge_end(text, kind, edge.a, edge.b, ordinal)
        else:
            updated = set_edge_end(text, kind, edge.a, edge.b, ordinal, point)
        self._write_text(updated)

    def _on_label(self, index: int, offset: tuple[float, float] | None) -> None:
        edge = self._edge(index)
        if edge is None:
            return
        self._write_text(set_edge_label_offset(
            self.editor.get_text(), edge.a, edge.b,
            edge_ordinal(self._diagram.edges, index), offset,
        ))

    def _on_orthogonal(self, specs) -> None:
        text = self.editor.get_text()
        for index, waypoints, exit_at, entry_at in specs:
            edge = self._edge(index)
            if edge is None or self._diagram is None:
                continue
            text = set_edge_geometry(
                text, edge.a, edge.b, edge_ordinal(self._diagram.edges, index),
                waypoints, exit_at, entry_at, src_line=edge.src_line,
            )
        self._write_text(text)

    def _on_edge_cleared(self, index: int) -> None:
        edge = self._edge(index)
        if edge is None:
            return
        self._write_text(clear_edge_waypoints(
            self.editor.get_text(), edge.a, edge.b,
            edge_ordinal(self._diagram.edges, index), edge.src_line,
        ))

    def _on_node_lock(self, name: str, locked: bool, x: float, y: float) -> None:
        self._write_text(set_node_position(
            self.editor.get_text(), name, x, y, locked=locked))
        state = "заблокировано" if locked else "снята блокировка"
        self._status(f"{name}: положение {state}")

    def _on_edge_lock(self, index: int, locked: bool,
                      points: list[tuple[float, float]]) -> None:
        edge = self._edge(index)
        if edge is None:
            return
        if not points:
            self._status("У связи нет узлов. Двойной щелчок по линии добавляет узел")
            return
        self._write_text(set_edge_waypoints(
            self.editor.get_text(), edge.a, edge.b,
            edge_ordinal(self._diagram.edges, index), points,
            locked=locked, src_line=edge.src_line,
        ))
        state = "заблокировано" if locked else "снята блокировка"
        self._status(f"Связь {edge.a} → {edge.b}: положение {state}")

    def _edge(self, index: int):
        diagram = self._diagram
        if diagram is None or not (0 <= index < len(diagram.edges)):
            return None
        return diagram.edges[index]

    def _on_cursor(self, row: int, col: int) -> None:
        self.cursor_text.configure(text=f"строка {row}, столбец {col}")

    # -------------------------------------------------------------- файлы --

    def _set_title(self) -> None:
        name = self.path.name if self.path else "без имени"
        mark = " *" if self.dirty else ""
        self.title(f"{name}{mark} — UML Studio {__version__}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Сохранить изменения?",
            "Текст диаграммы изменён. Сохранить перед продолжением?",
            parent=self)
        if answer is None:
            return False
        if answer:
            return self.save_file()
        return True

    def new_file(self) -> None:
        if not self._confirm_discard():
            return
        self.path = None
        self._schema_key = None
        self.editor.set_text(STARTER)
        self.dirty = False
        self._set_title()
        self.render_now()

    def open_file(self) -> None:
        if not self._confirm_discard():
            return
        name = filedialog.askopenfilename(
            parent=self, title="Открыть диаграмму", filetypes=FILE_TYPES,
            initialdir=self.settings.get("last_dir") or str(Path.home()))
        if name:
            self._load_file(Path(name))

    def _load_file(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror("Не удалось открыть файл", str(exc), parent=self)
            return
        self.path = path
        self.settings["last_dir"] = str(path.parent)
        self._schema_key = None
        self.editor.set_text(text)
        self.dirty = False
        self._set_title()
        self.render_now()

    def save_file(self) -> bool:
        if self.path is None:
            return self.save_file_as()
        try:
            self.path.write_text(self.editor.get_text(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Не удалось сохранить файл", str(exc), parent=self)
            return False
        self.dirty = False
        self._set_title()
        self.status_text.configure(text=f"Сохранено: {self.path}")
        return True

    def save_file_as(self) -> bool:
        name = filedialog.asksaveasfilename(
            parent=self, title="Сохранить диаграмму", defaultextension=".uml",
            filetypes=FILE_TYPES,
            initialfile=self.path.name if self.path else "диаграмма.uml",
            initialdir=self.settings.get("last_dir") or str(Path.home()))
        if not name:
            return False
        self.path = Path(name)
        self.settings["last_dir"] = str(self.path.parent)
        return self.save_file()

    # ------------------------------------------------------------- экспорт --

    def _default_png_path(self) -> Path:
        if self.path:
            return self.path.with_suffix(".png")
        folder = self.settings.get("last_dir") or str(Path.home())
        return Path(folder) / "диаграмма.png"

    def export_png(self) -> None:
        default = self._default_png_path()
        name = filedialog.asksaveasfilename(
            parent=self, title="Экспорт PNG", defaultextension=".png",
            filetypes=[("PNG", "*.png")], initialfile=default.name,
            initialdir=str(default.parent))
        if name:
            self._write_png(Path(name))

    def quick_export(self) -> None:
        if self.path is None:
            self.export_png()
            return
        self._write_png(self.path.with_suffix(".png"))

    def _write_png(self, path: Path) -> None:
        scale = max(1, int(self.export_scale.get()))
        self.status_text.configure(text=f"Сохранение {path.name}…")
        self.update_idletasks()
        try:
            result = api.render_to_file(self.editor.get_text(), str(path),
                                        scale=scale, supersample=2,
                                        honor_manual=self._honor)
        except Exception as exc:
            messagebox.showerror("Экспорт не удался", str(exc), parent=self)
            return
        if not result.ok:
            messagebox.showerror("Экспорт не удался",
                                 result.error or "неизвестная ошибка", parent=self)
            return
        self.status_text.configure(
            text=f"Сохранено: {path}  ·  {result.size[0]}×{result.size[1]} px")

    # ------------------------------------------------------------ диалоги --

    def _known_shapes(self) -> list[str]:
        try:
            diagram, _ = parse(self.editor.get_text())
            return sorted(diagram.shapes)
        except Exception:
            return []

    def design_shape(self) -> None:
        dialog = ShapeDesigner(self, self.ui_palette, self._known_shapes())
        snippet = dialog.show()
        if snippet:
            self.editor.insert_snippet(snippet)
            self.render_now()

    def design_link(self) -> None:
        snippet = LinkDesigner(self, self.ui_palette).show()
        if snippet:
            self.editor.insert_snippet(snippet)
            self.render_now()

    def design_struct(self) -> None:
        snippet = StructDesigner(self, self.ui_palette).show()
        if snippet:
            self.editor.insert_snippet(snippet)
            self.render_now()

    def load_example(self, name: str) -> None:
        if not self._confirm_discard():
            return
        self._schema_key = None
        self.editor.set_text(EXAMPLES[name])
        self.path = None
        self.dirty = False
        self._set_title()
        self._active_view().fit()
        self.render_now()

    def show_help(self) -> None:
        HelpWindow(self, self.ui_palette)

    def show_about(self) -> None:
        messagebox.showinfo(
            "О программе",
            f"UML Studio {__version__}\n\n"
            "Редактор UML-диаграмм: текст слева, PNG справа.\n"
            "Синтаксис близок к PlantUML и дополнен блоками shape, link\n"
            "и struct для собственных объектов, связей и структур.\n\n"
            "Разбор, раскладка и отрисовка выполняются внутри программы,\n"
            "внешние движки не требуются.",
            parent=self)

    # -------------------------------------------------------------- выход --

    def _on_close(self) -> None:
        if not self._confirm_discard():
            return
        self.settings.update({
            "ui_palette": self.ui_palette,
            "diagram_theme": self.diagram_theme.get(),
            "auto_render": bool(self.auto_render.get()),
            "export_scale": int(self.export_scale.get()),
            "editor_font": self.editor.font_size(),
            "interactive": bool(self.interactive.get()),
            "positions_locked": bool(self.positions_locked.get()),
        })
        try:
            self.settings["sash"] = self.panes.sashpos(0)
        except tk.TclError:
            pass
        _save_settings(self.settings)
        self.worker.stop()
        self.destroy()


class _ProblemList(ttk.Frame):
    """Компактный список ошибок и предупреждений разбора."""

    def __init__(self, master, on_select) -> None:
        super().__init__(master)
        self._on_select = on_select
        header = ttk.Frame(self)
        header.pack(fill="x")
        self.caption = ttk.Label(header, text="Проблем нет")
        self.caption.pack(side="left", padx=8, pady=(4, 2))
        self.tree = ttk.Treeview(self, columns=("line", "kind", "message"),
                                 show="headings", height=4)
        self.tree.heading("line", text="строка")
        self.tree.heading("kind", text="тип")
        self.tree.heading("message", text="сообщение")
        self.tree.column("line", width=64, anchor="e", stretch=False)
        self.tree.column("kind", width=130, anchor="w", stretch=False)
        self.tree.column("message", width=420, anchor="w")
        self.tree.bind("<Double-1>", self._activate)
        self.tree.bind("<Return>", self._activate)
        self.tree.tag_configure("error", foreground="#c62828")
        self.tree.tag_configure("warning", foreground="#a5761b")
        self._visible = False

    def set_palette(self, name: str) -> None:
        dark = name == "dark"
        self.tree.tag_configure("error", foreground="#ff8a80" if dark else "#c62828")
        self.tree.tag_configure("warning",
                                foreground="#ffcc80" if dark else "#a5761b")

    def update_items(self, diagnostics, extra: list[str]) -> None:
        self.tree.delete(*self.tree.get_children())
        errors = sum(1 for d in diagnostics if d.severity == "error")
        warnings = len(diagnostics) - errors
        for item in diagnostics:
            kind = "ошибка" if item.severity == "error" else "предупреждение"
            self.tree.insert("", "end", values=(item.line or "", kind,
                                                item.message),
                             tags=(item.severity,))
        for message in extra:
            self.tree.insert("", "end", values=("", "сбой", message),
                             tags=("error",))
        total = len(diagnostics) + len(extra)
        if total:
            self.caption.configure(
                text=f"Проблемы: ошибок {errors + len(extra)}, "
                     f"предупреждений {warnings}")
            if not self._visible:
                self.tree.pack(fill="x", padx=4, pady=(0, 4))
                self._visible = True
        else:
            self.caption.configure(text="Проблем нет")
            if self._visible:
                self.tree.pack_forget()
                self._visible = False

    def _activate(self, event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        try:
            line = int(values[0])
        except (ValueError, IndexError):
            return
        self._on_select(line)


def _settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    folder = Path(base) / "UmlStudio"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    try:
        _settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def run(path: str | None = None) -> None:
    """Запускает приложение."""
    app = App(path)
    app.mainloop()
