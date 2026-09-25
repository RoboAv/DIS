"""Чистая геометрия: границы форм, пунктир, сглаживание ломаных."""

from __future__ import annotations

import math

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def center(box: Box) -> Point:
    x0, y0, x1, y1 = box
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def border_point(form: str, box: Box, toward: Point) -> Point:
    """Точка на границе формы на луче из центра в сторону `toward`."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = max(1e-6, (x1 - x0) / 2), max(1e-6, (y1 - y0) / 2)
    dx, dy = toward[0] - cx, toward[1] - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (cx, y1)

    if form in ("ellipse", "circle", "ring", "cloud"):
        k = math.hypot(dx / hw, dy / hh)
        s = 1.0 / k if k else 0.0
    elif form == "diamond":
        k = abs(dx) / hw + abs(dy) / hh
        s = 1.0 / k if k else 0.0
    elif form == "stadium":
        # прямоугольник со скруглением радиусом hh: приближаем прямоугольником
        s = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
        s *= 0.97
    else:
        s = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return (cx + dx * s, cy + dy * s)


def clip_to_box(form: str, box: Box, points: list[Point], at_start: bool) -> Point:
    """Обрезает ломаную по границе формы с нужного конца."""
    if not points:
        return center(box)
    if at_start:
        outside = next((p for p in points[1:] if not inside(box, p)), points[-1])
    else:
        outside = next((p for p in reversed(points[:-1]) if not inside(box, p)),
                       points[0])
    return border_point(form, box, outside)


def inside(box: Box, p: Point) -> bool:
    x0, y0, x1, y1 = box
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def boxes_overlap(a: Box, b: Box, gap: float = 0.0) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or
                a[3] + gap <= b[1] or b[3] + gap <= a[1])


def polyline_length(points: list[Point]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def point_at(points: list[Point], fraction: float) -> tuple[Point, Point]:
    """Точка на ломаной на заданной доле длины и направление в ней."""
    if len(points) < 2:
        return (points[0] if points else (0.0, 0.0)), (1.0, 0.0)
    total = polyline_length(points)
    target = max(0.0, min(1.0, fraction)) * total
    walked = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.dist(a, b)
        if seg <= 1e-9:
            continue
        if walked + seg >= target:
            t = (target - walked) / seg
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            d = ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
            return p, d
        walked += seg
    a, b = points[-2], points[-1]
    seg = max(1e-9, math.dist(a, b))
    return b, ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)


def longest_segment(points: list[Point]) -> tuple[Point, Point]:
    best, best_len = (points[0], points[-1]), -1.0
    for i in range(len(points) - 1):
        seg = math.dist(points[i], points[i + 1])
        if seg > best_len:
            best_len, best = seg, (points[i], points[i + 1])
    return best


def dash_pattern(points: list[Point], on: float, off: float) -> list[list[Point]]:
    """Разбивает ломаную на штрихи."""
    if on <= 0:
        return [points]
    out: list[list[Point]] = []
    remaining = on
    drawing = True
    current: list[Point] = [points[0]] if points else []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.dist(a, b)
        pos = 0.0
        while pos < seg - 1e-9:
            step = min(remaining, seg - pos)
            t0 = pos / seg
            t1 = (pos + step) / seg
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if drawing:
                if current and math.dist(current[-1], p0) > 0.5:
                    out.append(current)
                    current = [p0]
                elif not current:
                    current = [p0]
                current.append(p1)
            pos += step
            remaining -= step
            if remaining <= 1e-9:
                if drawing and current:
                    out.append(current)
                    current = []
                drawing = not drawing
                remaining = on if drawing else off
    if current and len(current) > 1:
        out.append(current)
    return [seg for seg in out if len(seg) > 1]


def round_corners(points: list[Point], radius: float) -> list[Point]:
    """Заменяет углы ломаной короткими скруглениями (набором точек)."""
    if len(points) < 3 or radius <= 0:
        return list(points)
    out: list[Point] = [points[0]]
    for i in range(1, len(points) - 1):
        prev, cur, nxt = points[i - 1], points[i], points[i + 1]
        d1 = math.dist(prev, cur)
        d2 = math.dist(cur, nxt)
        r = min(radius, d1 / 2, d2 / 2)
        if r < 1.0:
            out.append(cur)
            continue
        a = _towards(cur, prev, r)
        b = _towards(cur, nxt, r)
        out.append(a)
        steps = 4
        for s in range(1, steps):
            t = s / steps
            out.append(_quad(a, cur, b, t))
        out.append(b)
    out.append(points[-1])
    return _dedup(out)


def _towards(origin: Point, target: Point, distance: float) -> Point:
    d = math.dist(origin, target)
    if d < 1e-9:
        return origin
    t = distance / d
    return (origin[0] + (target[0] - origin[0]) * t,
            origin[1] + (target[1] - origin[1]) * t)


def _quad(a: Point, c: Point, b: Point, t: float) -> Point:
    u = 1 - t
    return (u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
            u * u * a[1] + 2 * u * t * c[1] + t * t * b[1])


def _dedup(points: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or math.dist(out[-1], p) > 0.4:
            out.append(p)
    if len(out) < 2 and points:
        return list(points)
    return out


def hexagon(box: Box, cut: float = 0.18) -> list[Point]:
    x0, y0, x1, y1 = box
    c = (x1 - x0) * cut
    return [(x0 + c, y0), (x1 - c, y0), (x1, (y0 + y1) / 2),
            (x1 - c, y1), (x0 + c, y1), (x0, (y0 + y1) / 2)]


def diamond(box: Box) -> list[Point]:
    x0, y0, x1, y1 = box
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [(mx, y0), (x1, my), (mx, y1), (x0, my)]


def folder(box: Box, tab_h: float, tab_w: float) -> list[Point]:
    x0, y0, x1, y1 = box
    return [(x0, y0), (x0 + tab_w, y0), (x0 + tab_w + tab_h * 0.6, y0 + tab_h),
            (x1, y0 + tab_h), (x1, y1), (x0, y1)]


def document(box: Box, wave: float) -> list[Point]:
    x0, y0, x1, y1 = box
    pts: list[Point] = [(x0, y0), (x1, y0), (x1, y1 - wave)]
    steps = 12
    for i in range(steps + 1):
        t = i / steps
        x = x1 + (x0 - x1) * t
        y = y1 - wave + math.sin(t * math.pi * 2) * wave * 0.9
        pts.append((x, y))
    pts.append((x0, y0))
    return pts


def normalize(v: Point) -> Point:
    d = math.hypot(*v)
    if d < 1e-9:
        return (1.0, 0.0)
    return (v[0] / d, v[1] / d)


def perpendicular(v: Point) -> Point:
    return (-v[1], v[0])
