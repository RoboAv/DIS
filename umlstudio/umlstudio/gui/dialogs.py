"""Диалоги: конструктор своих объектов, связей и структур, справка."""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, ttk

from PIL import Image, ImageTk

from .. import api
from ..arrows import DECORATION_NAMES
from ..theme import KIND_DEFAULTS
from . import native, tooltip
from .examples import SYNTAX_HELP
from .palette import colors as ui_colors
from .palette import paint_popdowns, paint_text

FORM_LABELS: list[tuple[str, str]] = [
    ("rect", "прямоугольник"),
    ("roundrect", "прямоугольник со скруглением"),
    ("stadium", "капсула"),
    ("ellipse", "эллипс"),
    ("circle", "круг"),
    ("ring", "кольцо"),
    ("cylinder", "цилиндр (база данных)"),
    ("hexagon", "шестиугольник"),
    ("diamond", "ромб"),
    ("cloud", "облако"),
    ("note", "заметка"),
    ("folder", "папка"),
    ("component", "компонент"),
    ("node3d", "объёмный блок"),
    ("queue", "очередь"),
    ("document", "документ"),
    ("actor", "актор"),
]

LINE_LABELS = [("solid", "сплошная"), ("dashed", "пунктирная"),
               ("dotted", "точками"), ("bold", "жирная")]

PREVIEW_BOX = (360, 300)


def _pick(combo_values: list[tuple[str, str]], key: str) -> str:
    for value, label in combo_values:
        if value == key:
            return f"{label} ({value})"
    return combo_values[0][1] + f" ({combo_values[0][0]})"


def _unpick(display: str) -> str:
    if "(" in display and display.endswith(")"):
        return display[display.rindex("(") + 1:-1]
    return display.strip()


