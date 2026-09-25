"""Рисование геометрических форм объектов."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import ImageDraw

from .geometry import Box, Point, dash_pattern

Color = tuple[int, int, int, int]


@dataclass
class ShapeStyle:
    fill: Color
    stroke: Color
    width: float
    dashed: bool = False
    radius: float = 6.0
    scale: float = 1.0


def draw_form(draw: ImageDraw.ImageDraw, form: str, box: Box,
              st: ShapeStyle) -> None:
    """Рисует форму объекта в заданном прямоугольнике."""
    painter = _PAINTERS.get(form, _rect)
    painter(draw, box, st)


def content_inset(form: str, box: Box, scale: float) -> Box:
    """Прямоугольник, в котором можно размещать текст."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if form == "node3d":
        d = _depth(w, h)
        return (x0 + 2, y0 + d, x1 - d, y1 - 2)
    if form == "folder":
        return (x0 + 2, y0 + _tab_h(h), x1 - 2, y1 - 2)
    if form == "component":
        return (x0 + _comp_tab(w) * 0.9, y0 + 2, x1 - 2, y1 - 2)
    if form == "actor":
        return (x0, y0 + 34 * scale, x1, y1)
    if form in ("dot", "ring"):
        return (x0, y0 + _marker(scale) + 6 * scale, x1, y1)
    if form == "document":
        return (x0 + 2, y0 + 2, x1 - 2, y1 - _wave(h))
    if form == "queue":
        return (x0 + _queue_r(w) * 1.1, y0, x1 - _queue_r(w) * 1.6, y1)
    if form == "cylinder":
        return (x0, y0 + _cyl_r(h) * 1.4, x1, y1 - _cyl_r(h) * 0.4)
    if form == "note":
        return (x0 + 2, y0 + 2, x1 - _fold(w, h) * 0.6, y1 - 2)
    return (x0, y0, x1, y1)


# ------------------------------------------------------------ помощники ----


def _depth(w: float, h: float) -> float:
    return max(6.0, min(w, h) * 0.16)


def _tab_h(h: float) -> float:
    return max(9.0, h * 0.16)


def _comp_tab(w: float) -> float:
    return max(10.0, w * 0.13)


def _queue_r(w: float) -> float:
    return max(6.0, w * 0.10)


def _cyl_r(h: float) -> float:
    return max(5.0, h * 0.13)


def _wave(h: float) -> float:
    return max(7.0, h * 0.13)


def _fold(w: float, h: float) -> float:
    return max(10.0, min(w, h) * 0.22)


def _marker(scale: float) -> float:
    """Диаметр маркера начального и конечного состояния."""
    return 22.0 * scale


def _stroke(draw: ImageDraw.ImageDraw, points: list[Point], st: ShapeStyle,
            close: bool = True) -> None:
    if st.width <= 0 or st.stroke[3] == 0:
        return
    path = list(points) + ([points[0]] if close and len(points) > 2 else [])
    width = max(1, int(round(st.width)))
    if st.dashed:
        on, off = 7 * st.scale, 5 * st.scale
        for chunk in dash_pattern(path, on, off):
            draw.line(chunk, fill=st.stroke, width=width, joint=None)
    else:
        draw.line(path, fill=st.stroke, width=width, joint="curve")


def _poly(draw: ImageDraw.ImageDraw, points: list[Point], st: ShapeStyle,
          fill: Color | None = None) -> None:
    paint = st.fill if fill is None else fill
    if len(points) > 2 and paint[3] > 0:
        draw.polygon(points, fill=paint)
    _stroke(draw, points, st)


def _ellipse_points(box: Box, steps: int = 72,
                    start: float = 0.0, end: float = 360.0) -> list[Point]:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    out: list[Point] = []
    span = end - start
    count = max(3, int(steps * abs(span) / 360.0))
    for i in range(count + 1):
        angle = math.radians(start + span * i / count)
        out.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    return out


def _round_rect_points(box: Box, radius: float) -> list[Point]:
    x0, y0, x1, y1 = box
    r = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1.0:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    out: list[Point] = []
    corners = (
        (x1 - r, y0 + r, -90.0),
        (x1 - r, y1 - r, 0.0),
        (x0 + r, y1 - r, 90.0),
        (x0 + r, y0 + r, 180.0),
    )
    for cx, cy, start in corners:
        for i in range(7):
            angle = math.radians(start + 90.0 * i / 6)
            out.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return out


# ------------------------------------------------------------- формы ------


def _rect(draw, box: Box, st: ShapeStyle) -> None:
    _poly(draw, _round_rect_points(box, st.radius), st)


