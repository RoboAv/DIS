"""Объектная модель диаграммы.

Структура строго отделена от синтаксиса: парсер наполняет эти классы,
раскладка расставляет координаты, renderer только рисует.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Member:
    """Строка внутри объекта: поле, метод, значение перечисления."""

    text: str = ""
    visibility: str = ""      # '+', '-', '#', '~' или ''
    static: bool = False
    abstract: bool = False


@dataclass
class Compartment:
    """Секция объекта. У пользовательских видов может иметь заголовок."""

    title: str = ""
    members: list[Member] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.members and not self.title


@dataclass
class Node:
    """Объект диаграммы (класс, интерфейс, БД, пользовательский вид...)."""

    name: str
    kind: str = "class"
    label: str = ""
    stereotype: str = ""
    compartments: list[Compartment] = field(default_factory=list)
    group: str | None = None
    style: dict[str, Any] = field(default_factory=dict)
    src_line: int = 0

    # --- результат раскладки (в пикселях итогового изображения) ---
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    rows: list[dict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.label or self.name

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class Edge:
    """Связь между двумя объектами.

    `a` — левый операнд в тексте, `b` — правый. При раскладке сверху вниз
    `a` оказывается выше `b` (как в PlantUML).
    """

    a: str
    b: str
    kind: str = "association"
    label: str = ""
    a_mult: str = ""
    b_mult: str = ""
    tail: str = "none"        # украшение у конца `a`
    head: str = "arrow"       # украшение у конца `b`
    line: str = "solid"       # solid | dashed | dotted | bold
    color: str | None = None
    width: float | None = None
    direction: str = ""       # грань выхода: '', 'up', 'down', 'same', 'left', 'right'
    arrive: str = ""          # грань входа для notowning; пусто — ближайшая, кроме нижней
    notowning: bool = False   # линия есть, на раскладку блоков не влияет
    min_span: int = 1         # минимум уровней: 1 для «--», дальше по символу линии
    src_line: int = 0

    # --- результат раскладки ---
    points: list[tuple[float, float]] = field(default_factory=list)
    label_pos: tuple[float, float] | None = None


@dataclass
class Group:
    """Контейнер: package / namespace / frame / group."""

    name: str
    label: str = ""
    kind: str = "package"
    parent: str | None = None
    style: dict[str, Any] = field(default_factory=dict)
    src_line: int = 0

    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    header_h: float = 0.0

    @property
    def title(self) -> str:
        return self.label or self.name

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class ShapeDef:
    """Пользовательский вид объекта, объявленный блоком `shape`."""

    name: str
    form: str = "rect"
    accent: str | None = None
    fill: str | None = None
    stroke: str | None = None
    text: str | None = None
    stroke_width: float | None = None
    dashed: bool = False
    stereotype: str = ""
    sections: list[str] = field(default_factory=list)
    font_size: int | None = None
    compartments: bool = True
    title_italic: bool = False
    title_underline: bool = False
    base: str = "class"
    src_line: int = 0

    def as_style(self) -> dict:
        """Превращает объявление в словарь стиля вида объекта."""
        out: dict[str, Any] = {
            "form": self.form,
            "compartments": self.compartments,
            "title_italic": self.title_italic,
            "title_underline": self.title_underline,
            "sections": list(self.sections),
            "dashed": self.dashed,
        }
        if self.accent:
            out["accent"] = self.accent
        if self.fill:
            out["fill"] = self.fill
        if self.stroke:
            out["stroke"] = self.stroke
        if self.text:
            out["text"] = self.text
        if self.stroke_width is not None:
            out["stroke_width"] = self.stroke_width
        if self.stereotype:
            out["stereotype"] = self.stereotype
        if self.font_size is not None:
            out["font_size"] = self.font_size
        return out


@dataclass
class LinkDef:
    """Пользовательский вид связи, объявленный блоком `link`."""

    name: str
    line: str = "solid"
    head: str = "arrow"
    tail: str = "none"
    color: str | None = None
    width: float | None = None
    label: str = ""
    src_line: int = 0

    def as_style(self) -> dict:
        out: dict[str, Any] = {
            "line": self.line,
            "head": self.head,
            "tail": self.tail,
        }
        if self.color:
            out["color"] = self.color
        if self.width is not None:
            out["width"] = self.width
        if self.label:
            out["label"] = self.label
        return out


@dataclass
class StructDef:
    """Пользовательская структура — переиспользуемый шаблон из объектов и связей."""

    name: str
    params: list[str] = field(default_factory=list)
    body: list[tuple[int, str]] = field(default_factory=list)
    src_line: int = 0


@dataclass
class Diagram:
    """Полное описание диаграммы."""

    title: str = ""
    caption: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    shapes: dict[str, ShapeDef] = field(default_factory=dict)
    links: dict[str, LinkDef] = field(default_factory=dict)
    structs: dict[str, StructDef] = field(default_factory=dict)
    legend: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    # --- габариты после раскладки ---
    width: float = 0.0
    height: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)

    def opt(self, key: str, default=None):
        return self.options.get(key, default)

    def node(self, name: str) -> Node | None:
        return self.nodes.get(name)

    def ensure_node(self, name: str, kind: str = "class", line: int = 0,
                    group: str | None = None) -> Node:
        node = self.nodes.get(name)
        if node is None:
            node = Node(name=name, kind=kind, group=group, src_line=line)
            self.nodes[name] = node
        return node

    def group_path(self, name: str | None) -> list[str]:
        """Цепочка групп от корня до указанной."""
        chain: list[str] = []
        seen: set[str] = set()
        cur = name
        while cur and cur in self.groups and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = self.groups[cur].parent
        chain.reverse()
        return chain

    def is_empty(self) -> bool:
        return not self.nodes and not self.groups
