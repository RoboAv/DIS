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
          theme: str | None = None) -> RenderResult:
    """Разбирает текст, раскладывает диаграмму и рисует PNG в память."""
    started = time.perf_counter()
    diagram, diagnostics = parse(text or "")
    if theme:
        diagram.options.setdefault("theme", theme)
    palette = get_theme(str(diagram.opt("theme", "light")))
    scale = max(0.2, float(scale) * float(diagram.opt("scale", 1) or 1))

    try:
        image = _render(diagram, palette, scale, max(1, int(supersample)))
    except Exception as exc:  # отрисовка не должна валить приложение
        return RenderResult(None, diagram, diagnostics,
                            time.perf_counter() - started,
                            f"{type(exc).__name__}: {exc}")
    return RenderResult(image, diagram, diagnostics,
                        time.perf_counter() - started)


def _render(diagram: Diagram, palette, scale: float, supersample: int
            ) -> Image.Image:
    for factor in _factors(supersample):
        style = StyleResolver(diagram, palette, scale * factor)
        layout_diagram(diagram, style)
        area = max(1.0, diagram.width) * max(1.0, diagram.height)
        if area > MAX_SUPERSAMPLED_PIXELS and factor > 1:
            continue
        image = render_image(diagram, style, palette)
        if factor > 1:
            target = (max(1, round(image.width / factor)),
                      max(1, round(image.height / factor)))
            image = image.resize(target, Image.LANCZOS)
        return image
    raise RuntimeError("не удалось подобрать масштаб отрисовки")


def _factors(supersample: int) -> list[int]:
    factors = [supersample]
    while factors[-1] > 1:
        factors.append(max(1, factors[-1] // 2))
    return factors


def render_to_file(text: str, path: str, scale: float = 1.0,
                   supersample: int = 2, dpi: int = 96) -> RenderResult:
    """Рисует диаграмму и сохраняет её в PNG."""
    result = build(text, scale=scale, supersample=supersample)
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
