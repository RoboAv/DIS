"""Темы, палитры и стили по умолчанию для встроенных видов объектов и связей."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import ImageColor

# ---------------------------------------------------------------- цвета ----


def to_rgb(color, fallback=(0, 0, 0)) -> tuple[int, int, int]:
    """Переводит любое представление цвета в RGB-кортеж."""
    if color is None:
        return fallback
    if isinstance(color, (tuple, list)):
        return tuple(int(c) for c in color[:3])
    try:
        return ImageColor.getrgb(str(color).strip())[:3]
    except (ValueError, AttributeError):
        return fallback


def to_hex(rgb) -> str:
    r, g, b = to_rgb(rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def mix(a, b, t: float) -> str:
    """Смешивает цвета: t=0 -> a, t=1 -> b."""
    ra, ga, ba = to_rgb(a)
    rb, gb, bb = to_rgb(b)
    t = max(0.0, min(1.0, t))
    return to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def lighten(color, t: float) -> str:
    return mix(color, "#ffffff", t)


def darken(color, t: float) -> str:
    return mix(color, "#000000", t)


def is_dark(color) -> bool:
    r, g, b = to_rgb(color)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


def readable_on(bg) -> str:
    return "#f2f5f7" if is_dark(bg) else "#18222a"


# ---------------------------------------------------------------- тема -----


@dataclass
class Theme:
    """Набор цветов и размеров, общий для всей диаграммы."""

    name: str = "light"
    bg: str = "#fbfcfd"
    surface: str = "#ffffff"
    ink: str = "#18222a"
    muted: str = "#6b7b87"
    line: str = "#4c606d"
    group_fill: str = "#f1f4f7"
    group_stroke: str = "#b3c0ca"
    accent: str = "#37474f"
    shadow: bool = True
    shadow_color: str = "#0b1a24"
    shadow_alpha: int = 46
    rounded: int = 6
    # отношение накладываемых оттенков: заливка = accent, смешанный с surface
    fill_tint: float = 0.90
    stroke_tint: float = 0.0
    font_family: str = ""
    font_size: int = 13
    title_size: int = 14
    small_size: int = 11
    diagram_title_size: int = 22

    # ---- производные цвета для конкретного «акцента» вида объекта ----
    def fill_for(self, accent: str) -> str:
        return mix(accent, self.surface, self.fill_tint)

    def stroke_for(self, accent: str) -> str:
        if self.stroke_tint <= 0:
            return to_hex(accent)
        return lighten(accent, self.stroke_tint)

    def text_for(self, accent: str) -> str:
        return readable_on(self.fill_for(accent))


THEMES: dict[str, Theme] = {
    "light": Theme(),
    "dark": Theme(
        name="dark",
        bg="#171c22",
        surface="#20272f",
        ink="#e6edf3",
        muted="#93a3b1",
        line="#8fa3b3",
        group_fill="#1c2329",
        group_stroke="#3d4a55",
        accent="#8fa3b3",
        shadow_color="#000000",
        shadow_alpha=90,
        fill_tint=0.78,
        stroke_tint=0.35,
    ),
    "mono": Theme(
        name="mono",
        bg="#ffffff",
        surface="#ffffff",
        ink="#111111",
        muted="#555555",
        line="#222222",
        group_fill="#f6f6f6",
        group_stroke="#999999",
        accent="#222222",
        shadow=False,
        fill_tint=1.0,
        rounded=0,
    ),
    "blueprint": Theme(
        name="blueprint",
        bg="#0f2b46",
        surface="#143b5c",
        ink="#e8f2ff",
        muted="#9dc2e6",
        line="#cfe3f7",
        group_fill="#123b5c",
        group_stroke="#3f7ba8",
        accent="#9dc2e6",
        shadow=False,
        fill_tint=0.80,
        stroke_tint=0.4,
    ),
}


def get_theme(name: str) -> Theme:
    return THEMES.get(str(name).strip().lower(), THEMES["light"])


# ------------------------------------------------- виды объектов (формы) ---

#: Формы, которые умеет рисовать renderer.
FORMS = (
    "rect",
    "roundrect",
    "stadium",
    "ellipse",
    "circle",
    "cylinder",
    "hexagon",
    "diamond",
    "cloud",
    "note",
    "folder",
    "component",
    "node3d",
    "queue",
    "document",
    "actor",
    "dot",
    "ring",
)

#: Во сколько раз форма больше содержимого (по ширине и высоте).
FORM_PADDING: dict[str, tuple[float, float]] = {
    "ellipse": (1.35, 1.60),
    "circle": (1.45, 1.45),
    "diamond": (1.75, 1.85),
    "cloud": (1.50, 1.75),
    "cylinder": (1.12, 1.45),
    "hexagon": (1.28, 1.05),
    "stadium": (1.20, 1.05),
    "note": (1.05, 1.00),
    "folder": (1.02, 1.00),
    "queue": (1.18, 1.00),
    "document": (1.02, 1.10),
    "node3d": (1.02, 1.02),
}

#: Встроенные виды объектов. accent задаёт цветовую гамму, form — геометрию.
KIND_DEFAULTS: dict[str, dict] = {
    "class": dict(form="rect", accent="#37474f", compartments=True),
    "abstract": dict(form="rect", accent="#455a64", compartments=True,
                     title_italic=True, stereotype="abstract"),
    "interface": dict(form="rect", accent="#2e7d32", compartments=True,
                      stereotype="interface"),
    "enum": dict(form="rect", accent="#b07d19", compartments=True,
                 stereotype="enum"),
    "entity": dict(form="rect", accent="#1565c0", compartments=True,
                   stereotype="entity"),
    "record": dict(form="rect", accent="#6a4fa3", compartments=True,
                   stereotype="struct"),
    "object": dict(form="rect", accent="#455a64", compartments=True,
                   title_underline=True),
    "exception": dict(form="rect", accent="#c62828", compartments=True,
                      stereotype="exception"),
    "component": dict(form="component", accent="#00695c", compartments=True),
    "boundary": dict(form="roundrect", accent="#4527a0", compartments=True),
    "state": dict(form="roundrect", accent="#00838f", compartments=True),
    "node": dict(form="node3d", accent="#5d4037"),
    "database": dict(form="cylinder", accent="#0277bd"),
    "queue": dict(form="queue", accent="#7b1fa2"),
    "cloud": dict(form="cloud", accent="#0288d1"),
    "folder": dict(form="folder", accent="#8d6e63"),
    "artifact": dict(form="document", accent="#546e7a"),
    "actor": dict(form="actor", accent="#37474f"),
    "usecase": dict(form="ellipse", accent="#6d4c41"),
    "action": dict(form="stadium", accent="#2e7d32"),
    "decision": dict(form="diamond", accent="#ef6c00"),
    "start": dict(form="dot", accent="#37474f"),
    "stop": dict(form="ring", accent="#37474f"),
    # «чистая геометрия» — удобно для схем свободной формы
    "box": dict(form="rect", accent="#37474f"),
    "hexagon": dict(form="hexagon", accent="#455a64"),
    "ellipse": dict(form="ellipse", accent="#455a64"),
    "circle": dict(form="circle", accent="#455a64"),
    "note": dict(form="note", accent="#c9a227"),
}

#: Псевдонимы видов объектов.
KIND_ALIASES: dict[str, str] = {
    "struct": "record",
    "abstract class": "abstract",
    "interfase": "interface",
    "класс": "class",
    "интерфейс": "interface",
    "перечисление": "enum",
    "сущность": "entity",
    "объект": "object",
    "структура": "record",
    "компонент": "component",
    "база": "database",
    "бд": "database",
    "актор": "actor",
    "заметка": "note",
    "узел": "node",
    "очередь": "queue",
    "облако": "cloud",
    "папка": "folder",
    "действие": "action",
    "решение": "decision",
    "состояние": "state",
    "начало": "start",
    "конец": "stop",
}

# ------------------------------------------------------------ связи -------

#: Как рисовать окончания связей.
DECORATIONS = (
    "none",
    "arrow",
    "arrow_filled",
    "triangle",
    "triangle_filled",
    "diamond",
    "diamond_filled",
    "circle",
    "circle_filled",
    "cross",
    "bar",
    "crowfoot",
)

#: Символ окончания -> украшение. Используется парсером коннекторов.
TAIL_SYMBOLS = {
    "<|": "triangle",
    "<": "arrow",
    "*": "diamond_filled",
    "o": "diamond",
    "+": "circle",
    "x": "cross",
    "#": "bar",
    "}": "crowfoot",
    "{": "crowfoot",
}
HEAD_SYMBOLS = {
    "|>": "triangle",
    ">": "arrow",
    "*": "diamond_filled",
    "o": "diamond",
    "+": "circle",
    "x": "cross",
    "#": "bar",
    "{": "crowfoot",
    "}": "crowfoot",
}

#: Стиль линии по символу.
LINE_SYMBOLS = {"-": "solid", ".": "dotted", "=": "bold", "~": "dashed"}

#: Именованные виды связей: используются как `A -[flow]-> B`.
LINK_DEFAULTS: dict[str, dict] = {
    "line": dict(line="solid", head="none", tail="none"),
    "association": dict(line="solid", head="arrow", tail="none"),
    "bidir": dict(line="solid", head="arrow", tail="arrow"),
    "inheritance": dict(line="solid", head="triangle", tail="none"),
    "realization": dict(line="dashed", head="triangle", tail="none"),
    "dependency": dict(line="dashed", head="arrow", tail="none"),
    "composition": dict(line="solid", head="none", tail="diamond_filled"),
    "aggregation": dict(line="solid", head="none", tail="diamond"),
    "flow": dict(line="solid", head="arrow_filled", tail="none", width=2.0),
    "note": dict(line="dotted", head="none", tail="none"),
}

LINK_ALIASES = {
    "assoc": "association",
    "extends": "inheritance",
    "inherit": "inheritance",
    "implements": "realization",
    "realize": "realization",
    "depends": "dependency",
    "uses": "dependency",
    "use": "dependency",
    "has": "aggregation",
    "owns": "composition",
    "наследование": "inheritance",
    "реализация": "realization",
    "зависимость": "dependency",
    "композиция": "composition",
    "агрегация": "aggregation",
    "ассоциация": "association",
    "поток": "flow",
}

LINE_STYLES = ("solid", "dashed", "dotted", "bold")


def normalize_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    return KIND_ALIASES.get(k, k)


def normalize_link(name: str) -> str:
    n = (name or "").strip().lower()
    return LINK_ALIASES.get(n, n)
