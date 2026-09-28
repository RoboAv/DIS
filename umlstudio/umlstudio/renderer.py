"""Отрисовка размеченной диаграммы в изображение Pillow."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

from .arrows import draw_decoration
from .geometry import (
    dash_pattern,
    point_at,
    polyline_length,
    round_corners,
)
from .model import Diagram, Edge, Group, Node
from .shapes import ShapeStyle, content_inset, draw_form, horizontal_chords
from .style import VISIBILITY_COLORS, StyleResolver
from .theme import Theme, to_rgb

Color = tuple[int, int, int, int]

DASH_PATTERNS = {
    "solid": None,
    "dashed": (8.0, 5.0),
    "dotted": (2.2, 3.8),
    "bold": None,
}


def _rgba(color, alpha: int = 255) -> Color:
    r, g, b = to_rgb(color)
    return (r, g, b, max(0, min(255, alpha)))


class Renderer:
    """Переводит модель с координатами в картинку."""

    def __init__(self, diagram: Diagram, style: StyleResolver,
                 theme: Theme) -> None:
        self.d = diagram
        self.s = style
        self.t = theme
        self.scale = style.scale
        self.transparent = bool(diagram.opt("transparent", False))
        self.bg = _rgba(diagram.opt("bg", theme.bg), 0 if self.transparent else 255)
        self.corner = float(diagram.metrics.get("corner", style.px(7)))

    # ---------------------------------------------------------------- api --

    def render(self) -> Image.Image:
        width = max(1, int(math.ceil(self.d.width)))
        height = max(1, int(math.ceil(self.d.height)))
        image = Image.new("RGBA", (width, height), self.bg)
        draw = ImageDraw.Draw(image)

        if self.d.opt("grid"):
            self._draw_grid(draw, width, height)
        if bool(self.d.opt("shadow", self.t.shadow)):
            self._compose_shadows(image)

        for group in self._groups_outside_in():
            self._draw_group(draw, group)
        for edge in self.d.edges:
            self._draw_edge(draw, image, edge)
        for node in self.d.nodes.values():
            self._draw_node(draw, node)
        self._draw_captions(draw, width, height)
        return image

    # ------------------------------------------------------------- фоны ----

    def _draw_grid(self, draw: ImageDraw.ImageDraw, width: int,
                   height: int) -> None:
        step = self.s.px(24)
        color = _rgba(self.t.group_stroke, 48)
        x = step
        while x < width:
            draw.line([(x, 0), (x, height)], fill=color, width=1)
            x += step
        y = step
        while y < height:
            draw.line([(0, y), (width, y)], fill=color, width=1)
            y += step

    def _compose_shadows(self, image: Image.Image) -> None:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        color = _rgba(self.t.shadow_color, self.t.shadow_alpha)
        offset = self.s.px(2.5)
        blank = _rgba(self.t.shadow_color, 0)
        for group in self.d.groups.values():
            st = ShapeStyle(fill=color, stroke=blank, width=0,
                            radius=self.s.px(10), scale=self.scale)
            draw_form(draw, "rect", (group.x, group.y + offset,
                                     group.x + group.w, group.y + group.h + offset),
                      st)
        for node in self.d.nodes.values():
            form = self.s.node_style(node)["form"]
            st = ShapeStyle(fill=color, stroke=blank, width=0,
                            radius=self.s.px(self.t.rounded), scale=self.scale)
            draw_form(draw, form, (node.x, node.y + offset,
                                   node.x + node.w, node.y + node.h + offset), st)
        layer = layer.filter(ImageFilter.GaussianBlur(self.s.px(3.4)))
        image.alpha_composite(layer)

    # ----------------------------------------------------------- группы ----

    def _groups_outside_in(self) -> list[Group]:
        def depth(group: Group) -> int:
            return len(self.d.group_path(group.name))

        return sorted(self.d.groups.values(), key=depth)

    def _draw_group(self, draw: ImageDraw.ImageDraw, group: Group) -> None:
        st = self.s.group_style(group)
        box = (group.x, group.y, group.x + group.w, group.y + group.h)
        shape = ShapeStyle(fill=_rgba(st["fill"]), stroke=_rgba(st["stroke"]),
                           width=self.s.px(1.3), dashed=st["dashed"],
                           radius=self.s.px(10), scale=self.scale)
        draw_form(draw, "rect", box, shape)

        metrics = self.s.group_metrics(group)
        header = group.header_h or metrics["header_h"]
        self._draw_inside_line(draw, "rect", box, shape.radius, shape.scale,
                               group.y + header, _rgba(st["stroke"], 150))

        size = metrics["font_size"]
        font = self.s.fonts.get(self.s.fs(size), bold=True)
        text_h = self.s.font_height(size, bold=True)
        tx = group.x + metrics["pad"] * 0.7
        ty = group.y + (header - text_h) / 2
        title = group.title
        if st["stereotype"]:
            small = self.s.fonts.get(self.s.fs(self.s.small_size), italic=True)
            draw.text((tx, ty), f"«{st['stereotype']}» ", font=small,
                      fill=_rgba(st["text"], 190), anchor="la")
            tx += self.s.font_width(f"«{st['stereotype']}» ", self.s.small_size,
                                    italic=True)
        draw.text((tx, ty), title, font=font, fill=_rgba(st["text"]), anchor="la")

    # ----------------------------------------------------------- объекты ---

    def _draw_node(self, draw: ImageDraw.ImageDraw, node: Node) -> None:
        st = self.s.node_style(node)
        form = st["form"]
        box = node.box()
        shape = ShapeStyle(
            fill=_rgba(st["fill"]),
            stroke=_rgba(st["stroke"]),
            width=self.s.px(float(st["stroke_width"])),
            dashed=bool(st["dashed"]),
            radius=self.s.px(self.t.rounded),
            scale=self.scale,
        )
        draw_form(draw, form, box, shape)
        self._draw_rows(draw, node, st, form)

    def _draw_rows(self, draw: ImageDraw.ImageDraw, node: Node, st: dict,
                   form: str) -> None:
        metrics = node.metrics
        cx0, cy0, cx1, cy1 = content_inset(form, node.box(), self.scale)
        pad_x = metrics.get("pad_x", self.s.px(14))
        gap = metrics.get("row_gap", self.s.px(2))
        content_h = metrics.get("content_h", 0.0)
        left = cx0 + pad_x
        right = cx1 - pad_x
        y = cy0 + max(0.0, ((cy1 - cy0) - content_h) / 2)
        radius = self.s.px(self.t.rounded)

        for row in node.rows:
            height = row["h"]
            if row["type"] == "sep":
                mid = y + height / 2
                self._draw_inside_line(draw, form, node.box(), radius, self.scale,
                                       mid, _rgba(st["stroke"], 110))
                y += height + gap
                continue
            self._draw_text_row(draw, row, st, left, right, y)
            y += height + gap

    def _draw_inside_line(self, draw: ImageDraw.ImageDraw, form: str,
                          box: tuple[float, float, float, float], radius: float,
                          scale: float, y: float, color: Color) -> None:
        """Горизонталь строго внутри формы: концы лежат на её границе."""
        for x0, x1 in horizontal_chords(form, box, y, radius, scale):
            draw.line([(x0, y), (x1, y)], fill=color, width=1)

    def _draw_text_row(self, draw: ImageDraw.ImageDraw, row: dict, st: dict,
                       left: float, right: float, y: float) -> None:
        font = self.s.fonts.get(self.s.fs(row["size"]), row["bold"], row["italic"])
        color = _rgba(row.get("color") or st["text"])
        marker = row.get("marker", 0.0)
        gap = row.get("gap", 0.0)
        text_w = row["w"]
        if row["align"] == "center":
            x = (left + right) / 2 - text_w / 2
        else:
            x = left
        baseline_y = y + self.s.px(1.5)

        if marker and row.get("vis"):
            self._draw_visibility(draw, row["vis"], x, baseline_y, marker)
        tx = x + marker + gap
        draw.text((tx, baseline_y), row["text"], font=font, fill=color, anchor="la")
        if row.get("underline"):
            ascent, _ = font.getmetrics()
            uy = baseline_y + ascent + self.s.px(1)
            draw.line([(tx, uy), (tx + text_w - marker - gap, uy)],
                      fill=color, width=1)

    def _draw_visibility(self, draw: ImageDraw.ImageDraw, vis: str, x: float,
                         y: float, size: float) -> None:
        color = _rgba(VISIBILITY_COLORS.get(vis, self.t.muted))
        pad = size * 0.12
        box = (x + pad, y + pad * 1.6, x + size - pad, y + size - pad * 0.4)
        if vis == "+":
            draw.rectangle(box, fill=color)
        elif vis == "-":
            draw.rectangle(box, outline=color, width=max(1, int(self.s.px(1.4))))
        elif vis == "#":
            draw.ellipse(box, fill=color)
        else:
            draw.ellipse(box, outline=color, width=max(1, int(self.s.px(1.4))))

    # ------------------------------------------------------------- связи ---

    def _draw_edge(self, draw: ImageDraw.ImageDraw, image: Image.Image,
                   edge: Edge) -> None:
        st = self.s.edge_style(edge)
        points = list(edge.points)
        if st["hidden"] or len(points) < 2:
            return
        color = _rgba(st["color"])
        width = st["width"]
        if st["line"] == "bold":
            width *= 1.9
        line_w = max(1, int(round(width)))
        background = _rgba(self._local_background(edge))

        head_dir = self._direction(points[-2], points[-1])
        tail_dir = self._direction(points[1], points[0])
        head_inset = draw_decoration(draw, st["head"], points[-1], head_dir,
                                     color, background, width, self.scale)
        tail_inset = draw_decoration(draw, st["tail"], points[0], tail_dir,
                                     color, background, width, self.scale)

        path = _trim(points, tail_inset, head_inset)
        if len(path) >= 2:
            smooth = round_corners(path, self.corner) if len(path) > 2 else path
            pattern = DASH_PATTERNS.get(st["line"])
            if pattern:
                on, off = pattern[0] * self.scale, pattern[1] * self.scale
                for chunk in dash_pattern(smooth, on, off):
                    draw.line(chunk, fill=color, width=line_w)
            else:
                draw.line(smooth, fill=color, width=line_w, joint="curve")

        self._draw_edge_label(draw, edge, st)
        self._draw_multiplicity(draw, points, edge.a_mult, st, True)
        self._draw_multiplicity(draw, points, edge.b_mult, st, False)

    @staticmethod
    def _direction(origin, tip) -> tuple[float, float]:
        dx, dy = tip[0] - origin[0], tip[1] - origin[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return (0.0, 1.0)
        return (dx / length, dy / length)

    def _local_background(self, edge: Edge) -> str:
        node = self.d.nodes.get(edge.b) or self.d.nodes.get(edge.a)
        if node is not None and node.group:
            group = self.d.groups.get(node.group)
            if group is not None:
                return self.s.group_style(group)["fill"]
        return self.d.opt("bg", self.t.bg)

    def _draw_edge_label(self, draw: ImageDraw.ImageDraw, edge: Edge,
                         st: dict) -> None:
        if not edge.label or not edge.label_pos:
            return
        lines = edge.label.replace("\\n", "\n").split("\n")
        size = self.s.small_size + 1
        font = self.s.fonts.get(self.s.fs(size))
        line_h = self.s.font_height(size)
        width = max(self.s.font_width(line, size) for line in lines)
        height = line_h * len(lines)
        cx, cy = edge.label_pos
        pad = self.s.px(3)
        draw.rectangle((cx - width / 2 - pad, cy - height / 2 - pad * 0.6,
                        cx + width / 2 + pad, cy + height / 2 + pad * 0.6),
                       fill=_rgba(self._local_background(edge), 225))
        y = cy - height / 2
        for line in lines:
            draw.text((cx, y), line, font=font,
                      fill=_rgba(st["label_color"]), anchor="ma")
            y += line_h

    def _draw_multiplicity(self, draw: ImageDraw.ImageDraw, points: list,
                           text: str, st: dict, at_start: bool) -> None:
        if not text:
            return
        total = polyline_length(points)
        if total < 1e-6:
            return
        distance = min(self.s.px(20), total * 0.35)
        fraction = distance / total if at_start else 1 - distance / total
        anchor, direction = point_at(points, fraction)
        side = (-direction[1], direction[0])
        size = self.s.small_size
        width = self.s.font_width(text, size)
        height = self.s.font_height(size)
        offset = abs(side[0]) * (width / 2) + abs(side[1]) * (height / 2)
        offset += self.s.px(4)
        if side[0] < 0 or (abs(side[0]) < 1e-6 and side[1] < 0):
            side = (-side[0], -side[1])
        cx = anchor[0] + side[0] * offset
        cy = anchor[1] + side[1] * offset
        font = self.s.fonts.get(self.s.fs(size))
        draw.text((cx, cy), text, font=font, fill=_rgba(st["mult_color"]),
                  anchor="mm")

    # ------------------------------------------------ заголовок и легенда --

    def _draw_captions(self, draw: ImageDraw.ImageDraw, width: int,
                       height: int) -> None:
        padding = self.d.metrics.get("padding", self.s.px(28))
        if self.d.title:
            size = float(self.d.opt("title_size", 0) or 0) or self.s.base_size + 8
            font = self.s.fonts.get(self.s.fs(size), bold=True)
            line_h = self.s.font_height(size, bold=True)
            y = padding * 0.6
            for line in self.d.title.split("\n"):
                draw.text((width / 2, y), line, font=font,
                          fill=_rgba(self.t.ink), anchor="ma")
                y += line_h
        bottom = height - padding * 0.5
        if self.d.legend:
            bottom = self._draw_legend(draw, padding, bottom)
        if self.d.caption:
            size = self.s.base_size
            font = self.s.fonts.get(self.s.fs(size), italic=True)
            draw.text((width / 2, bottom - self.s.font_height(size)),
                      self.d.caption, font=font,
                      fill=_rgba(self.t.muted), anchor="la")

    def _draw_legend(self, draw: ImageDraw.ImageDraw, padding: float,
                     bottom: float) -> float:
        size = self.s.small_size + 1
        font = self.s.fonts.get(self.s.fs(size))
        line_h = self.s.font_height(size) + self.s.px(3)
        box_h = line_h * len(self.d.legend) + self.s.px(14)
        box_w = max(self.s.font_width(line, size)
                    for line in self.d.legend) + self.s.px(24)
        x0 = padding
        y0 = bottom - box_h
        draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h),
                               radius=self.s.px(6),
                               fill=_rgba(self.t.group_fill, 235),
                               outline=_rgba(self.t.group_stroke), width=1)
        y = y0 + self.s.px(7)
        for line in self.d.legend:
            draw.text((x0 + self.s.px(12), y), line, font=font,
                      fill=_rgba(self.t.ink), anchor="la")
            y += line_h
        return y0 - self.s.px(8)


def _trim(points: list, start: float, end: float) -> list:
    """Укорачивает ломаную с обоих концов на заданные длины."""
    path = _trim_start(points, start)
    path = list(reversed(_trim_start(list(reversed(path)), end)))
    return path


def _trim_start(points: list, amount: float) -> list:
    if amount <= 0.5 or len(points) < 2:
        return list(points)
    remaining = amount
    out = list(points)
    while len(out) >= 2:
        a, b = out[0], out[1]
        seg = math.dist(a, b)
        if seg <= 1e-9:
            out.pop(0)
            continue
        if seg > remaining:
            t = remaining / seg
            out[0] = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            return out
        remaining -= seg
        out.pop(0)
    return out


def render_image(diagram: Diagram, style: StyleResolver,
                 theme: Theme) -> Image.Image:
    return Renderer(diagram, style, theme).render()