class _Dialog(tk.Toplevel):
    """Основа для модальных окон с предпросмотром."""

    def __init__(self, master, title: str, palette: str = "light") -> None:
        super().__init__(master)
        self.title(title)
        self.result: str | None = None
        self.palette = palette
        self._photo: ImageTk.PhotoImage | None = None
        self._pending: str | None = None
        self.transient(master)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())
        self.configure(background=ui_colors(palette)["bg"])
        native.apply_chrome(self, palette == "dark",
                            ui_colors(palette)["bg"],
                            ui_colors(palette)["fg"])

    # ------------------------------------------------------------ каркас ---

    def build(self) -> None:
        c = ui_colors(self.palette)
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        self.body_frame = ttk.Frame(outer)
        self.body_frame.grid(row=0, column=0, sticky="nw")
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="n", padx=(18, 0))
        ttk.Label(right, text="Предпросмотр").pack(anchor="w")
        self.canvas_frame = tk.Frame(right, width=PREVIEW_BOX[0],
                                     height=PREVIEW_BOX[1],
                                     background=c["canvas"], relief="solid",
                                     borderwidth=1,
                                     highlightbackground=c["border"])
        self.canvas_frame.pack_propagate(False)
        self.canvas_frame.pack()
        self.preview = tk.Label(self.canvas_frame, background=c["canvas"])
        self.preview.pack(expand=True)
        self.hint = ttk.Label(right, text="", foreground=c["muted"],
                              wraplength=PREVIEW_BOX[0])
        self.hint.pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(outer)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(16, 0))
        cancel = ttk.Button(buttons, text="Отмена", command=self._cancel)
        cancel.pack(side="right", padx=(8, 0))
        tooltip.attach(cancel, "Закрыть окно, ничего не вставляя  ·  Esc")
        self.ok_button = ttk.Button(buttons, text="Вставить в текст",
                                    command=self._accept)
        self.ok_button.pack(side="right")
        tooltip.attach(self.ok_button,
                       "Добавить готовое описание в редактор "
                       "после текущей строки")

    def row(self, parent, index: int, label: str, widget,
            hint: str = "") -> None:
        caption = ttk.Label(parent, text=label)
        caption.grid(row=index, column=0, sticky="w", pady=3, padx=(0, 10))
        widget.grid(row=index, column=1, sticky="we", pady=3)
        parent.columnconfigure(1, weight=1)
        if hint:
            tooltip.attach(widget, hint)
            tooltip.attach(caption, hint)

    def check(self, parent, label: str, variable, hint: str,
              command=None, **grid) -> ttk.Checkbutton:
        """Переключатель с подписью и всплывающей подсказкой."""
        box = ttk.Checkbutton(parent, text=label, variable=variable,
                              command=command)
        if grid.pop("pack", False):
            box.pack(**grid)
        else:
            box.grid(**grid)
        tooltip.attach(box, hint)
        return box

    def color_row(self, parent, index: int, label: str,
                  variable: tk.StringVar, hint: str = "") -> None:
        holder = ttk.Frame(parent)
        entry = ttk.Entry(holder, textvariable=variable, width=12)
        entry.pack(side="left")
        swatch = tk.Label(holder, width=3, relief="solid", borderwidth=1)
        swatch.pack(side="left", padx=6)

        def sync(*_):
            value = variable.get().strip() or "#ffffff"
            try:
                swatch.configure(background=value)
            except tk.TclError:
                swatch.configure(background="#ffffff")

        def choose():
            chosen = colorchooser.askcolor(
                color=variable.get() or "#1565c0", parent=self)
            if chosen and chosen[1]:
                variable.set(chosen[1])

        picker = ttk.Button(holder, text="Выбрать…", width=10, command=choose)
        picker.pack(side="left")
        tooltip.attach(picker, f"Открыть палитру для «{label}». "
                               "Код вида #1565c0 можно вписать и вручную")
        variable.trace_add("write", sync)
        sync()
        self.row(parent, index, label, holder, hint)

    # ------------------------------------------------------- предпросмотр --

    def watch(self, *variables) -> None:
        for var in variables:
            var.trace_add("write", lambda *_: self.schedule_preview())

    def schedule_preview(self) -> None:
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(180, self.refresh_preview)

    def refresh_preview(self) -> None:
        self._pending = None
        source = self.preview_source()
        result = api.build(source, scale=1.0, supersample=2)
        if not result.ok or result.image is None:
            self.hint.configure(text=result.error or "не удалось отрисовать")
            return
        image = result.image
        factor = min(1.0, PREVIEW_BOX[0] / image.width,
                     PREVIEW_BOX[1] / image.height)
        if factor < 1.0:
            image = image.resize((max(1, int(image.width * factor)),
                                 max(1, int(image.height * factor))),
                                Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self._photo)
        problems = [str(d) for d in result.diagnostics]
        self.hint.configure(text="; ".join(problems[:2]) if problems else "")

    def preview_source(self) -> str:
        return "class Пример"

    def snippet(self) -> str:
        return ""

    # ----------------------------------------------------------- действия --

    def _accept(self) -> None:
        self.result = self.snippet()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self) -> str | None:
        self.build()
        paint_popdowns(self, ui_colors(self.palette))
        self.refresh_preview()
        self.update_idletasks()
        self._center()
        self.grab_set()
        self.wait_window()
        return self.result

    def set_palette(self, name: str) -> None:
        """Переключает оформление уже открытого окна."""
        self.palette = name
        c = ui_colors(name)
        self.configure(background=c["bg"])
        native.apply_chrome(self, name == "dark", c["bg"], c["fg"])
        paint_popdowns(self, c)
        if getattr(self, "canvas_frame", None) is not None:
            self.canvas_frame.configure(background=c["canvas"],
                                        highlightbackground=c["border"])
            self.preview.configure(background=c["canvas"])
            self.hint.configure(foreground=c["muted"])
        if getattr(self, "body", None) is not None:
            paint_text(self.body, c)

    def _center(self) -> None:
        parent = self.master
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")


# --------------------------------------------------- конструктор объектов --


