"""Шрифты, разрешение стилей и обмер объектов.

Модуль — единственное место, где текст превращается в размеры. И раскладка,
и рисование пользуются одним и тем же обмером, поэтому картинка всегда
соответствует расчёту.
"""

from __future__ import annotations

import os
import textwrap

from PIL import ImageFont

from .model import Diagram, Edge, Node
from .theme import (
    FORM_PADDING,
    KIND_DEFAULTS,
    LINK_DEFAULTS,
    Theme,
    darken,
    lighten,
    mix,
    normalize_link,
    readable_on,
)

#: Известные семейства: (обычный, жирный, курсив, жирный курсив).
FAMILY_FILES: dict[str, tuple[str, str, str, str]] = {
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "courier new": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "cascadia mono": ("CascadiaMono.ttf",) * 4,
    "times new roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "dejavu sans": (
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans-Oblique.ttf",
        "DejaVuSans-BoldOblique.ttf",
    ),
}

FALLBACK_ORDER = ("segoe ui", "arial", "tahoma", "dejavu sans")

#: Цвета маркеров видимости, как в большинстве UML-инструментов.
VISIBILITY_COLORS = {
    "+": "#3f8f3f",
    "-": "#c0392b",
    "#": "#d98324",
    "~": "#2e6f9e",
}


class FontBook:
    """Кэш загруженных шрифтов с аккуратным откатом на доступные файлы."""

    def __init__(self, family: str = "") -> None:
        self._cache: dict[tuple[int, bool, bool], ImageFont.FreeTypeFont] = {}
        self._files = self._resolve_family(family)

    @staticmethod
    def _font_dirs() -> list[str]:
        dirs = []
        win = os.environ.get("WINDIR")
        if win:
            dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
        dirs += [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts",
            "/Library/Fonts",
            "/System/Library/Fonts",
        ]
        return dirs

    def _try_load(self, name: str) -> str | None:
        if os.path.isfile(name):
            return name
        for folder in self._font_dirs():
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
        try:
            ImageFont.truetype(name, 12)
            return name
        except OSError:
            return None

    def _resolve_family(self, family: str) -> tuple[str, str, str, str] | None:
        names = []
        if family:
            key = family.strip().lower()
            if key in FAMILY_FILES:
                names.append(key)
            else:
                custom = self._try_load(family)
                if custom:
                    return (custom,) * 4
        names += [f for f in FALLBACK_ORDER if f not in names]
        for key in names:
            files = FAMILY_FILES[key]
            resolved = [self._try_load(f) for f in files]
            if resolved[0]:
                base = resolved[0]
                return tuple(r or base for r in resolved)  # type: ignore[return-value]
        return None

    def get(self, size: int, bold: bool = False, italic: bool = False):
        size = max(6, int(round(size)))
        key = (size, bold, italic)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        font = None
        if self._files:
            index = (1 if bold else 0) + (2 if italic else 0)
            try:
                font = ImageFont.truetype(self._files[index], size)
            except OSError:
                font = None
        if font is None:
            font = ImageFont.load_default(size)
        self._cache[key] = font
        return font

    def width(self, text: str, size: int, bold=False, italic=False) -> float:
        if not text:
            return 0.0
        return float(self.get(size, bold, italic).getlength(text))

    def line_height(self, size: int, bold=False, italic=False) -> float:
        ascent, descent = self.get(size, bold, italic).getmetrics()
        return float(ascent + descent)


