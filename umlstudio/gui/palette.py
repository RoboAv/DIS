"""Цвета оформления самого окна: фон, поля, рамки, выделение."""

from __future__ import annotations

import tkinter as tk

UI: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f3f5f7",          # фон панелей
        "fg": "#1f2a33",          # основной текст
        "field": "#ffffff",       # фон полей ввода и списков
        "muted": "#8a9aa6",       # подписи и пояснения
        "border": "#c6d0d8",      # рамки и разделители
        "focus": "#1565c0",       # обводка активного элемента
        "accent": "#1565c0",      # фон выделенной строки
        "accent_fg": "#ffffff",   # текст на выделении
        "trough": "#e4e9ee",      # дорожка полосы прокрутки
        "button": "#e7ebef",
        "button_active": "#dfe6ec",
        "button_pressed": "#d3dbe2",
        "canvas": "#eef1f4",      # подложка предпросмотра
    },
    "dark": {
        "bg": "#232a31",
        "fg": "#e6edf3",
        "field": "#1b2127",
        "muted": "#8b9aa7",
        "border": "#3a4650",
        "focus": "#6fb3f2",
        "accent": "#2f6fb5",
        "accent_fg": "#ffffff",
        "trough": "#1a2027",
        "button": "#2f3943",
        "button_active": "#3a4854",
        "button_pressed": "#262f38",
        "canvas": "#171c21",
    },
}


def colors(name: str) -> dict[str, str]:
    """Набор цветов по имени оформления; неизвестное имя — светлое."""
    return UI.get(name, UI["light"])


def find(root: tk.Misc, klass: str) -> list[tk.Misc]:
    """Все вложенные элементы указанного класса."""
    found: list[tk.Misc] = []
    for child in root.winfo_children():
        if child.winfo_class() == klass:
            found.append(child)
        found.extend(find(child, klass))
    return found


def paint_text(widget: tk.Text, c: dict[str, str]) -> None:
    """Цвета текстового поля: фон, курсор, выделение и обводка фокуса."""
    widget.configure(background=c["field"], foreground=c["fg"],
                     insertbackground=c["fg"],
                     selectbackground=c["accent"],
                     selectforeground=c["accent_fg"],
                     relief="flat", borderwidth=0, highlightthickness=1,
                     highlightbackground=c["border"],
                     highlightcolor=c["focus"])


def paint_popdowns(root: tk.Misc, c: dict[str, str]) -> None:
    """Раскрывающийся список — отдельное окно Tk со своим списком."""
    for combo in find(root, "TCombobox"):
        try:
            root.tk.call("ttk::combobox::PopdownWindow", str(combo))
            root.tk.call(f"{combo}.popdown.f.l", "configure",
                         "-background", c["field"], "-foreground", c["fg"],
                         "-selectbackground", c["accent"],
                         "-selectforeground", c["accent_fg"])
        except tk.TclError:
            continue
