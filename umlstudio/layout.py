"""Автоматическая раскладка диаграммы.

Используется послойная схема (Сугияма): снятие циклов -> распределение по
слоям -> уменьшение числа пересечений -> расстановка координат -> трассировка
связей. Вложенные пакеты раскладываются рекурсивно: каждая группа сначала
считается отдельной диаграммой, а затем участвует в раскладке родителя
как единый прямоугольник.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .geometry import border_point, normalize, perpendicular, point_at
from .model import Diagram, Edge
from .style import StyleResolver

RECTISH = {"rect", "roundrect", "component", "node3d", "note", "folder",
           "document", "queue", "cylinder", "hexagon", "actor", "dot", "ring"}


@dataclass
class LayoutOptions:
    direction: str = "TB"
    node_sep: float = 44.0
    rank_sep: float = 68.0
    padding: float = 28.0
    edge_style: str = "ortho"
    dummy_size: float = 10.0
    dummy_sep: float = 16.0
    corner: float = 7.0


@dataclass(eq=False)
class _Item:
    key: str
    w: float
    h: float
    index: int
    is_group: bool = False
    x: float = 0.0
    y: float = 0.0


@dataclass(eq=False)
class _Link:
    edge: Edge
    src: str
    dst: str
    flipped: bool = False
    lifted: bool = False
    chain: list[str] = field(default_factory=list)
    points: list[tuple[float, float]] = field(default_factory=list)


# --------------------------------------------------------------- один слой --


class _Level:
    """Послойная раскладка одного уровня вложенности."""

    def __init__(self, items: list[_Item], links: list[_Link],
                 opts: LayoutOptions, style: StyleResolver) -> None:
        self.items = items
        self.by_key = {it.key: it for it in items}
        self.links = links
        self.opts = opts
        self.style = style
        self.horizontal = opts.direction in ("TB", "BT")
        self.flip_rank = opts.direction in ("BT", "RL")

        self.rank: dict[str, int] = {}
        self.osize: dict[str, float] = {}
        self.rsize: dict[str, float] = {}
        self.order: dict[str, float] = {}
        self.rcoord: dict[str, float] = {}
        self.dummies: set[str] = set()
        self.layers: list[list[str]] = []
        self.succ: dict[str, list[str]] = defaultdict(list)
        self.pred: dict[str, list[str]] = defaultdict(list)
        self.flat: list[_Link] = []
        self._dummy_seq = 0
        self._rank_extent = 0.0

    # ---------------------------------------------------------------- api --

    def solve(self) -> tuple[float, float]:
        if not self.items:
            return (0.0, 0.0)
        self._sizes()
        self._orient()
        self._remove_cycles()
        self._rank_items()
        self._build_chains()
        self._init_order()
        self._reduce_crossings()
        self._order_coords()
        self._rank_coords()
        self._route()
        return self._normalize()

    # ------------------------------------------------------------ размеры --

    def _sizes(self) -> None:
        for it in self.items:
            if self.horizontal:
                self.osize[it.key], self.rsize[it.key] = it.w, it.h
            else:
                self.osize[it.key], self.rsize[it.key] = it.h, it.w

    def _orient(self) -> None:
        """Учитывает подсказки направления, заданные в тексте."""
        for link in self.links:
            hint = link.edge.direction
            if hint == "up":
                link.src, link.dst = link.dst, link.src
                link.flipped = not link.flipped

    # ------------------------------------------------------- снятие циклов --

    def _remove_cycles(self) -> None:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for link in self.links:
            if link.edge.direction == "same" or link.src == link.dst:
                continue
            adjacency[link.src].append(link.dst)

        state: dict[str, int] = {}
        back: set[tuple[str, str]] = set()
        for start in (it.key for it in self.items):
            if state.get(start):
                continue
            stack: list[tuple[str, int]] = [(start, 0)]
            state[start] = 1
            while stack:
                node, idx = stack[-1]
                neighbours = adjacency.get(node, ())
                if idx >= len(neighbours):
                    state[node] = 2
                    stack.pop()
                    continue
                stack[-1] = (node, idx + 1)
                nxt = neighbours[idx]
                mark = state.get(nxt, 0)
                if mark == 1:
                    back.add((node, nxt))
                elif mark == 0:
                    state[nxt] = 1
                    stack.append((nxt, 0))
        for link in self.links:
            if (link.src, link.dst) in back:
                link.src, link.dst = link.dst, link.src
                link.flipped = not link.flipped

    # ------------------------------------------------------------- слои ----

    def _rank_items(self) -> None:
        keys = [it.key for it in self.items]
        succ: dict[str, set[str]] = defaultdict(set)
        indeg: dict[str, int] = {k: 0 for k in keys}
        for link in self.links:
            if link.edge.direction == "same" or link.src == link.dst:
                continue
            if link.dst not in succ[link.src]:
                succ[link.src].add(link.dst)
                indeg[link.dst] = indeg.get(link.dst, 0) + 1

        rank = {k: 0 for k in keys}
        queue = [k for k in keys if indeg.get(k, 0) == 0]
        seen = set(queue)
        while queue:
            node = queue.pop(0)
            for nxt in sorted(succ.get(node, ()), key=self._index):
                rank[nxt] = max(rank[nxt], rank[node] + 1)
                indeg[nxt] -= 1
                if indeg[nxt] <= 0 and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        for key in keys:
            if key not in seen:
                rank.setdefault(key, 0)
        self.rank = rank
        self._merge_same_ranks()
        self._compact_ranks()

    def _index(self, key: str) -> int:
        item = self.by_key.get(key)
        return item.index if item else 10**6

    def _merge_same_ranks(self) -> None:
        pairs = [(l.src, l.dst) for l in self.links if l.edge.direction == "same"]
        if not pairs:
            return
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in pairs:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        clusters: dict[str, list[str]] = defaultdict(list)
        for key in list(parent):
            clusters[find(key)].append(key)
        for members in clusters.values():
            target = max(self.rank.get(m, 0) for m in members)
            for m in members:
                self.rank[m] = target

    def _compact_ranks(self) -> None:
        used = sorted({r for r in self.rank.values()})
        remap = {r: i for i, r in enumerate(used)}
        for key in self.rank:
            self.rank[key] = remap[self.rank[key]]

    def _build_chains(self) -> None:
        for link in self.links:
            if link.src == link.dst:
                continue
            ra, rb = self.rank[link.src], self.rank[link.dst]
            if rb < ra:
                link.src, link.dst = link.dst, link.src
                link.flipped = not link.flipped
                ra, rb = rb, ra
            if ra == rb:
                self.flat.append(link)
                link.chain = [link.src, link.dst]
                continue
            chain = [link.src]
            previous = link.src
            for rank in range(ra + 1, rb):
                self._dummy_seq += 1
                key = f"\u0000d{self._dummy_seq}"
                self.dummies.add(key)
                self.rank[key] = rank
                self.osize[key] = self.opts.dummy_size
                self.rsize[key] = 0.0
                self.succ[previous].append(key)
                self.pred[key].append(previous)
                chain.append(key)
                previous = key
            self.succ[previous].append(link.dst)
            self.pred[link.dst].append(previous)
            chain.append(link.dst)
            link.chain = chain

        depth = max(self.rank.values(), default=0) + 1
        self.layers = [[] for _ in range(depth)]

    # --------------------------------------------------------- упорядочение --

    def _init_order(self) -> None:
        by_rank: dict[int, list[str]] = defaultdict(list)
        for it in sorted(self.items, key=lambda i: (self.rank[i.key], i.index)):
            by_rank[self.rank[it.key]].append(it.key)
        for key in sorted(self.dummies, key=lambda k: self.rank[k]):
            by_rank[self.rank[key]].append(key)

        placed: set[str] = set()
        layers: list[list[str]] = [[] for _ in range(len(self.layers))]
        roots = [it.key for it in sorted(self.items, key=lambda i: i.index)
                 if self.rank[it.key] == 0]
        queue = list(roots)
        placed.update(roots)
        for key in roots:
            layers[0].append(key)
        while queue:
            node = queue.pop(0)
            for nxt in self.succ.get(node, ()):
                if nxt in placed:
                    continue
                placed.add(nxt)
                layers[self.rank[nxt]].append(nxt)
                queue.append(nxt)
        for rank, keys in by_rank.items():
            for key in keys:
                if key not in placed:
                    placed.add(key)
                    layers[rank].append(key)
        self.layers = layers

    def _positions(self) -> dict[str, int]:
        return {k: i for layer in self.layers for i, k in enumerate(layer)}

    def _reduce_crossings(self) -> None:
        if len(self.layers) < 2:
            return
        best = [list(layer) for layer in self.layers]
        best_cost = self._crossings(best)
        for iteration in range(8):
            down = iteration % 2 == 0
            self._sweep(down)
            cost = self._crossings(self.layers)
            if cost < best_cost:
                best_cost = cost
                best = [list(layer) for layer in self.layers]
            if best_cost == 0:
                break
        self.layers = best

    def _sweep(self, down: bool) -> None:
        pos = self._positions()
        indices = range(1, len(self.layers)) if down \
            else range(len(self.layers) - 2, -1, -1)
        for rank in indices:
            layer = self.layers[rank]
            neighbours = self.pred if down else self.succ
            medians = [self._median([pos[n] for n in neighbours.get(k, ())
                                     if n in pos]) for k in layer]
            self.layers[rank] = self._reorder(layer, medians)
            pos = self._positions()

    @staticmethod
    def _median(values: list[int]) -> float:
        if not values:
            return -1.0
        values = sorted(values)
        size = len(values)
        middle = size // 2
        if size % 2 == 1:
            return float(values[middle])
        if size == 2:
            return (values[0] + values[1]) / 2
        left = values[middle - 1] - values[0]
        right = values[-1] - values[middle]
        if left + right == 0:
            return (values[middle - 1] + values[middle]) / 2
        return (values[middle - 1] * right + values[middle] * left) / (left + right)

    @staticmethod
    def _reorder(layer: list[str], medians: list[float]) -> list[str]:
        result: list[str | None] = [None] * len(layer)
        movable: list[tuple[float, int]] = []
        for i, value in enumerate(medians):
            if value < 0:
                result[i] = layer[i]
            else:
                movable.append((value, i))
        movable.sort()
        slots = [i for i, value in enumerate(result) if value is None]
        for slot, (_, source) in zip(slots, movable):
            result[slot] = layer[source]
        return [k for k in result if k is not None]

    def _crossings(self, layers: list[list[str]]) -> int:
        pos = {k: i for layer in layers for i, k in enumerate(layer)}
        total = 0
        for rank in range(len(layers) - 1):
            pairs: list[tuple[int, int]] = []
            for upper in layers[rank]:
                for lower in self.succ.get(upper, ()):
                    if lower in pos:
                        pairs.append((pos[upper], pos[lower]))
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    a, b = pairs[i], pairs[j]
                    if (a[0] - b[0]) * (a[1] - b[1]) < 0:
                        total += 1
        return total

    # ------------------------------------------------------- координаты ----

    def _order_coords(self) -> None:
        coords: dict[str, float] = {}
        for layer in self.layers:
            cursor = 0.0
            for key in layer:
                half = self.osize[key] / 2
                coords[key] = cursor + half
                cursor += self.osize[key] + self._sep(key)
        self.order = coords

        for iteration in range(10):
            down = iteration % 2 == 0
            indices = range(len(self.layers)) if down \
                else range(len(self.layers) - 1, -1, -1)
            for rank in indices:
                layer = self.layers[rank]
                if not layer:
                    continue
                targets: list[float] = []
                weights: list[float] = []
                for key in layer:
                    linked = list(self.pred.get(key, ())) if down \
                        else list(self.succ.get(key, ()))
                    if iteration >= 6:
                        linked = list(self.pred.get(key, ())) + \
                            list(self.succ.get(key, ()))
                    known = [coords[n] for n in linked if n in coords]
                    if known:
                        targets.append(sum(known) / len(known))
                        weights.append(6.0 if key in self.dummies else 1.0)
                    else:
                        targets.append(coords[key])
                        weights.append(0.2)
                fitted = self._fit(layer, targets, weights)
                for key, value in zip(layer, fitted):
                    coords[key] = value
        self.order = coords

    def _sep(self, key: str) -> float:
        return self.opts.dummy_sep if key in self.dummies else self.opts.node_sep

    def _fit(self, layer: list[str], targets: list[float],
             weights: list[float]) -> list[float]:
        """Ближайшее к целям размещение, не нарушающее порядок и зазоры."""
        offsets = [0.0]
        for i in range(len(layer) - 1):
            gap = (self.osize[layer[i]] + self.osize[layer[i + 1]]) / 2
            gap += max(self._sep(layer[i]), self._sep(layer[i + 1]))
            offsets.append(offsets[-1] + gap)
        shifted = [t - o for t, o in zip(targets, offsets)]
        fitted = _isotonic(shifted, weights)
        return [v + o for v, o in zip(fitted, offsets)]

    def _rank_coords(self) -> None:
        extra = self._label_gaps()
        cursor = 0.0
        for rank, layer in enumerate(self.layers):
            band = max((self.rsize[k] for k in layer), default=0.0)
            band = max(band, self.style.px(4))
            for key in layer:
                self.rcoord[key] = cursor + band / 2
            cursor += band + self.opts.rank_sep + extra.get(rank, 0.0)
        self._rank_extent = max(cursor - self.opts.rank_sep, 0.0)

    def _label_gaps(self) -> dict[int, float]:
        gaps: dict[int, float] = {}
        for link in self.links:
            if not link.chain or link in self.flat:
                continue
            text = link.edge.label
            if not text and not link.edge.a_mult and not link.edge.b_mult:
                continue
            _, height = self.style.edge_label_size(text or "0")
            rank = self.rank[link.src]
            gaps[rank] = max(gaps.get(rank, 0.0), height + self.style.px(6))
        return gaps

    # ------------------------------------------------------- трассировка ---

    def _route(self) -> None:
        out_slots: dict[str, list[tuple[float, _Link]]] = defaultdict(list)
        in_slots: dict[str, list[tuple[float, _Link]]] = defaultdict(list)
        for link in self.links:
            if link in self.flat or len(link.chain) < 2:
                continue
            out_slots[link.src].append((self.order[link.chain[1]], link))
            in_slots[link.dst].append((self.order[link.chain[-2]], link))

        out_port = self._ports(out_slots)
        in_port = self._ports(in_slots)

        for link in self.links:
            if not link.chain:
                continue
            if link in self.flat:
                pts = self._flat_route(link)
            else:
                start = out_port.get(id(link), self.order[link.src])
                end = in_port.get(id(link), self.order[link.dst])
                pts = [(start, self._far(link.src))]
                for key in link.chain[1:-1]:
                    pts.append((self.order[key], self.rcoord[key]))
                pts.append((end, self._near(link.dst)))
                if self.opts.edge_style != "straight":
                    pts = self._orthogonal(pts)
            link.points = [self._to_xy(o, r) for o, r in pts]
            if link.flipped:
                link.points.reverse()

    def _ports(self, slots: dict[str, list[tuple[float, _Link]]]) -> dict[int, float]:
        ports: dict[int, float] = {}
        for key, entries in slots.items():
            entries.sort(key=lambda e: e[0])
            count = len(entries)
            if count == 1:
                ports[id(entries[0][1])] = self.order[key]
                continue
            span = self.osize[key] * 0.68
            base = self.order[key] - span / 2
            for i, (_, link) in enumerate(entries):
                ports[id(link)] = base + span * (i + 0.5) / count
        return ports

    def _far(self, key: str) -> float:
        return self.rcoord[key] + self.rsize[key] / 2

    def _near(self, key: str) -> float:
        return self.rcoord[key] - self.rsize[key] / 2

    def _flat_route(self, link: _Link) -> list[tuple[float, float]]:
        src, dst = link.src, link.dst
        layer = self.layers[self.rank[src]]
        try:
            adjacent = abs(layer.index(src) - layer.index(dst)) == 1
        except ValueError:
            adjacent = False
        left_to_right = self.order[src] <= self.order[dst]
        so = self.order[src] + (1 if left_to_right else -1) * self.osize[src] / 2
        do = self.order[dst] - (1 if left_to_right else -1) * self.osize[dst] / 2
        if adjacent:
            return [(so, self.rcoord[src]), (do, self.rcoord[dst])]
        drop = self.opts.rank_sep * 0.38
        sr = self._far(src)
        dr = self._far(dst)
        return [
            (self.order[src], sr),
            (self.order[src], sr + drop),
            (self.order[dst], dr + drop),
            (self.order[dst], dr),
        ]

    @staticmethod
    def _orthogonal(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = [points[0]]
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            if abs(a[0] - b[0]) > 0.75 and abs(a[1] - b[1]) > 0.75:
                middle = (a[1] + b[1]) / 2
                out.append((a[0], middle))
                out.append((b[0], middle))
            out.append(b)
        deduped: list[tuple[float, float]] = []
        for p in out:
            if not deduped or math.dist(deduped[-1], p) > 0.4:
                deduped.append(p)
        return deduped

    def _to_xy(self, order: float, rank: float) -> tuple[float, float]:
        if self.flip_rank:
            rank = self._rank_extent - rank
        return (order, rank) if self.horizontal else (rank, order)

    # ---------------------------------------------------------- финализация --

    def _normalize(self) -> tuple[float, float]:
        for it in self.items:
            x, y = self._to_xy(self.order[it.key], self.rcoord[it.key])
            it.x = x - it.w / 2
            it.y = y - it.h / 2

        xs: list[float] = []
        ys: list[float] = []
        for it in self.items:
            xs += [it.x, it.x + it.w]
            ys += [it.y, it.y + it.h]
        for link in self.links:
            for px, py in link.points:
                xs.append(px)
                ys.append(py)
        if not xs:
            return (0.0, 0.0)
        dx, dy = -min(xs), -min(ys)
        for it in self.items:
            it.x += dx
            it.y += dy
        for link in self.links:
            link.points = [(px + dx, py + dy) for px, py in link.points]
        return (max(xs) - min(xs), max(ys) - min(ys))


def _isotonic(values: list[float], weights: list[float]) -> list[float]:
    """Взвешенная изотоническая регрессия (алгоритм PAVA)."""
    means: list[float] = []
    mass: list[float] = []
    counts: list[int] = []
    for value, weight in zip(values, weights):
        means.append(value)
        mass.append(max(1e-6, weight))
        counts.append(1)
        while len(means) > 1 and means[-2] > means[-1]:
            m2, w2, c2 = means.pop(), mass.pop(), counts.pop()
            m1, w1, c1 = means.pop(), mass.pop(), counts.pop()
            total = w1 + w2
            means.append((m1 * w1 + m2 * w2) / total)
            mass.append(total)
            counts.append(c1 + c2)
    out: list[float] = []
    for value, count in zip(means, counts):
        out.extend([value] * count)
    return out


# ------------------------------------------------------- раскладка целиком --


def layout_diagram(diagram: Diagram, style: StyleResolver) -> None:
    """Расставляет координаты всех объектов, групп и связей."""
    opts = _options(diagram, style)
    for node in diagram.nodes.values():
        style.measure_node(node)
    _sanitize_groups(diagram)

    group_kids: dict[str | None, list[str]] = defaultdict(list)
    node_kids: dict[str | None, list[str]] = defaultdict(list)
    for name, group in diagram.groups.items():
        group_kids[group.parent].append(name)
    for name, node in diagram.nodes.items():
        node_kids[node.group].append(name)

    ancestors: dict[str, list[str]] = {}
    for name, node in diagram.nodes.items():
        ancestors[name] = diagram.group_path(node.group)

    def item_key(level: str | None, node_name: str) -> str | None:
        chain = ancestors.get(node_name, [])
        if level is None:
            return chain[0] if chain else node_name
        if level not in chain:
            return None
        position = chain.index(level)
        return chain[position + 1] if position + 1 < len(chain) else node_name

    content_size: dict[str | None, tuple[float, float]] = {}
    level_items: dict[str | None, list[_Item]] = {}
    level_links: dict[str | None, list[_Link]] = {}
    handled: set[int] = set()

    def solve(level: str | None) -> tuple[float, float]:
        for child in group_kids.get(level, ()):
            solve(child)

        items: list[_Item] = []
        index = 0
        for name in node_kids.get(level, ()):
            node = diagram.nodes[name]
            items.append(_Item(name, node.w, node.h, index))
            index += 1
        for name in group_kids.get(level, ()):
            width, height = _group_box(diagram, style, name, content_size[name])
            group = diagram.groups[name]
            group.w, group.h = width, height
            items.append(_Item(name, width, height, index, is_group=True))
            index += 1

        keys = {it.key for it in items}
        links: list[_Link] = []
        for edge in diagram.edges:
            if id(edge) in handled:
                continue
            a = item_key(level, edge.a)
            b = item_key(level, edge.b)
            if a is None or b is None or a not in keys or b not in keys:
                continue
            if a == b:
                continue
            handled.add(id(edge))
            links.append(_Link(edge, a, b,
                               lifted=(a != edge.a or b != edge.b)))

        level_obj = _Level(items, links, opts, style)
        size = level_obj.solve()
        level_items[level] = items
        level_links[level] = links
        content_size[level] = size
        return size

    solve(None)

    reserve = _reserve(diagram, style)
    origin = (opts.padding, opts.padding + reserve["top"])
    _place(diagram, style, None, origin, level_items, level_links, opts)

    _route_lifted(diagram, level_links, opts, style)
    _route_self_loops(diagram, opts, style)
    attach_shape_ends(diagram, style)
    _place_labels(diagram, style, opts)

    width, height = _bounds(diagram, style)
    width += opts.padding
    needed = reserve["width"] + 2 * opts.padding
    if needed > width:
        _shift_all(diagram, (needed - width) / 2)
        width = needed
    diagram.width = width
    diagram.height = height + opts.padding + reserve["bottom"]
    diagram.metrics = {
        "reserve": reserve,
        "padding": opts.padding,
        "corner": opts.corner,
        "direction": opts.direction,
    }


def _options(diagram: Diagram, style: StyleResolver) -> LayoutOptions:
    return LayoutOptions(
        direction=str(diagram.opt("direction", "TB") or "TB").upper(),
        node_sep=style.px(float(diagram.opt("node_sep", 44) or 44)),
        rank_sep=style.px(float(diagram.opt("rank_sep", 68) or 68)),
        padding=style.px(float(diagram.opt("padding", 28) or 28)),
        edge_style=str(diagram.opt("edge_style", "ortho") or "ortho").lower(),
        dummy_size=style.px(10),
        dummy_sep=style.px(18),
        corner=style.px(7),
    )


def _sanitize_groups(diagram: Diagram) -> None:
    for group in diagram.groups.values():
        if group.parent not in diagram.groups:
            group.parent = None
    for group in diagram.groups.values():
        seen: set[str] = {group.name}
        cursor = group.parent
        while cursor:
            if cursor in seen:
                group.parent = None
                break
            seen.add(cursor)
            cursor = diagram.groups[cursor].parent if cursor in diagram.groups else None
    for node in diagram.nodes.values():
        if node.group is not None and node.group not in diagram.groups:
            node.group = None


def _group_box(diagram: Diagram, style: StyleResolver, name: str,
               content: tuple[float, float]) -> tuple[float, float]:
    metrics = style.group_metrics(diagram.groups[name])
    pad = metrics["pad"]
    diagram.groups[name].header_h = metrics["header_h"]
    width = max(content[0] + 2 * pad, metrics["label_w"], style.px(120))
    height = content[1] + metrics["header_h"] + 2 * pad
    return (round(width), round(height))


def _place(diagram: Diagram, style: StyleResolver, level: str | None,
           origin: tuple[float, float], level_items, level_links,
           opts: LayoutOptions) -> None:
    ox, oy = origin
    for item in level_items.get(level, ()):
        if item.is_group:
            group = diagram.groups[item.key]
            group.x, group.y = ox + item.x, oy + item.y
            metrics = style.group_metrics(group)
            _place(diagram, style, item.key,
                   (group.x + metrics["pad"], group.y + group.header_h +
                    metrics["pad"]),
                   level_items, level_links, opts)
        else:
            node = diagram.nodes[item.key]
            node.x, node.y = ox + item.x, oy + item.y
    for link in level_links.get(level, ()):
        link.points = [(px + ox, py + oy) for px, py in link.points]
        if not link.lifted:
            link.edge.points = link.points


def _route_lifted(diagram: Diagram, level_links, opts: LayoutOptions,
                  style: StyleResolver) -> None:
    """Достраивает связи, у которых концы лежат в разных пакетах.

    Середина маршрута берётся из раскладки уровня (она уже обходит чужие
    прямоугольники), а к настоящим объектам он дотягивается по краям.
    """
    lanes: dict[tuple, int] = defaultdict(int)
    for links in level_links.values():
        for link in links:
            if not link.lifted:
                continue
            edge = link.edge
            a, b = diagram.nodes.get(edge.a), diagram.nodes.get(edge.b)
            if a is None or b is None:
                edge.points = []
                continue
            corridor_a = _corridor(diagram, a)
            corridor_b = _corridor(diagram, b)
            key = (tuple(round(v) for v in corridor_a),
                   tuple(round(v) for v in corridor_b))
            lane = lanes[key]
            lanes[key] += 1
            edge.points = _corridor_route(a, b, corridor_a, corridor_b,
                                          opts, style, lane)


def _corridor(diagram: Diagram, node) -> tuple[float, float, float, float]:
    """Габариты самого внешнего пакета, в котором лежит объект."""
    chain = diagram.group_path(node.group)
    if not chain:
        return node.box()
    group = diagram.groups[chain[0]]
    return (group.x, group.y, group.x + group.w, group.y + group.h)


def _corridor_route(a, b, ca, cb, opts: LayoutOptions, style: StyleResolver,
                    lane: int) -> list[tuple[float, float]]:
    """Ортогональный маршрут с изгибом в свободном зазоре между пакетами."""
    slack = style.px(16)
    shift = ((lane % 5) - 2) * style.px(9)
    order = ("x+", "x-", "y+", "y-") if opts.direction in ("LR", "RL") \
        else ("y+", "y-", "x+", "x-")
    for attempt in order:
        if attempt == "x+" and cb[0] - ca[2] > slack:
            jog = _lane(ca[2], cb[0], shift, style)
            return [(a.x + a.w, a.cy), (jog, a.cy), (jog, b.cy), (b.x, b.cy)]
        if attempt == "x-" and ca[0] - cb[2] > slack:
            jog = _lane(cb[2], ca[0], shift, style)
            return [(a.x, a.cy), (jog, a.cy), (jog, b.cy), (b.x + b.w, b.cy)]
        if attempt == "y+" and cb[1] - ca[3] > slack:
            jog = _lane(ca[3], cb[1], shift, style)
            return [(a.cx, a.y + a.h), (a.cx, jog), (b.cx, jog), (b.cx, b.y)]
        if attempt == "y-" and ca[1] - cb[3] > slack:
            jog = _lane(cb[3], ca[1], shift, style)
            return [(a.cx, a.y), (a.cx, jog), (b.cx, jog), (b.cx, b.y + b.h)]
    return _direct_route(a, b, opts, style)


def _lane(low: float, high: float, shift: float, style: StyleResolver) -> float:
    margin = min(style.px(7), (high - low) / 3)
    return min(max((low + high) / 2 + shift, low + margin), high - margin)


def _direct_route(a, b, opts: LayoutOptions, style: StyleResolver
                  ) -> list[tuple[float, float]]:
    vertical = opts.direction in ("TB", "BT")
    if vertical:
        gap = b.y - (a.y + a.h) if b.cy >= a.cy else a.y - (b.y + b.h)
        if gap > style.px(18):
            top, bottom = (a, b) if b.cy >= a.cy else (b, a)
            middle = (top.y + top.h + bottom.y) / 2
            points = [(top.cx, top.y + top.h), (top.cx, middle),
                      (bottom.cx, middle), (bottom.cx, bottom.y)]
            return points if top is a else list(reversed(points))
        left, right = (a, b) if b.cx >= a.cx else (b, a)
        middle = (left.x + left.w + right.x) / 2
        points = [(left.x + left.w, left.cy), (middle, left.cy),
                  (middle, right.cy), (right.x, right.cy)]
        return points if left is a else list(reversed(points))
    gap = b.x - (a.x + a.w) if b.cx >= a.cx else a.x - (b.x + b.w)
    if gap > style.px(18):
        left, right = (a, b) if b.cx >= a.cx else (b, a)
        middle = (left.x + left.w + right.x) / 2
        points = [(left.x + left.w, left.cy), (middle, left.cy),
                  (middle, right.cy), (right.x, right.cy)]
        return points if left is a else list(reversed(points))
    top, bottom = (a, b) if b.cy >= a.cy else (b, a)
    middle = (top.y + top.h + bottom.y) / 2
    points = [(top.cx, top.y + top.h), (top.cx, middle),
              (bottom.cx, middle), (bottom.cx, bottom.y)]
    return points if top is a else list(reversed(points))


def _route_self_loops(diagram: Diagram, opts: LayoutOptions,
                      style: StyleResolver) -> None:
    counters: dict[str, int] = defaultdict(int)
    for edge in diagram.edges:
        if edge.a != edge.b or edge.points:
            continue
        node = diagram.nodes.get(edge.a)
        if node is None:
            continue
        index = counters[edge.a]
        counters[edge.a] += 1
        reach = style.px(26) + index * style.px(14)
        top = node.y + node.h * 0.28
        low = node.y + node.h * 0.72
        right = node.x + node.w
        edge.points = [(right, top), (right + reach, top),
                       (right + reach, low), (right, low)]


def _place_labels(diagram: Diagram, style: StyleResolver,
                  opts: LayoutOptions) -> None:
    for edge in diagram.edges:
        if not edge.label or len(edge.points) < 2:
            edge.label_pos = None
            continue
        mid, direction = point_at(edge.points, 0.5)
        side = perpendicular(normalize(direction))
        width, height = style.edge_label_size(edge.label)
        offset = (abs(side[0]) * width / 2 + abs(side[1]) * height / 2) + style.px(5)
        if side[0] < 0 or (abs(side[0]) < 1e-6 and side[1] < 0):
            side = (-side[0], -side[1])
        edge.label_pos = (mid[0] + side[0] * offset, mid[1] + side[1] * offset)


def _bounds(diagram: Diagram, style: StyleResolver) -> tuple[float, float]:
    xs: list[float] = [0.0]
    ys: list[float] = [0.0]
    for node in diagram.nodes.values():
        xs += [node.x, node.x + node.w]
        ys += [node.y, node.y + node.h]
    for group in diagram.groups.values():
        xs += [group.x, group.x + group.w]
        ys += [group.y, group.y + group.h]
    for edge in diagram.edges:
        for px, py in edge.points:
            xs.append(px)
            ys.append(py)
        if edge.label_pos:
            width, height = style.edge_label_size(edge.label)
            xs += [edge.label_pos[0] - width / 2, edge.label_pos[0] + width / 2]
            ys += [edge.label_pos[1] - height / 2, edge.label_pos[1] + height / 2]
    return (max(xs), max(ys))


def _reserve(diagram: Diagram, style: StyleResolver) -> dict[str, float]:
    top = 0.0
    width = 0.0
    if diagram.title:
        size = float(diagram.opt("title_size", 0) or 0) or style.base_size + 8
        lines = diagram.title.split("\n")
        top = style.font_height(size, bold=True) * len(lines) + style.px(18)
        width = max(style.font_width(line, size, bold=True) for line in lines)
    bottom = 0.0
    if diagram.caption:
        bottom += style.font_height(style.base_size) + style.px(14)
        width = max(width, style.font_width(diagram.caption, style.base_size,
                                            italic=True))
    if diagram.legend:
        bottom += (style.font_height(style.small_size + 1) + style.px(3)) * \
            len(diagram.legend) + style.px(26)
        width = max(width, max(style.font_width(line, style.small_size + 1)
                               for line in diagram.legend) + style.px(24))
    return {"top": top, "bottom": bottom, "width": width}


def _shift_all(diagram: Diagram, dx: float) -> None:
    for node in diagram.nodes.values():
        node.x += dx
    for group in diagram.groups.values():
        group.x += dx
    for edge in diagram.edges:
        edge.points = [(px + dx, py) for px, py in edge.points]
        if edge.label_pos:
            edge.label_pos = (edge.label_pos[0] + dx, edge.label_pos[1])


def attach_shape_ends(diagram: Diagram, style: StyleResolver) -> None:
    """Подтягивает концы связей к границам неугловатых форм."""
    for edge in diagram.edges:
        if len(edge.points) < 2:
            continue
        a, b = diagram.nodes.get(edge.a), diagram.nodes.get(edge.b)
        if a is not None and a is not b:
            form = style.node_style(a)["form"]
            if form not in RECTISH:
                edge.points[0] = border_point(form, a.box(), edge.points[1])
        if b is not None and b is not a:
            form = style.node_style(b)["form"]
            if form not in RECTISH:
                edge.points[-1] = border_point(form, b.box(), edge.points[-2])
