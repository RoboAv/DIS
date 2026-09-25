"""Окончания связей: стрелки, треугольники наследования, ромбы агрегации."""

from __future__ import annotations

import math

from PIL import ImageDraw

from .geometry import Point

Color = tuple[int, int, int, int]


def draw_decoration(draw: ImageDraw.ImageDraw, kind: str, tip: Point,
                    direction: Point, stroke: Color, background: Color,
                    width: float, scale: float = 1.0) -> float:
    """Рисует украшение на конце связи.

    `direction` — единичный вектор движения вдоль линии к точке `tip`.
    Возвращает длину, на которую нужно укоротить линию.
    """
    kind = (kind or "none").strip().lower().replace("-", "_")
    if kind in ("", "none"):
        return 0.0
    painter = _PAINTERS.get(kind)
    if painter is None:
        return 0.0
    line_w = max(1, int(round(width)))
    return painter(draw, tip, direction, stroke, background, line_w, scale)


def _back(tip: Point, direction: Point, distance: float) -> Point:
    return (tip[0] - direction[0] * distance, tip[1] - direction[1] * distance)


def _side(direction: Point) -> Point:
    return (-direction[1], direction[0])


def _wing(tip: Point, direction: Point, length: float, half: float
          ) -> tuple[Point, Point, Point]:
    base = _back(tip, direction, length)
    side = _side(direction)
    left = (base[0] + side[0] * half, base[1] + side[1] * half)
    right = (base[0] - side[0] * half, base[1] - side[1] * half)
    return base, left, right


def _arrow(draw, tip, direction, stroke, background, width, scale) -> float:
    length, half = 11.0 * scale, 5.2 * scale
    _, left, right = _wing(tip, direction, length, half)
    draw.line([left, tip], fill=stroke, width=width, joint="curve")
    draw.line([right, tip], fill=stroke, width=width, joint="curve")
    return 0.0


def _arrow_filled(draw, tip, direction, stroke, background, width, scale) -> float:
    length, half = 12.0 * scale, 5.0 * scale
    base, left, right = _wing(tip, direction, length, half)
    notch = _back(tip, direction, length * 0.72)
    draw.polygon([tip, left, notch, right], fill=stroke)
    return length * 0.68


def _triangle(draw, tip, direction, stroke, background, width, scale) -> float:
    length, half = 14.0 * scale, 8.0 * scale
    _, left, right = _wing(tip, direction, length, half)
    draw.polygon([tip, left, right], fill=background)
    draw.line([tip, left, right, tip], fill=stroke, width=width, joint="curve")
    return length


def _triangle_filled(draw, tip, direction, stroke, background, width, scale) -> float:
    length, half = 14.0 * scale, 7.5 * scale
    _, left, right = _wing(tip, direction, length, half)
    draw.polygon([tip, left, right], fill=stroke)
    return length


def _diamond_shape(draw, tip, direction, stroke, background, width, scale,
                   filled: bool) -> float:
    length, half = 16.0 * scale, 6.4 * scale
    middle = _back(tip, direction, length / 2)
    side = _side(direction)
    left = (middle[0] + side[0] * half, middle[1] + side[1] * half)
    right = (middle[0] - side[0] * half, middle[1] - side[1] * half)
    tail = _back(tip, direction, length)
    points = [tip, left, tail, right]
    draw.polygon(points, fill=stroke if filled else background)
    if not filled:
        draw.line(points + [tip], fill=stroke, width=width, joint="curve")
    return length


def _diamond(draw, tip, direction, stroke, background, width, scale) -> float:
    return _diamond_shape(draw, tip, direction, stroke, background, width,
                          scale, False)


def _diamond_filled(draw, tip, direction, stroke, background, width, scale) -> float:
    return _diamond_shape(draw, tip, direction, stroke, background, width,
                          scale, True)


def _circle_shape(draw, tip, direction, stroke, background, width, scale,
                  filled: bool) -> float:
    radius = 5.0 * scale
    center = _back(tip, direction, radius)
    box = (center[0] - radius, center[1] - radius,
           center[0] + radius, center[1] + radius)
    draw.ellipse(box, fill=stroke if filled else background,
                 outline=stroke, width=width)
    if not filled:
        side = _side(direction)
        draw.line([(center[0] - side[0] * radius, center[1] - side[1] * radius),
                   (center[0] + side[0] * radius, center[1] + side[1] * radius)],
                  fill=stroke, width=width)
        draw.line([_back(tip, direction, 2 * radius), tip],
                  fill=stroke, width=width)
    return 2 * radius


def _circle(draw, tip, direction, stroke, background, width, scale) -> float:
    return _circle_shape(draw, tip, direction, stroke, background, width,
                         scale, False)


def _circle_filled(draw, tip, direction, stroke, background, width, scale) -> float:
    return _circle_shape(draw, tip, direction, stroke, background, width,
                         scale, True)


def _cross(draw, tip, direction, stroke, background, width, scale) -> float:
    reach = 5.5 * scale
    center = _back(tip, direction, reach * 1.2)
    side = _side(direction)
    diag1 = ((direction[0] + side[0]) / math.sqrt(2),
             (direction[1] + side[1]) / math.sqrt(2))
    diag2 = ((direction[0] - side[0]) / math.sqrt(2),
             (direction[1] - side[1]) / math.sqrt(2))
    for vec in (diag1, diag2):
        draw.line([(center[0] - vec[0] * reach, center[1] - vec[1] * reach),
                   (center[0] + vec[0] * reach, center[1] + vec[1] * reach)],
                  fill=stroke, width=width)
    return reach * 2.2


def _bar(draw, tip, direction, stroke, background, width, scale) -> float:
    half = 7.0 * scale
    side = _side(direction)
    base = _back(tip, direction, 1.0 * scale)
    draw.line([(base[0] + side[0] * half, base[1] + side[1] * half),
               (base[0] - side[0] * half, base[1] - side[1] * half)],
              fill=stroke, width=max(width, int(round(2 * scale))))
    return 1.0 * scale


def _crowfoot(draw, tip, direction, stroke, background, width, scale) -> float:
    length, half = 12.0 * scale, 7.0 * scale
    base, left, right = _wing(tip, direction, length, half)
    for point in (left, right, base):
        draw.line([tip, point], fill=stroke, width=width, joint="curve")
    return 0.0


_PAINTERS = {
    "arrow": _arrow,
    "arrow_filled": _arrow_filled,
    "triangle": _triangle,
    "triangle_filled": _triangle_filled,
    "diamond": _diamond,
    "diamond_filled": _diamond_filled,
    "circle": _circle,
    "circle_filled": _circle_filled,
    "cross": _cross,
    "bar": _bar,
    "crowfoot": _crowfoot,
}

#: Список для интерфейса: человекочитаемые названия.
DECORATION_NAMES = {
    "none": "нет",
    "arrow": "стрелка",
    "arrow_filled": "закрашенная стрелка",
    "triangle": "полый треугольник (наследование)",
    "triangle_filled": "закрашенный треугольник",
    "diamond": "полый ромб (агрегация)",
    "diamond_filled": "закрашенный ромб (композиция)",
    "circle": "окружность",
    "circle_filled": "закрашенная точка",
    "cross": "крест",
    "bar": "черта",
    "crowfoot": "«гусиная лапка»",
}
