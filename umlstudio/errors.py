"""Диагностика разбора текста диаграммы."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    """Сообщение об ошибке или предупреждении с привязкой к строке."""

    line: int
    message: str
    severity: str = "error"   # error | warning
    text: str = ""

    def __str__(self) -> str:
        mark = "ошибка" if self.severity == "error" else "предупреждение"
        where = f"строка {self.line}" if self.line else "источник"
        return f"{where}: {mark}: {self.message}"


class DiagramError(Exception):
    """Фатальная ошибка: диаграмму отрисовать невозможно."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(message)
        self.line = line
        self.message = message
