"""Публичный интерфейс: текст -> изображение."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PIL import Image

from .errors import Diagnostic
from .layout import layout_diagram
from .model import Diagram
from .parser import parse
from .renderer import render_image
from .style import StyleResolver
from .theme import get_theme

#: Выше этого числа пикселей сглаживание отключается, чтобы не съесть память.
MAX_SUPERSAMPLED_PIXELS = 42_000_000


@dataclass
class RenderResult:
    """Результат одной отрисовки."""

    image: Image.Image | None = None
    diagram: Diagram | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.image is not None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size if self.image else (0, 0)


def build(text: str, scale: float = 1.0, supersample: int = 2,
          theme: str | None = None, honor_manual: bool = True,
          output_scale: float = 1.0) -> RenderResult:
    """Разбирает текст, раскладывает диаграмму и рисует PNG в память.

    ``scale`` — масштаб раскладки. ``output_scale`` увеличивает картинку,
    не меняя взаимное положение объектов. ``supersample`` только сглаживает.
    """
    started = time.perf_counter()
    diagram, diagnostics = parse(text or "")
    if theme:
        diagram.options.setdefault("theme", theme)
    palette = get_theme(str(diagram.opt("theme", "light")))
    scale = max(0.2, float(scale) * float(diagram.opt("scale", 1) or 1))

    try:
        image = _render(diagram, palette, scale, max(1, int(supersample)),
                        honor_manual, output_scale=output_scale)
    except Exception as exc:  # отрисовка не должна валить приложение
        return RenderResult(None, diagram, diagnostics,
                            time.perf_counter() - started,
                            f"{type(exc).__name__}: {exc}")
    return RenderResult(image, diagram, diagnostics,
                        time.perf_counter() - started)


def _render(diagram: Diagram, palette, scale: float, supersample: int,
            honor_manual: bool = True, output_scale: float = 1.0) -> Image.Image:
    """Раскладывает один раз и рисует эту же карту, при необходимости крупнее."""
    style = StyleResolver(diagram, palette, scale)
    layout_diagram(diagram, style, honor_manual=honor_manual)
    smooth = max(1, int(supersample))
    pixels = max(1.0, float(output_scale))
    draw_factor = pixels * smooth
    area = max(1.0, diagram.width) * max(1.0, diagram.height) * draw_factor * draw_factor
    if area > MAX_SUPERSAMPLED_PIXELS and smooth > 1:
        smooth = 1
        draw_factor = pixels
    if abs(draw_factor - 1.0) < 1e-6:
        return render_image(diagram, style, palette)
    _scale_geometry(diagram, draw_factor)
    try:
        drawn = StyleResolver(diagram, palette, scale * draw_factor)
        image = render_image(diagram, drawn, palette)
    finally:
        _scale_geometry(diagram, 1.0 / draw_factor)
    if smooth > 1:
        target = (max(1, round(image.width / smooth)),
                  max(1, round(image.height / smooth)))
        image = image.resize(target, Image.LANCZOS)
    return image


def _scale_geometry(diagram: Diagram, factor: float) -> None:
    """Умножает уже посчитанные координаты. Повтор с ``1/factor`` возвращает их."""
    diagram.width *= factor
    diagram.height *= factor
    for node in diagram.nodes.values():
        node.x *= factor
        node.y *= factor
        node.w *= factor
        node.h *= factor
        for row in node.rows:
            for key in ("w", "h", "marker", "gap"):
                if isinstance(row.get(key), (int, float)):
                    row[key] *= factor
        for key, value in list(node.metrics.items()):
            if isinstance(value, (int, float)):
                node.metrics[key] = value * factor
    for group in diagram.groups.values():
        group.x *= factor
        group.y *= factor
        group.w *= factor
        group.h *= factor
        group.header_h *= factor
    for edge in diagram.edges:
        edge.points = [(px * factor, py * factor) for px, py in edge.points]
        if edge.label_pos:
            edge.label_pos = (edge.label_pos[0] * factor, edge.label_pos[1] * factor)
        if edge.label_anchor:
            edge.label_anchor = (edge.label_anchor[0] * factor,
                                 edge.label_anchor[1] * factor)
    metrics = diagram.metrics
    for key in ("padding", "corner"):
        if isinstance(metrics.get(key), (int, float)):
            metrics[key] *= factor
    reserve = metrics.get("reserve")
    if isinstance(reserve, dict):
        for key, value in list(reserve.items()):
            if isinstance(value, (int, float)):
                reserve[key] = value * factor


def layout_only(text: str, theme: str | None = None,
                honor_manual: bool = True) -> RenderResult:
    """Разбирает текст и раскладывает диаграмму без картинки."""
    started = time.perf_counter()
    diagram, diagnostics = parse(text or "")
    if theme:
        diagram.options.setdefault("theme", theme)
    palette = get_theme(str(diagram.opt("theme", "light")))
    scale = max(0.2, float(diagram.opt("scale", 1) or 1))
    try:
        style = StyleResolver(diagram, palette, scale)
        layout_diagram(diagram, style, honor_manual=honor_manual)
    except Exception as exc:
        return RenderResult(None, diagram, diagnostics,
                            time.perf_counter() - started,
                            f"{type(exc).__name__}: {exc}")
    return RenderResult(None, diagram, diagnostics, time.perf_counter() - started)


def render_to_file(text: str, path: str, scale: float = 1.0,
                   supersample: int = 2, dpi: int = 96,
                   honor_manual: bool = True,
                   output_scale: float = 1.0) -> RenderResult:
    """Рисует диаграмму и сохраняет её в PNG."""
    result = build(text, scale=scale, supersample=supersample,
                   honor_manual=honor_manual, output_scale=output_scale)
    if result.image is None:
        return result
    image = result.image
    if not (result.diagram and result.diagram.opt("transparent")):
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.split()[3])
        image = flat
    image.save(path, format="PNG", dpi=(dpi, dpi), optimize=True)
    return result


def parse_only(text: str) -> tuple[Diagram, list[Diagnostic]]:
    return parse(text or "")
