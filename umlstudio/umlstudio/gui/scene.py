"""Интерактивная область: блоки и связи — отдельные объекты холста."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..model import Diagram, Edge, Group, Node
from ..style import StyleResolver
from ..theme import get_theme, to_hex
from .preview import BACKDROPS, ZOOM_STEPS

def _segment_distance(start: tuple[float, float], end: tuple[float, float],
                      point: tuple[float, float]) -> float:
    ax, ay = start
    bx, by = end
    px, py = point
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length < 1e-9:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    share = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    qx, qy = ax + share * dx, ay + share * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


HINT = (
    "Интерактивная область\n"
    "Перетащите блок или узел связи\n"
    "Двойной щелчок по линии добавляет узел\n"
    "Правый щелчок блокирует объект"
)


class InteractiveCanvas(ttk.Frame):
    """Холст диаграммы: перетаскивание блоков и узлов связей."""

    def __init__(self, master, on_node_moved=None, on_edge_moved=None,
                 on_edge_cleared=None, on_node_lock=None, on_edge_lock=None,
                 on_zoom_change=None) -> None:
        super().__init__(master)
        self._on_node_moved = on_node_moved
        self._on_edge_moved = on_edge_moved
        self._on_edge_cleared = on_edge_cleared
        self._on_node_lock = on_node_lock
        self._on_edge_lock = on_edge_lock
        self._on_zoom_change = on_zoom_change

        self.zoom = 1.0
        self._fit_mode = True
        self._diagram: Diagram | None = None
        self._style: StyleResolver | None = None
        self._ox = 16.0
        self._oy = 16.0
        self._dragging = False
        self._drag: dict | None = None
        self._edge_line: dict[int, int] = {}
        self._group_names: list[str] = []
        self._palette = "light"
        self._pending: tuple | None = None

        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                bg=BACKDROPS["light"])
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set,
                              xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._hint = self.canvas.create_text(
            0, 0, text=HINT, fill="#8a9aa6", font=("Segoe UI", 12),
            anchor="center", justify="center", tags="hint",
        )
        self._menu = tk.Menu(self, tearoff=0)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._wheel_horizontal)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._double)
        self.canvas.bind("<ButtonPress-3>", self._popup)
        self.canvas.bind("<ButtonPress-2>", self._press_pan)
        self.canvas.bind("<B2-Motion>", self._pan_motion)

    def set_backdrop(self, palette: str) -> None:
        self._palette = palette
        self.canvas.configure(bg=BACKDROPS.get(palette, BACKDROPS["light"]))

    def show(self, diagram: Diagram | None, error: str = "") -> None:
        if self._dragging:
            self._pending = (diagram, error)
            return
        self._paint(diagram, error)

    def fit(self) -> None:
        self._fit_mode = True
        self._compute_fit()
        self._paint(self._diagram, "")
        self._notify()

    def set_zoom(self, value: float) -> None:
        self._fit_mode = False
        self.zoom = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], value))
        self._paint(self._diagram, "")
        self._notify()

    def zoom_in(self) -> None:
        self.set_zoom(self._step(1))

    def zoom_out(self) -> None:
        self.set_zoom(self._step(-1))

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def _paint(self, diagram: Diagram | None, error: str) -> None:
        x_pos = self.canvas.xview()[0] if self._diagram is not None else 0.0
        y_pos = self.canvas.yview()[0] if self._diagram is not None else 0.0
        self._diagram = diagram
        self._style = None
        self._edge_line.clear()
        self._group_names = []
        self.canvas.delete("item")
        empty = diagram is None or not (diagram.nodes or diagram.groups)
        if error or empty:
            self.canvas.itemconfigure(self._hint, state="normal",
                                      text=error or HINT)
            self._center_hint()
            return
        self.canvas.itemconfigure(self._hint, state="hidden")
        theme_name = str(diagram.opt("theme", "light"))
        palette = get_theme(theme_name)
        self._style = StyleResolver(diagram, palette, 1.0)
        if self._fit_mode:
            self._compute_fit()
        self._draw(diagram, palette)
        if not self._fit_mode:
            self.canvas.xview_moveto(x_pos)
            self.canvas.yview_moveto(y_pos)

    def _draw(self, diagram: Diagram, palette) -> None:
        scale = self.zoom
        width = max(1.0, diagram.width) * scale
        height = max(1.0, diagram.height) * scale
        view_w = max(self.canvas.winfo_width(), width + self._ox * 2)
        view_h = max(self.canvas.winfo_height(), height + self._oy * 2)
        paper = diagram.opt("bg", palette.bg)
        self.canvas.create_rectangle(
            self._ox, self._oy, self._ox + width, self._oy + height,
            fill=to_hex(paper), outline="", tags=("item", "paper"),
        )
        if diagram.title:
            self.canvas.create_text(
                self._ox + width / 2, self._oy + 10 * scale,
                text=diagram.title, anchor="n",
                fill=to_hex(palette.ink),
                font=("Segoe UI", max(8, int(round(15 * scale))), "bold"),
                tags=("item",),
            )
        for index, group in enumerate(self._groups_back_to_front(diagram)):
            self._group_names.append(group.name)
            self._draw_group(index, group)
        for index, edge in enumerate(diagram.edges):
            self._draw_edge(index, edge)
        for index, node in enumerate(diagram.nodes.values()):
            self._draw_node(index, node)
        for index, edge in enumerate(diagram.edges):
            self._draw_handles(index, edge)
        self.canvas.configure(scrollregion=(0, 0, view_w, view_h))
        self.canvas.tag_raise("hint")

    def _groups_back_to_front(self, diagram: Diagram) -> list[Group]:
        def depth(group: Group) -> int:
            return len(diagram.group_path(group.name))

        return sorted(diagram.groups.values(), key=depth)

    def _draw_group(self, index: int, group: Group) -> None:
        assert self._style is not None
        st = self._style.group_style(group)
        tag = f"g:{index}"
        x0, y0, x1, y1 = self._box(group.x, group.y, group.w, group.h)
        self.canvas.create_rectangle(
            x0, y0, x1, y1, fill=to_hex(st["fill"]), outline=to_hex(st["stroke"]),
            width=1, tags=("item", tag, "group"),
        )
        self.canvas.create_text(
            x0 + 8, y0 + 6, text=group.title, anchor="nw",
            fill=to_hex(st["text"]), font=("Segoe UI", max(8, int(11 * self.zoom)), "bold"),
            tags=("item", tag, "group"),
        )

    def _draw_node(self, index: int, node: Node) -> None:
        assert self._style is not None
        st = self._style.node_style(node)
        tag = f"n:{index}"
        x0, y0, x1, y1 = self._box(node.x, node.y, node.w, node.h)
        self._shape(st["form"], x0, y0, x1, y1, to_hex(st["fill"]),
                    to_hex(st["stroke"]), float(st["stroke_width"]) * self.zoom,
                    bool(st["dashed"]), tag)
        self._draw_rows(node, x0, y0, x1, y1, tag, to_hex(st["stroke"]))
        if node.locked:
            self.canvas.create_oval(
                x1 - 11, y0 + 3, x1 - 3, y0 + 11, fill="#c62828", outline="",
                tags=("item", tag, "node"),
            )

    def _draw_rows(self, node: Node, x0: float, y0: float, x1: float, y1: float,
                   tag: str, stroke: str) -> None:
        metrics = node.metrics or {}
        pad_x = metrics.get("pad_x", 14) * self.zoom
        gap = metrics.get("row_gap", 2) * self.zoom
        content_h = metrics.get("content_h", 0.0) * self.zoom
        inner_h = max(0.0, (y1 - y0) - content_h)
        y = y0 + inner_h / 2
        left = x0 + pad_x
        right = x1 - pad_x
        for row in node.rows:
            height = row["h"] * self.zoom
            if row.get("type") == "sep":
                mid = y + height / 2
                self.canvas.create_line(
                    left, mid, right, mid, fill=stroke, tags=("item", tag, "node"),
                )
                y += height + gap
                continue
            text = row.get("text") or ""
            if row.get("vis"):
                text = f"{row['vis']} {text}"
            size = max(7, int(round(row.get("size", 12) * self.zoom)))
            styles = []
            if row.get("bold"):
                styles.append("bold")
            if row.get("italic"):
                styles.append("italic")
            if row.get("underline"):
                styles.append("underline")
            font = ("Segoe UI", size, " ".join(styles)) if styles else ("Segoe UI", size)
            center = row.get("align") == "center"
            self.canvas.create_text(
                (left + right) / 2 if center else left, y,
                text=text, anchor="n" if center else "nw",
                fill=to_hex(row.get("color") or "#18222a"), font=font,
                tags=("item", tag, "node"),
            )
            y += height + gap

    def _shape(self, form: str, x0: float, y0: float, x1: float, y1: float,
               fill: str, outline: str, width: float, dashed: bool, tag: str) -> None:
        kw = {"fill": fill, "outline": outline, "width": max(1, round(width)),
              "tags": ("item", tag, "node")}
        if dashed:
            kw["dash"] = (5, 3)
        if form in ("ellipse", "circle", "ring", "cloud"):
            self.canvas.create_oval(x0, y0, x1, y1, **kw)
            return
        if form == "diamond":
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self.canvas.create_polygon(cx, y0, x1, cy, cx, y1, x0, cy, **kw)
            return
        if form == "hexagon":
            cut = (x1 - x0) * 0.18
            cy = (y0 + y1) / 2
            self.canvas.create_polygon(
                x0 + cut, y0, x1 - cut, y0, x1, cy, x1 - cut, y1, x0 + cut, y1, x0, cy,
                **kw)
            return
        self.canvas.create_rectangle(x0, y0, x1, y1, **kw)

    def _draw_edge(self, index: int, edge: Edge) -> None:
        assert self._style is not None and self._diagram is not None
        st = self._style.edge_style(edge)
        if st["hidden"] or len(edge.points) < 2:
            return
        flat: list[float] = []
        for px, py in edge.points:
            cx, cy = self._to_canvas(px, py)
            flat.extend((cx, cy))
        color = to_hex(st["color"])
        width = max(1.4, float(st["width"])) * max(0.8, self.zoom)
        dash = None
        if st["line"] == "dashed":
            dash = (8, 5)
        elif st["line"] == "dotted":
            dash = (2, 3)
        arrow = "last" if any(word in st["head"] for word in ("arrow", "triangle")) else "none"
        tags = ("item", f"e:{index}", "edge")
        line = self.canvas.create_line(
            *flat, fill=color, width=max(3, round(width)),
            arrow=arrow, arrowshape=(10 * self.zoom, 12 * self.zoom, 4 * self.zoom),
            capstyle="round", joinstyle="round", dash=dash, tags=tags,
        )
        self._edge_line[index] = line
        if edge.label and edge.label_pos:
            lx, ly = self._to_canvas(*edge.label_pos)
            self.canvas.create_text(
                lx, ly, text=edge.label, fill=to_hex(st["label_color"]),
                font=("Segoe UI", max(7, int(11 * self.zoom))), tags=tags,
            )
        self._multiplicity(edge, flat, st)

    def _multiplicity(self, edge: Edge, flat: list[float], st: dict) -> None:
        pairs = ((edge.a_mult, 0), (edge.b_mult, len(flat) - 4))
        for text, start in pairs:
            if not text or start < 0 or start + 3 >= len(flat):
                continue
            x0, y0, x1, y1 = flat[start:start + 4]
            self.canvas.create_text(
                (x0 + x1) / 2, (y0 + y1) / 2 - 8,
                text=text, fill=to_hex(st["mult_color"]),
                font=("Segoe UI", max(7, int(10 * self.zoom))),
                tags=("item", "edge"),
            )

    def _draw_handles(self, index: int, edge: Edge) -> None:
        if len(edge.points) < 3:
            return
        color = "#c62828" if edge.locked else "#1565c0"
        for point_index, (px, py) in enumerate(edge.points[1:-1], start=1):
            cx, cy = self._to_canvas(px, py)
            radius = max(4, 5 * self.zoom)
            self.canvas.create_oval(
                cx - radius, cy - radius, cx + radius, cy + radius,
                fill=color, outline="#ffffff", width=1,
                tags=("item", f"h:{index}:{point_index}", "handle"),
            )

    def _box(self, x: float, y: float, w: float, h: float
             ) -> tuple[float, float, float, float]:
        x0, y0 = self._to_canvas(x, y)
        return x0, y0, x0 + w * self.zoom, y0 + h * self.zoom

    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return x * self.zoom + self._ox, y * self.zoom + self._oy

    def _to_diagram(self, x: float, y: float) -> tuple[float, float]:
        scale = self._layout_scale()
        return (x - self._ox) / self.zoom / scale, (y - self._oy) / self.zoom / scale

    def _layout_scale(self) -> float:
        if self._diagram is None:
            return 1.0
        return float(self._diagram.metrics.get("scale", 1) or 1)

    def _unscaled(self, x: float, y: float) -> tuple[float, float]:
        scale = self._layout_scale()
        return x / scale, y / scale

    def _notify(self) -> None:
        if self._on_zoom_change:
            self._on_zoom_change(self.zoom)

    def _step(self, direction: int) -> float:
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
        if self._diagram is None:
            return
        width = max(1, self.canvas.winfo_width() - 32)
        height = max(1, self.canvas.winfo_height() - 32)
        base_w = max(1.0, self._diagram.width)
        base_h = max(1.0, self._diagram.height)
        self.zoom = min(1.0, width / base_w, height / base_h)
        self.zoom = max(ZOOM_STEPS[0], self.zoom)

    def _center_hint(self) -> None:
        self.canvas.coords(self._hint, self.canvas.winfo_width() / 2,
                           self.canvas.winfo_height() / 2)

    def _on_resize(self, event) -> None:
        if self._diagram is None:
            self._center_hint()
            return
        if self._fit_mode:
            self._compute_fit()
            self._notify()
        self._paint(self._diagram, "")

    def _wheel(self, event) -> str:
        if event.state & 0x0004:
            self.set_zoom(self._step(1 if event.delta > 0 else -1))
            return "break"
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _wheel_horizontal(self, event) -> str:
        self.canvas.xview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _tags(self, event) -> tuple[str, ...]:
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        for item in reversed(items):
            tags = self.canvas.gettags(item)
            if "hint" in tags or "paper" in tags:
                continue
            if tags:
                return tags
        return ()

    def _kind(self, tags: tuple[str, ...]) -> tuple[str, tuple[int, ...]] | None:
        for tag in tags:
            if tag.startswith("h:"):
                edge, point = tag[2:].split(":")
                return "handle", (int(edge), int(point))
            if tag.startswith("n:"):
                return "node", (int(tag[2:]),)
            if tag.startswith("e:"):
                return "edge", (int(tag[2:]),)
            if tag.startswith("g:"):
                return "group", (int(tag[2:]),)
        return None

    def _press(self, event) -> None:
        kind = self._kind(self._tags(event))
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if kind is None or kind[0] == "group":
            self._drag = {"mode": "pan", "x": event.x, "y": event.y}
            self.canvas.scan_mark(event.x, event.y)
            self.canvas.configure(cursor="hand2")
            return
        mode, data = kind
        if mode == "edge":
            return
        self._dragging = True
        self._fit_mode = False
        self._drag = {"mode": mode, "x": cx, "y": cy, "data": data, "dx": 0.0, "dy": 0.0}
        if mode == "node":
            self.canvas.configure(cursor="fleur")
        elif mode == "handle":
            self.canvas.configure(cursor="crosshair")

    def _press_pan(self, event) -> None:
        self._drag = {"mode": "pan", "x": event.x, "y": event.y}
        self.canvas.scan_mark(event.x, event.y)

    def _pan_motion(self, event) -> None:
        if self._drag and self._drag.get("mode") == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _motion(self, event) -> None:
        if not self._drag:
            return
        if self._drag["mode"] == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        dx, dy = cx - self._drag["x"], cy - self._drag["y"]
        self._drag["x"], self._drag["y"] = cx, cy
        self._drag["dx"] += dx
        self._drag["dy"] += dy
        if self._drag["mode"] == "node":
            index = self._drag["data"][0]
            self.canvas.move(f"n:{index}", dx, dy)
            self._shift_edges(index, dx, dy)
        elif self._drag["mode"] == "handle":
            edge_index, point_index = self._drag["data"]
            self._move_handle(edge_index, point_index, dx, dy)

    def _shift_edges(self, node_index: int, dx: float, dy: float) -> None:
        if self._diagram is None:
            return
        name = list(self._diagram.nodes)[node_index]
        for index, edge in enumerate(self._diagram.edges):
            line = self._edge_line.get(index)
            if line is None:
                continue
            coords = list(self.canvas.coords(line))
            if edge.a == name and edge.b == name:
                coords = [value + (dx if i % 2 == 0 else dy) for i, value in enumerate(coords)]
                self._move_all_handles(index, dx, dy)
            else:
                if edge.a == name and len(coords) >= 2:
                    coords[0] += dx
                    coords[1] += dy
                if edge.b == name and len(coords) >= 2:
                    coords[-2] += dx
                    coords[-1] += dy
            self.canvas.coords(line, *coords)
            for other in self.canvas.find_withtag(f"e:{index}"):
                if other != line and self.canvas.type(other) == "line":
                    self.canvas.coords(other, *coords)

    def _move_all_handles(self, edge_index: int, dx: float, dy: float) -> None:
        for item in self.canvas.find_withtag("handle"):
            tags = self.canvas.gettags(item)
            if any(tag.startswith(f"h:{edge_index}:") for tag in tags):
                self.canvas.move(item, dx, dy)

    def _move_handle(self, edge_index: int, point_index: int,
                     dx: float, dy: float) -> None:
        line = self._edge_line.get(edge_index)
        if line is None:
            return
        coords = list(self.canvas.coords(line))
        slot = point_index * 2
        if slot + 1 >= len(coords):
            return
        coords[slot] += dx
        coords[slot + 1] += dy
        self.canvas.coords(line, *coords)
        for other in self.canvas.find_withtag(f"e:{edge_index}"):
            if other != line and self.canvas.type(other) == "line":
                self.canvas.coords(other, *coords)
        for item in self.canvas.find_withtag(f"h:{edge_index}:{point_index}"):
            self.canvas.move(item, dx, dy)

    def _release(self, event) -> None:
        drag = self._drag
        self._drag = None
        self._dragging = False
        self.canvas.configure(cursor="")
        if not drag or drag["mode"] == "pan" or self._diagram is None:
            self._flush_pending()
            return
        if drag["mode"] == "node" and (abs(drag["dx"]) > 1 or abs(drag["dy"]) > 1):
            index = drag["data"][0]
            node = list(self._diagram.nodes.values())[index]
            x, y = self._unscaled(node.x + drag["dx"] / self.zoom,
                                  node.y + drag["dy"] / self.zoom)
            if self._on_node_moved:
                self._on_node_moved(node.name, x, y)
        elif drag["mode"] == "handle" and (abs(drag["dx"]) > 1 or abs(drag["dy"]) > 1):
            edge_index = drag["data"][0]
            points = self._interior(edge_index)
            if points and self._on_edge_moved:
                self._on_edge_moved(edge_index, points)
        self._flush_pending()

    def _interior(self, edge_index: int) -> list[tuple[float, float]]:
        line = self._edge_line.get(edge_index)
        if line is None:
            return []
        coords = self.canvas.coords(line)
        pts = list(zip(coords[0::2], coords[1::2]))
        return [self._to_diagram(px, py) for px, py in pts[1:-1]]

    def _double(self, event) -> str:
        kind = self._kind(self._tags(event))
        if kind is None or kind[0] != "edge" or self._diagram is None:
            if kind is None:
                self.fit()
            return "break"
        edge_index = kind[1][0]
        edge = self._diagram.edges[edge_index]
        if len(edge.points) < 2:
            return "break"
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        click = self._to_diagram(cx, cy)
        points = [self._unscaled(px, py) for px, py in edge.points]
        placed = self._insert_on_segment(points, click)
        interior = placed[1:-1]
        if interior and self._on_edge_moved:
            self._on_edge_moved(edge_index, interior)
        return "break"

    def _insert_on_segment(self, points: list[tuple[float, float]],
                           click: tuple[float, float]) -> list[tuple[float, float]]:
        best_at = 1
        best = 1e18
        for index in range(len(points) - 1):
            distance = _segment_distance(points[index], points[index + 1], click)
            if distance < best:
                best = distance
                best_at = index + 1
        updated = list(points)
        updated.insert(best_at, click)
        return updated

    def _popup(self, event) -> str:
        if self._diagram is None:
            return "break"
        kind = self._kind(self._tags(event))
        self._menu.delete(0, "end")
        if kind is None:
            return "break"
        mode, data = kind
        if mode == "node":
            node = list(self._diagram.nodes.values())[data[0]]
            label = "Снять блокировку" if node.locked else "Заблокировать положение"
            self._menu.add_command(
                label=label,
                command=lambda: self._lock_node(node, not node.locked),
            )
        elif mode == "group":
            if not (0 <= data[0] < len(self._group_names)):
                return "break"
            group = self._diagram.groups.get(self._group_names[data[0]])
            if group is None:
                return "break"
            label = "Снять блокировку" if group.locked else "Заблокировать положение"
            self._menu.add_command(
                label=label,
                command=lambda: self._lock_group(group, not group.locked),
            )
        elif mode in ("edge", "handle"):
            edge_index = data[0]
            edge = self._diagram.edges[edge_index]
            label = "Снять блокировку" if edge.locked else "Заблокировать положение"
            self._menu.add_command(
                label=label,
                command=lambda: self._lock_edge(edge_index, not edge.locked),
            )
            if mode == "handle":
                point_index = data[1]
                self._menu.add_command(
                    label="Удалить узел",
                    command=lambda: self._delete_handle(edge_index, point_index),
                )
        else:
            return "break"
        self._menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _lock_node(self, node: Node, locked: bool) -> None:
        x, y = self._unscaled(node.x, node.y)
        if self._on_node_lock:
            self._on_node_lock(node.name, locked, x, y)

    def _lock_group(self, group: Group, locked: bool) -> None:
        x, y = self._unscaled(group.x, group.y)
        if self._on_node_lock:
            self._on_node_lock(group.name, locked, x, y)

    def _lock_edge(self, edge_index: int, locked: bool) -> None:
        if self._diagram is None:
            return
        edge = self._diagram.edges[edge_index]
        points = [self._unscaled(px, py) for px, py in edge.points[1:-1]]
        if not points:
            points = self._interior(edge_index)
        if self._on_edge_lock:
            self._on_edge_lock(edge_index, locked, points)

    def _delete_handle(self, edge_index: int, point_index: int) -> None:
        if self._diagram is None:
            return
        edge = self._diagram.edges[edge_index]
        points = [self._unscaled(px, py) for px, py in edge.points[1:-1]]
        interior_index = point_index - 1
        if 0 <= interior_index < len(points):
            del points[interior_index]
        if points and self._on_edge_moved:
            self._on_edge_moved(edge_index, points)
        elif self._on_edge_cleared:
            self._on_edge_cleared(edge_index)

    def _flush_pending(self) -> None:
        pending = getattr(self, "_pending", None)
        if not pending:
            return
        self._pending = None
        self._paint(*pending)