class StyleResolver:
    """Сводит тему, встроенные виды и пользовательские объявления в один стиль."""

    def __init__(self, diagram: Diagram, theme: Theme, scale: float = 1.0) -> None:
        self.d = diagram
        self.t = theme
        self.scale = max(0.25, float(scale))
        family = str(diagram.opt("font", theme.font_family) or "")
        self.fonts = FontBook(family)
        self.base_size = int(diagram.opt("font_size", theme.font_size) or theme.font_size)
        self.title_size = self.base_size + 1
        self.small_size = max(8, self.base_size - 2)
        self._kinds: dict[str, dict] = {}

    # ----------------------------------------------------------- метрики --

    def px(self, value: float) -> float:
        return value * self.scale

    def fs(self, size: float) -> int:
        return max(6, int(round(size * self.scale)))

    def font_width(self, text: str, size: float, bold=False, italic=False) -> float:
        return self.fonts.width(text, self.fs(size), bold, italic)

    def font_height(self, size: float, bold=False, italic=False) -> float:
        return self.fonts.line_height(self.fs(size), bold, italic)

    # ------------------------------------------------------- виды/стили ---

    def kind_style(self, kind: str) -> dict:
        cached = self._kinds.get(kind)
        if cached is not None:
            return cached
        shape = self.d.shapes.get(kind)
        if shape is not None:
            base = dict(KIND_DEFAULTS.get(shape.base, KIND_DEFAULTS["class"]))
            base.update(shape.as_style())
        else:
            base = dict(KIND_DEFAULTS.get(kind, KIND_DEFAULTS["class"]))
        style = self._complete(base)
        self._kinds[kind] = style
        return style

    def _complete(self, base: dict) -> dict:
        accent = base.get("accent") or self.t.accent
        style = {
            "form": base.get("form", "rect"),
            "accent": accent,
            "fill": base.get("fill") or self.t.fill_for(accent),
            "stroke": base.get("stroke") or self.t.stroke_for(accent),
            "stroke_width": float(base.get("stroke_width", 1.4)),
            "compartments": bool(base.get("compartments", False)),
            "title_italic": bool(base.get("title_italic", False)),
            "title_underline": bool(base.get("title_underline", False)),
            "stereotype": base.get("stereotype", ""),
            "sections": list(base.get("sections", [])),
            "dashed": bool(base.get("dashed", False)),
            "solid": bool(base.get("solid", False)),
            "font_size": base.get("font_size"),
        }
        style["text"] = base.get("text") or readable_on(style["fill"])
        return style

    def node_style(self, node: Node) -> dict:
        style = dict(self.kind_style(node.kind))
        overrides = {k: v for k, v in node.style.items() if not k.startswith("_")}
        if "fill" in overrides:
            style["fill"] = overrides["fill"]
            style["text"] = readable_on(style["fill"])
            if "stroke" not in overrides:
                style["stroke"] = darken(overrides["fill"], 0.45)
        style.update(overrides)
        return style

    def edge_style(self, edge: Edge) -> dict:
        data = dict(LINK_DEFAULTS.get(normalize_link(edge.kind), {}))
        custom = self.d.links.get(edge.kind)
        if custom is not None:
            data.update(custom.as_style())
        color = edge.color or data.get("color") or self.t.line
        width = edge.width or data.get("width") or 1.4
        return {
            "color": color,
            "width": max(0.8, float(width)) * max(1.0, self.scale * 0.9),
            "line": edge.line or data.get("line", "solid"),
            "head": edge.head,
            "tail": edge.tail,
            "hidden": color == "hidden",
            "label_color": self.t.ink,
            "label_bg": self.t.bg,
            "mult_color": self.t.muted,
        }

    def group_style(self, group) -> dict:
        fill = group.style.get("fill") or self.t.group_fill
        return {
            "fill": fill,
            "stroke": group.style.get("stroke") or self.t.group_stroke,
            "text": group.style.get("text") or readable_on(fill),
            "header_fill": mix(fill, self.t.group_stroke, 0.25),
            "stereotype": group.style.get("stereotype", ""),
            "dashed": group.kind in ("namespace", "frame"),
        }

    # -------------------------------------------------------- обмер узла --

    def measure_node(self, node: Node) -> None:
        style = self.node_style(node)
        form = style["form"]
        body_size = style.get("font_size") or self.base_size
        title_size = body_size + 1
        is_rect = form in ("rect", "roundrect", "component", "node3d", "note", "folder")
        centered = not is_rect or form == "note" and False
        align_title = "left" if form == "note" else "center"
        align_member = "left" if is_rect else "center"

        rows: list[dict] = []
        stereo = node.stereotype or style.get("stereotype") or ""
        if stereo and form != "note":
            text = stereo if stereo.startswith("«") else f"«{stereo}»"
            rows.append(self._text_row("stereotype", text, self.small_size,
                                       italic=True, align="center",
                                       color=self._muted_on(style["fill"])))

        for line in self._title_lines(node, form):
            rows.append(
                self._text_row(
                    "title", line, title_size, bold=form != "note",
                    italic=style["title_italic"], align=align_title,
                    underline=style["title_underline"], color=style["text"],
                )
            )

        if style["compartments"]:
            for comp in node.compartments:
                if not comp.members and not comp.title:
                    continue
                rows.append({"type": "sep", "w": 0.0, "h": self.px(7),
                             "style": "solid"})
                if comp.title:
                    rows.append(
                        self._text_row("section", comp.title, self.small_size,
                                       bold=True, align="left",
                                       color=self._muted_on(style["fill"]))
                    )
                for member in comp.members:
                    rows.append(self._member_row(member, body_size, style,
                                                 align_member))

        pad_x = self.px(14)
        pad_y = self.px(9)
        content_w = max([r["w"] for r in rows], default=self.px(30))
        content_h = sum(r["h"] for r in rows) + self.px(2) * max(0, len(rows) - 1)
        box_w = content_w + 2 * pad_x
        box_h = content_h + 2 * pad_y

        grow_w, grow_h = FORM_PADDING.get(form, (1.0, 1.0))
        box_w *= grow_w
        box_h *= grow_h
        if form == "circle":
            size = max(box_w, box_h, self.px(34))
            box_w = box_h = size
        if form == "actor":
            box_h += self.px(34)
        if form in ("dot", "ring"):
            box_h += self.px(28)
            box_w = max(box_w, self.px(32))

        min_w = self.px(74 if style["compartments"] else 52)
        box_w = max(box_w, min_w)
        box_h = max(box_h, self.px(30))

        node.rows = rows
        node.w = round(box_w)
        node.h = round(box_h)
        node.metrics = {
            "content_w": content_w,
            "content_h": content_h,
            "pad_x": pad_x,
            "pad_y": pad_y,
            "centered": centered,
            "form": form,
            "row_gap": self.px(2),
        }

    def _title_lines(self, node: Node, form: str) -> list[str]:
        raw = node.title.replace("\\n", "\n")
        if form == "note":
            limit = int(self.d.opt("note_width", 34) or 34)
            out: list[str] = []
            for chunk in raw.split("\n"):
                out.extend(textwrap.wrap(chunk, limit) or [""])
            return out or [""]
        return raw.split("\n")

    def _text_row(self, kind: str, text: str, size: float, bold=False,
                  italic=False, align="center", underline=False,
                  color: str | None = None) -> dict:
        return {
            "type": kind,
            "text": text,
            "size": size,
            "bold": bold,
            "italic": italic,
            "align": align,
            "underline": underline,
            "color": color,
            "w": self.font_width(text, size, bold, italic),
            "h": self.font_height(size, bold, italic) + self.px(3),
        }

    def _member_row(self, member, size: float, style: dict, align: str) -> dict:
        marker = self.px(11) if member.visibility else 0.0
        gap = self.px(6) if member.visibility else 0.0
        italic = member.abstract
        row = self._text_row("member", member.text, size, italic=italic,
                             align=align, underline=member.static,
                             color=style["text"])
        row["vis"] = member.visibility
        row["marker"] = marker
        row["gap"] = gap
        row["w"] = row["w"] + marker + gap
        return row

    def _muted_on(self, fill: str) -> str:
        base = readable_on(fill)
        return lighten(base, 0.35) if base.startswith("#1") else darken(base, 0.25)

    # ----------------------------------------------------- прочие обмеры --

    def group_metrics(self, group) -> dict:
        size = self.base_size + 1
        header = self.font_height(size, bold=True) + self.px(10)
        return {
            "header_h": header,
            "pad": self.px(18),
            "font_size": size,
            "label_w": self.font_width(group.title, size, bold=True) + self.px(28),
        }

    def edge_label_size(self, text: str) -> tuple[float, float]:
        if not text:
            return 0.0, 0.0
        lines = text.replace("\\n", "\n").split("\n")
        w = max(self.font_width(line, self.small_size + 1) for line in lines)
        h = self.font_height(self.small_size + 1) * len(lines)
        return w + self.px(8), h + self.px(4)
