"""Просмотр отрисованной диаграммы с масштабированием и панорамированием."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

ZOOM_STEPS = (0.15, 0.25, 0.35, 0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5,
              3.0, 4.0)

BACKDROPS = {"light": "#e7ebef", "dark": "#101418"}


class Preview(ttk.Frame):
    """Полотно с картинкой: колесо прокручивает, Ctrl+колесо масштабирует."""

    def __init__(self, master, on_zoom_change=None,
                 on_scale_request=None) -> None:
        super().__init__(master)
        self._on_zoom_change = on_zoom_change
        self._on_scale_request = on_scale_request
        self._image: Image.Image | None = None
        self._render_scale = 1.0
        self._photo: ImageTk.PhotoImage | None = None
        self.zoom = 1.0
        self._fit_mode = True
        self._drag_origin: tuple[int, int] | None = None

        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                bg=BACKDROPS["light"])
        self.vbar = ttk.Scrollbar(self, orient="vertical",
                                  command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal",
                                  command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set,
                              xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._hint = self.canvas.create_text(
            0, 0, text="Здесь появится диаграмма", fill="#8a9aa6",
            font=("Segoe UI", 12), anchor="center",
        )

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._wheel_horizontal)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-2>", self._press)
        self.canvas.bind("<B2-Motion>", self._drag)
        self.canvas.bind("<Double-Button-1>", lambda e: self.fit())

    # ---------------------------------------------------------------- api --

    def set_backdrop(self, palette: str) -> None:
        self.canvas.configure(bg=BACKDROPS.get(palette, BACKDROPS["light"]))

    def set_image(self, image: Image.Image, render_scale: float = 1.0) -> None:
        self._image = image
        self._render_scale = max(0.01, render_scale)
        if self._fit_mode:
            self._compute_fit()
        self._redraw()

    def clear(self) -> None:
        self._image = None
        self._photo = None
        self.canvas.delete("diagram")
        self.canvas.itemconfigure(self._hint, state="normal")
        self._center_hint()

    def fit(self) -> None:
        self._fit_mode = True
        self._compute_fit()
        self._redraw()
        self._notify()

    def set_zoom(self, value: float, request_render: bool = True) -> None:
        self._fit_mode = False
        self.zoom = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], value))
        self._redraw()
        self._notify()

    def zoom_in(self) -> None:
        self.set_zoom(self._next_step(1))

    def zoom_out(self) -> None:
        self.set_zoom(self._next_step(-1))

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    # ------------------------------------------------------------ рисование --

    def _next_step(self, direction: int) -> float:
        steps = list(ZOOM_STEPS)
        if direction > 0:
            for value in steps:
                if value > self.zoom + 1e-6:
                    return value
            return steps[-1]
        for value in reversed(steps):
            if value < self.zoom - 1e-6:
                return value
        return steps[0]

    def _compute_fit(self) -> None:
        if self._image is None:
            return
        width = max(1, self.canvas.winfo_width() - 24)
        height = max(1, self.canvas.winfo_height() - 24)
        base_w = self._image.width / self._render_scale
        base_h = self._image.height / self._render_scale
        if base_w <= 0 or base_h <= 0:
            return
        self.zoom = min(1.0, width / base_w, height / base_h)
        self.zoom = max(ZOOM_STEPS[0], self.zoom)

    def _redraw(self) -> None:
        self.canvas.delete("diagram")
        if self._image is None:
            self._center_hint()
            return
        self.canvas.itemconfigure(self._hint, state="hidden")
        factor = self.zoom / self._render_scale
        target = (max(1, round(self._image.width * factor)),
                  max(1, round(self._image.height * factor)))
        if abs(factor - 1.0) < 0.005:
            shown = self._image
        else:
            filt = Image.LANCZOS if factor < 1 else Image.BICUBIC
            shown = self._image.resize(target, filt)
        self._photo = ImageTk.PhotoImage(shown)

        margin = 12
        view_w = max(self.canvas.winfo_width(), shown.width + margin * 2)
        view_h = max(self.canvas.winfo_height(), shown.height + margin * 2)
        x = max(margin, (view_w - shown.width) / 2)
        y = max(margin, (view_h - shown.height) / 2)
        self.canvas.create_image(x, y, image=self._photo, anchor="nw",
                                 tags="diagram")
        self.canvas.configure(scrollregion=(0, 0, view_w, view_h))

    def _center_hint(self) -> None:
        self.canvas.coords(self._hint,
                           self.canvas.winfo_width() / 2,
                           self.canvas.winfo_height() / 2)

    def _notify(self) -> None:
        if self._on_zoom_change:
            self._on_zoom_change(self.zoom)

    # -------------------------------------------------------------- события --

    def _on_resize(self, event) -> None:
        if self._image is None:
            self._center_hint()
            return
        if self._fit_mode:
            self._compute_fit()
            self._notify()
        self._redraw()

    def _wheel(self, event) -> str:
        if event.state & 0x0004:
            self.set_zoom(self._next_step(1 if event.delta > 0 else -1))
            return "break"
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _wheel_horizontal(self, event) -> str:
        self.canvas.xview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _press(self, event) -> None:
        self._drag_origin = (event.x, event.y)
        self.canvas.configure(cursor="hand2")

    def _drag(self, event) -> None:
        if self._drag_origin is None:
            return
        dx = (event.x - self._drag_origin[0]) * 0.35
        dy = (event.y - self._drag_origin[1]) * 0.35
        self._drag_origin = (event.x, event.y)
        region = self.canvas.cget("scrollregion")
        if not region:
            return
        rx0, ry0, rx1, ry1 = (float(part) for part in str(region).split())
        width = max(1.0, rx1 - rx0)
        height = max(1.0, ry1 - ry0)
        x0 = self.canvas.xview()[0]
        y0 = self.canvas.yview()[0]
        self.canvas.xview_moveto(min(1.0, max(0.0, x0 - dx / width)))
        self.canvas.yview_moveto(min(1.0, max(0.0, y0 - dy / height)))

    def _release(self, event) -> None:
        self._drag_origin = None
        self.canvas.configure(cursor="")
