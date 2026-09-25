"""Всплывающие подсказки для кнопок и других элементов управления."""

from __future__ import annotations

import tkinter as tk

PALETTES = {
    "light": {"bg": "#2f3b44", "fg": "#f4f7f9", "border": "#1b242b"},
    "dark": {"bg": "#3a464f", "fg": "#eef3f7", "border": "#12181d"},
}

MARGIN = 6

_current = "light"


def set_palette(name: str) -> None:
    """Задаёт оформление подсказок для всего приложения."""
    global _current
    _current = name if name in PALETTES else "light"


class Tooltip:
    """Подсказка, всплывающая при наведении на элемент."""

    def __init__(self, widget: tk.Misc, text: str, delay: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._timer: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")
        widget.bind("<Destroy>", self._cancel, add="+")

    # ---------------------------------------------------------------- показ --

    def _schedule(self, event=None) -> None:
        self._cancel()
        if self.text:
            self._timer = self.widget.after(self.delay, self._show)

    def _cancel(self, event=None) -> None:
        if self._timer:
            try:
                self.widget.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        self._hide()

    def _show(self) -> None:
        self._timer = None
        if self._window is not None or not self.text:
            return
        colors = PALETTES[_current]
        try:
            left = self.widget.winfo_rootx()
            top = self.widget.winfo_rooty()
            height = self.widget.winfo_height()
        except tk.TclError:
            return
        window = tk.Toplevel(self.widget)
        window.withdraw()
        window.wm_overrideredirect(True)
        window.configure(background=colors["border"])
        try:
            window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(window, text=self.text, background=colors["bg"],
                 foreground=colors["fg"], justify="left", padx=8, pady=5,
                 font=("Segoe UI", 9), wraplength=340).pack(padx=1, pady=1)
        window.update_idletasks()
        x, y = self._place(window, left, top, height)
        window.wm_geometry(f"+{x}+{y}")
        window.deiconify()
        self._window = window

    def _place(self, window: tk.Toplevel, left: int, top: int,
               height: int) -> tuple[int, int]:
        """Держит подсказку в пределах экрана: у края разворачивает её."""
        width = window.winfo_reqwidth()
        tall = window.winfo_reqheight()
        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()
        x = min(left + 12, max(MARGIN, screen_w - width - MARGIN))
        y = top + height + 6
        if y + tall > screen_h - MARGIN:
            y = max(MARGIN, top - tall - 6)
        return x, y

    def _hide(self) -> None:
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None

    def update_text(self, text: str) -> None:
        self.text = text
        self._hide()


def attach(widget: tk.Misc, text: str) -> Tooltip:
    """Короткая форма: привязывает подсказку к элементу."""
    return Tooltip(widget, text)