def _roundrect(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    radius = min((y1 - y0) * 0.32, (x1 - x0) * 0.32, 22 * st.scale)
    _poly(draw, _round_rect_points(box, radius), st)


def _stadium(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    _poly(draw, _round_rect_points(box, (y1 - y0) / 2), st)


def _ellipse(draw, box: Box, st: ShapeStyle) -> None:
    _poly(draw, _ellipse_points(box), st)


def _circle(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    size = min(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    square = (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    _poly(draw, _ellipse_points(square), st)


def _marker_box(box: Box, scale: float) -> Box:
    x0, y0, x1, y1 = box
    size = min(_marker(scale), x1 - x0)
    cx = (x0 + x1) / 2
    top = y0 + 2 * scale
    return (cx - size / 2, top, cx + size / 2, top + size)


def _dot(draw, box: Box, st: ShapeStyle) -> None:
    """Начальное состояние: закрашенный кружок, подпись под ним."""
    draw.polygon(_ellipse_points(_marker_box(box, st.scale)), fill=st.stroke)


def _ring(draw, box: Box, st: ShapeStyle) -> None:
    """Конечное состояние: кольцо с закрашенным центром."""
    outer = _marker_box(box, st.scale)
    _poly(draw, _ellipse_points(outer), st)
    inset = (outer[2] - outer[0]) * 0.27
    inner = (outer[0] + inset, outer[1] + inset,
             outer[2] - inset, outer[3] - inset)
    draw.polygon(_ellipse_points(inner), fill=st.stroke)


def _hexagon(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    cut = (x1 - x0) * 0.16
    mid = (y0 + y1) / 2
    _poly(draw, [(x0 + cut, y0), (x1 - cut, y0), (x1, mid),
                 (x1 - cut, y1), (x0 + cut, y1), (x0, mid)], st)


def _diamond(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    _poly(draw, [(mx, y0), (x1, my), (mx, y1), (x0, my)], st)


def _cloud(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    points: list[Point] = []
    for i in range(120):
        angle = 2 * math.pi * i / 120
        bump = 1.0 + 0.11 * math.cos(6 * angle) + 0.05 * math.sin(3 * angle)
        points.append((cx + rx * bump * 0.92 * math.cos(angle),
                       cy + ry * bump * 0.90 * math.sin(angle)))
    _poly(draw, points, st)


def _note(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    fold = _fold(x1 - x0, y1 - y0)
    _poly(draw, [(x0, y0), (x1 - fold, y0), (x1, y0 + fold),
                 (x1, y1), (x0, y1)], st)
    _stroke(draw, [(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)],
            st, close=False)


def _folder(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    tab = _tab_h(y1 - y0)
    width = min((x1 - x0) * 0.42, 90 * st.scale)
    _poly(draw, [(x0, y0), (x0 + width, y0), (x0 + width + tab * 0.55, y0 + tab),
                 (x1, y0 + tab), (x1, y1), (x0, y1)], st)


def _component(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    _poly(draw, _round_rect_points(box, st.radius * 0.6), st)
    tab_w = _comp_tab(x1 - x0)
    tab_h = max(6.0, (y1 - y0) * 0.14)
    for factor in (0.26, 0.58):
        ty = y0 + (y1 - y0) * factor
        tab = (x0 - tab_w * 0.45, ty, x0 + tab_w * 0.55, ty + tab_h)
        draw.rectangle(tab, fill=st.fill)
        _stroke(draw, [(tab[0], tab[1]), (tab[2], tab[1]),
                       (tab[2], tab[3]), (tab[0], tab[3])], st)


def _node3d(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    d = _depth(x1 - x0, y1 - y0)
    front = [(x0, y0 + d), (x1 - d, y0 + d), (x1 - d, y1), (x0, y1)]
    top = [(x0, y0 + d), (x0 + d, y0), (x1, y0), (x1 - d, y0 + d)]
    side = [(x1 - d, y0 + d), (x1, y0), (x1, y1 - d), (x1 - d, y1)]
    _poly(draw, top, st)
    _poly(draw, side, st)
    _poly(draw, front, st)


def _cylinder(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    r = _cyl_r(y1 - y0)
    top = (x0, y0, x1, y0 + 2 * r)
    bottom = (x0, y1 - 2 * r, x1, y1)
    outline = _ellipse_points(top, start=180.0, end=360.0)
    outline += _ellipse_points(bottom, start=0.0, end=180.0)
    _poly(draw, outline, st)
    _stroke(draw, _ellipse_points(top, start=0.0, end=180.0), st, close=False)


def _queue(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    r = _queue_r(x1 - x0)
    left = (x0, y0, x0 + 2 * r, y1)
    right = (x1 - 2 * r, y0, x1, y1)
    outline = _ellipse_points(left, start=90.0, end=270.0)
    outline += _ellipse_points(right, start=-90.0, end=90.0)
    _poly(draw, outline, st)
    _stroke(draw, _ellipse_points(right, start=90.0, end=270.0), st, close=False)


def _document(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    wave = _wave(y1 - y0)
    points: list[Point] = [(x0, y0), (x1, y0), (x1, y1 - wave)]
    steps = 16
    for i in range(steps + 1):
        t = i / steps
        points.append((x1 + (x0 - x1) * t,
                       y1 - wave + math.sin(t * math.pi * 2) * wave * 0.85))
    _poly(draw, points, st)


def _actor(draw, box: Box, st: ShapeStyle) -> None:
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    unit = 34 * st.scale
    head_r = unit * 0.24
    head_cy = y0 + head_r + unit * 0.06
    _poly(draw, _ellipse_points((cx - head_r, head_cy - head_r,
                                 cx + head_r, head_cy + head_r)), st)
    body_top = head_cy + head_r
    body_bottom = y0 + unit * 0.78
    _stroke(draw, [(cx, body_top), (cx, body_bottom)], st, close=False)
    arm_y = body_top + (body_bottom - body_top) * 0.32
    _stroke(draw, [(cx - unit * 0.32, arm_y + unit * 0.10),
                   (cx + unit * 0.32, arm_y + unit * 0.10)], st, close=False)
    _stroke(draw, [(cx - unit * 0.26, y0 + unit * 0.98), (cx, body_bottom),
                   (cx + unit * 0.26, y0 + unit * 0.98)], st, close=False)


_PAINTERS = {
    "rect": _rect,
    "roundrect": _roundrect,
    "stadium": _stadium,
    "ellipse": _ellipse,
    "circle": _circle,
    "dot": _dot,
    "ring": _ring,
    "hexagon": _hexagon,
    "diamond": _diamond,
    "cloud": _cloud,
    "note": _note,
    "folder": _folder,
    "component": _component,
    "node3d": _node3d,
    "cylinder": _cylinder,
    "queue": _queue,
    "document": _document,
    "actor": _actor,
}
