"""UML Studio — редактор UML-диаграмм с отрисовкой в PNG.

Текст описания диаграммы разбирается своим парсером (синтаксис близок к
PlantUML), раскладывается собственным послойным алгоритмом и рисуется
средствами Pillow. Внешние движки и Java не нужны.
"""

from .api import build, parse_only, render_to_file
from .errors import Diagnostic, DiagramError
from .model import Diagram

__all__ = [
    "build",
    "render_to_file",
    "parse_only",
    "Diagram",
    "Diagnostic",
    "DiagramError",
    "__version__",
]

__version__ = "1.0.0"