class ShapeDesigner(_Dialog):
    """Собирает блок ``shape`` — собственный вид объекта."""

    def __init__(self, master, palette: str = "light",
                 known_shapes: list[str] | None = None) -> None:
        super().__init__(master, "Новый вид объекта", palette)
        self.known = known_shapes or []
        self.name = tk.StringVar(value="Микросервис")
        self.base = tk.StringVar(value="class")
        self.form = tk.StringVar(value=_pick(FORM_LABELS, "roundrect"))
        self.accent = tk.StringVar(value="#1565c0")
        self.stereotype = tk.StringVar(value="service")
        self.sections = tk.StringVar(value="Ручки, SLA")
        self.stroke_width = tk.StringVar(value="1.4")
        self.font_size = tk.StringVar(value="13")
        self.dashed = tk.BooleanVar(value=False)
        self.italic = tk.BooleanVar(value=False)
        self.underline = tk.BooleanVar(value=False)
        self.with_sample = tk.BooleanVar(value=True)
        self.manual_colors = tk.BooleanVar(value=False)
        self.fill = tk.StringVar(value="#eef6ff")
        self.stroke = tk.StringVar(value="#1565c0")
        self.text_color = tk.StringVar(value="#10314f")

    def build(self) -> None:
        super().build()
        grid = ttk.Frame(self.body_frame)
        grid.pack(fill="x")
        bases = ["class"] + sorted(KIND_DEFAULTS) + self.known
        row = 0
        self.row(grid, row, "Название вида",
                 ttk.Entry(grid, textvariable=self.name, width=26),
                 "Имя, которым вид объекта будет вызываться в тексте: "
                 "«Микросервис Каталог»")
        row += 1
        self.row(grid, row, "Форма",
                 ttk.Combobox(grid, textvariable=self.form, state="readonly",
                              values=[f"{lbl} ({val})"
                                      for val, lbl in FORM_LABELS], width=30),
                 "Геометрия объекта на картинке")
        row += 1
        self.row(grid, row, "Базовый вид",
                 ttk.Combobox(grid, textvariable=self.base, state="readonly",
                              values=sorted(set(bases)), width=26),
                 "От кого унаследовать свойства. Заданные ниже значения "
                 "перекроют унаследованные")
        row += 1
        self.color_row(grid, row, "Акцентный цвет", self.accent,
                       "Один цвет, из которого считаются и заливка, и рамка, "
                       "и цвет текста")
        row += 1
        self.check(grid, "задать заливку, рамку и текст вручную",
                   self.manual_colors,
                   "Отказаться от расчёта по акцентному цвету и указать "
                   "все три цвета самому", command=self._toggle_colors,
                   row=row, column=1, sticky="w", pady=(2, 4))
        row += 1
        self.manual_rows = []
        hints = {
            "Заливка": "Цвет внутренней области объекта",
            "Рамка": "Цвет линии по контуру объекта",
            "Цвет текста": "Цвет названия и содержимого объекта",
        }
        for label, var in (("Заливка", self.fill), ("Рамка", self.stroke),
                           ("Цвет текста", self.text_color)):
            self.color_row(grid, row, label, var, hints[label])
            self.manual_rows.append(grid.grid_slaves(row=row))
            row += 1
        self.row(grid, row, "Стереотип",
                 ttk.Entry(grid, textvariable=self.stereotype, width=26),
                 "Пометка в угловых кавычках над названием, например "
                 "«service». Оставьте пустым, если не нужна")
        row += 1
        self.row(grid, row, "Секции (через запятую)",
                 ttk.Entry(grid, textvariable=self.sections, width=26),
                 "Именованные разделы внутри объекта. В тексте заполняются "
                 "строкой «Название:» и перечислением под ней")
        row += 1
        self.row(grid, row, "Толщина рамки",
                 ttk.Spinbox(grid, textvariable=self.stroke_width, from_=0.5,
                             to=6.0, increment=0.2, width=8),
                 "Толщина контурной линии в пикселях, обычно 1.4")
        row += 1
        self.row(grid, row, "Размер шрифта",
                 ttk.Spinbox(grid, textvariable=self.font_size, from_=8, to=28,
                             width=8),
                 "Размер текста внутри объекта; заголовок будет на пункт "
                 "крупнее")
        row += 1
        flags = ttk.Frame(grid)
        flags.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.check(flags, "пунктирная рамка", self.dashed,
                   "Рисовать контур штрихами — обычно так показывают "
                   "что-то условное или внешнее", pack=True, side="left")
        self.check(flags, "курсивный заголовок", self.italic,
                   "Название объекта наклонным шрифтом — принятое "
                   "обозначение абстрактных сущностей",
                   pack=True, side="left", padx=10)
        self.check(flags, "подчёркнутый", self.underline,
                   "Подчёркнутое название — принятое обозначение экземпляра "
                   "объекта", pack=True, side="left")
        row += 1
        self.check(grid, "добавить пример использования", self.with_sample,
                   "Вместе с описанием вида вставить готовый объект этого "
                   "вида, чтобы сразу увидеть его на картинке",
                   row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._toggle_colors()
        self.watch(self.name, self.base, self.form, self.accent,
                   self.stereotype, self.sections, self.stroke_width,
                   self.font_size, self.fill, self.stroke, self.text_color)
        for var in (self.dashed, self.italic, self.underline,
                    self.manual_colors, self.with_sample):
            var.trace_add("write", lambda *_: self.schedule_preview())

    def _toggle_colors(self) -> None:
        state = "normal" if self.manual_colors.get() else "disabled"
        for widgets in getattr(self, "manual_rows", []):
            for widget in widgets:
                for child in (widget,) + tuple(widget.winfo_children()):
                    try:
                        child.configure(state=state)
                    except tk.TclError:
                        pass
        self.schedule_preview()

    # ------------------------------------------------------------- вывод ---

    def _shape_block(self) -> str:
        name = self.name.get().strip() or "МойОбъект"
        base = self.base.get().strip()
        head = f"shape {name}"
        if base and base != "class":
            head += f" extends {base}"
        lines = [head + " {", f"  form: {_unpick(self.form.get())}"]
        if self.manual_colors.get():
            lines.append(f"  fill: {self.fill.get().strip()}")
            lines.append(f"  stroke: {self.stroke.get().strip()}")
            lines.append(f"  text: {self.text_color.get().strip()}")
        else:
            lines.append(f"  accent: {self.accent.get().strip() or '#1565c0'}")
        width = self.stroke_width.get().strip()
        if width and width not in ("1.4", ""):
            lines.append(f"  stroke-width: {width}")
        size = self.font_size.get().strip()
        if size and size != "13":
            lines.append(f"  font-size: {size}")
        if self.dashed.get():
            lines.append("  dashed: on")
        if self.italic.get():
            lines.append("  italic: on")
        if self.underline.get():
            lines.append("  underline: on")
        if self.stereotype.get().strip():
            lines.append(f"  stereotype: {self.stereotype.get().strip()}")
        sections = [s.strip() for s in self.sections.get().split(",") if s.strip()]
        if sections:
            lines.append("  sections: " + ", ".join(sections))
        lines.append("}")
        return "\n".join(lines)

    def _sample(self) -> str:
        name = self.name.get().strip() or "МойОбъект"
        sections = [s.strip() for s in self.sections.get().split(",") if s.strip()]
        if not sections:
            return f"{name} Пример"
        body = [f"{name} Пример {{"]
        for index, section in enumerate(sections):
            body.append(f"  {section}:")
            body.append(f"    + значение {index + 1}")
        body.append("}")
        return "\n".join(body)

    def snippet(self) -> str:
        parts = [self._shape_block()]
        if self.with_sample.get():
            parts.append(self._sample())
        return "\n\n".join(parts) + "\n"

    def preview_source(self) -> str:
        return ("set padding = 14\nset shadow = off\n" +
                self._shape_block() + "\n\n" + self._sample() + "\n")


# ---------------------------------------------------- конструктор связей --


class LinkDesigner(_Dialog):
    """Собирает блок ``link`` — собственный вид связи."""

    def __init__(self, master, palette: str = "light") -> None:
        super().__init__(master, "Новый вид связи", palette)
        self.name = tk.StringVar(value="поток")
        self.line = tk.StringVar(value=_pick(LINE_LABELS, "solid"))
        self.head = tk.StringVar(value=self._deco("arrow_filled"))
        self.tail = tk.StringVar(value=self._deco("none"))
        self.color = tk.StringVar(value="#ef6c00")
        self.width = tk.StringVar(value="2")
        self.label = tk.StringVar(value="")

    @staticmethod
    def _deco(key: str) -> str:
        return f"{DECORATION_NAMES.get(key, key)} ({key})"

    def build(self) -> None:
        super().build()
        grid = ttk.Frame(self.body_frame)
        grid.pack(fill="x")
        decorations = [f"{label} ({key})"
                       for key, label in DECORATION_NAMES.items()]
        row = 0
        self.row(grid, row, "Название связи",
                 ttk.Entry(grid, textvariable=self.name, width=26),
                 "Имя, которым связь вызывается в тексте: «A -[поток]-> B»")
        row += 1
        self.row(grid, row, "Линия",
                 ttk.Combobox(grid, textvariable=self.line, state="readonly",
                              values=[f"{lbl} ({val})"
                                      for val, lbl in LINE_LABELS], width=28),
                 "Как выглядит сама линия между объектами")
        row += 1
        self.row(grid, row, "Окончание у цели",
                 ttk.Combobox(grid, textvariable=self.head, state="readonly",
                              values=decorations, width=34),
                 "Что нарисовать у правого объекта — у того, на который "
                 "связь указывает")
        row += 1
        self.row(grid, row, "Окончание у источника",
                 ttk.Combobox(grid, textvariable=self.tail, state="readonly",
                              values=decorations, width=34),
                 "Что нарисовать у левого объекта. Здесь обычно ставят ромб "
                 "композиции или агрегации")
        row += 1
        self.color_row(grid, row, "Цвет", self.color,
                       "Цвет линии и её окончаний")
        row += 1
        self.row(grid, row, "Толщина",
                 ttk.Spinbox(grid, textvariable=self.width, from_=0.8, to=6.0,
                             increment=0.2, width=8),
                 "Толщина линии в пикселях, обычно 1.4")
        row += 1
        self.row(grid, row, "Подпись по умолчанию",
                 ttk.Entry(grid, textvariable=self.label, width=26),
                 "Текст у связи, если в самой строке подпись не указана. "
                 "Можно оставить пустым")
        self.watch(self.name, self.line, self.head, self.tail, self.color,
                   self.width, self.label)

    def _block(self) -> str:
        name = self.name.get().strip() or "связь"
        lines = [f"link {name} {{", f"  line: {_unpick(self.line.get())}",
                 f"  head: {_unpick(self.head.get())}",
                 f"  tail: {_unpick(self.tail.get())}"]
        if self.color.get().strip():
            lines.append(f"  color: {self.color.get().strip()}")
        if self.width.get().strip() not in ("", "1.4"):
            lines.append(f"  width: {self.width.get().strip()}")
        if self.label.get().strip():
            lines.append(f"  label: {self.label.get().strip()}")
        lines.append("}")
        return "\n".join(lines)

    def snippet(self) -> str:
        name = self.name.get().strip() or "связь"
        return self._block() + f"\n\n' пример: A -[{name}]-> B\n"

    def preview_source(self) -> str:
        name = self.name.get().strip() or "связь"
        return ("set padding = 14\nset shadow = off\nset direction = LR\n" +
                self._block() + f"\n\nclass Источник\nclass Цель\n"
                f"Источник -[{name}]-> Цель\n")


# ------------------------------------------------ конструктор структур ---


class StructDesigner(_Dialog):
    """Собирает блок ``struct`` — переиспользуемую структуру."""

    TEMPLATE = """Сервис ${Имя}Api as "$Имя API"
class ${Имя}Логика {
  + обработать(команда)
}
database $БД
${Имя}Api --> ${Имя}Логика
${Имя}Логика --> $БД"""

    def __init__(self, master, palette: str = "light") -> None:
        super().__init__(master, "Новая структура", palette)
        self.name = tk.StringVar(value="Трёхслойный")
        self.params = tk.StringVar(value="Имя, БД")
        self.prelude = tk.StringVar(value="")

    def build(self) -> None:
        super().build()
        grid = ttk.Frame(self.body_frame)
        grid.pack(fill="x")
        self.row(grid, 0, "Название структуры",
                 ttk.Entry(grid, textvariable=self.name, width=30),
                 "Имя, которым структура разворачивается в тексте: "
                 "«use Трёхслойный(Order, orders_db)»")
        self.row(grid, 1, "Параметры (через запятую)",
                 ttk.Entry(grid, textvariable=self.params, width=30),
                 "Имена подстановок. В теле ниже пишутся как $Имя или "
                 "${Имя} и заменяются аргументами при использовании")
        ttk.Label(self.body_frame,
                  text="Тело структуры "
                       "(параметры подставляются как $Имя или ${Имя})",
                  wraplength=330).pack(anchor="w", pady=(10, 4))
        self.body = tk.Text(self.body_frame, width=46, height=14, wrap="none",
                            font=("Consolas", 10), padx=6, pady=4)
        paint_text(self.body, ui_colors(self.palette))
        self.body.pack(fill="both", expand=True)
        self.body.insert("1.0", self.TEMPLATE)
        self.body.bind("<KeyRelease>", lambda e: self.schedule_preview())
        tooltip.attach(self.body, "Обычное описание диаграммы: объекты, их "
                                  "тела и связи. Отличие только в том, что "
                                  "вместо имён можно подставлять параметры")
        ttk.Label(self.body_frame,
                  text="Вставляется вместе со строкой use "
                       "для первого набора аргументов.",
                  foreground=ui_colors(self.palette)["muted"],
                  wraplength=330).pack(anchor="w",
                                                             pady=(6, 0))
        self.watch(self.name, self.params)

    def _param_list(self) -> list[str]:
        return [p.strip() for p in self.params.get().split(",") if p.strip()]

    def _block(self) -> str:
        name = self.name.get().strip() or "МояСтруктура"
        params = ", ".join(self._param_list())
        body = self.body.get("1.0", "end-1c").rstrip()
        indented = "\n".join("  " + line if line.strip() else ""
                             for line in body.split("\n"))
        return f"struct {name}({params}) {{\n{indented}\n}}"

    def _use(self) -> str:
        name = self.name.get().strip() or "МояСтруктура"
        args = ", ".join(self._param_list()) or ""
        return f"use {name}({args})"

    def snippet(self) -> str:
        return self._block() + "\n\n" + self._use() + "\n"

    def preview_source(self) -> str:
        extra = ""
        body = self.body.get("1.0", "end-1c")
        if "Сервис" in body:
            extra = "shape Сервис {\n  form: roundrect\n  accent: #00695c\n" \
                    "  stereotype: service\n}\n"
        return ("set padding = 14\nset shadow = off\n" + extra +
                self._block() + "\n\n" + self._use() + "\n")


# ------------------------------------------------------------- справка ----


class HelpWindow(tk.Toplevel):
    """Окно со справкой по синтаксису."""

    def __init__(self, master, palette: str = "light") -> None:
        super().__init__(master)
        self.title("Справка по синтаксису")
        self.geometry("820x680")
        self.transient(master)
        self.palette = palette
        c = ui_colors(palette)
        self.configure(background=c["bg"])
        native.apply_chrome(self, palette == "dark", c["bg"], c["fg"])

        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Поиск:").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.query, width=30)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._find())
        find = ttk.Button(bar, text="Найти", command=self._find)
        find.pack(side="left")
        tooltip.attach(find, "Найти следующее совпадение в справке  ·  Enter")
        close = ttk.Button(bar, text="Закрыть", command=self.destroy)
        close.pack(side="right")
        tooltip.attach(close, "Закрыть справку  ·  Esc")

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(holder, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.text = tk.Text(holder, wrap="none", font=("Consolas", 10),
                            padx=12, pady=10, yscrollcommand=scroll.set)
        paint_text(self.text, c)
        self.text.pack(fill="both", expand=True)
        scroll.configure(command=self.text.yview)
        self.text.insert("1.0", SYNTAX_HELP)
        self.text.tag_configure("found", background="#ffe08a",
                                foreground="#1f2a33")
        self.text.configure(state="disabled")
        self.bind("<Escape>", lambda e: self.destroy())
        self._last = "1.0"

    def set_palette(self, name: str) -> None:
        """Переключает оформление открытого окна справки."""
        self.palette = name
        c = ui_colors(name)
        self.configure(background=c["bg"])
        paint_text(self.text, c)
        native.apply_chrome(self, name == "dark", c["bg"], c["fg"])

    def _find(self) -> None:
        needle = self.query.get().strip()
        self.text.tag_remove("found", "1.0", "end")
        if not needle:
            return
        index = self.text.search(needle, self._last, nocase=True, stopindex="end")
        if not index:
            index = self.text.search(needle, "1.0", nocase=True, stopindex="end")
            if not index:
                return
        end = f"{index}+{len(needle)}c"
        self.text.tag_add("found", index, end)
        self.text.see(index)
        self._last = end
