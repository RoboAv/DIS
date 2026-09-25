"""Точка входа UML Studio.

Без аргументов открывается окно редактора. Аргументы позволяют собрать PNG
из командной строки:

    python main.py                      окно редактора
    python main.py diagram.uml          окно редактора с открытым файлом
    python main.py diagram.uml -o d.png только отрисовать PNG
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cli(args: argparse.Namespace) -> int:
    from umlstudio import api

    source = Path(args.source)
    if not source.is_file():
        print(f"файл не найден: {source}", file=sys.stderr)
        return 2
    text = source.read_text(encoding="utf-8-sig")
    target = Path(args.out) if args.out else source.with_suffix(".png")
    result = api.render_to_file(text, str(target), scale=args.scale)
    for item in result.diagnostics:
        print(item, file=sys.stderr)
    if not result.ok:
        print(f"не удалось отрисовать: {result.error}", file=sys.stderr)
        return 1
    print(f"{target}  {result.size[0]}x{result.size[1]} px  "
          f"{result.duration * 1000:.0f} мс")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uml-studio",
        description="Редактор UML-диаграмм с отрисовкой в PNG.")
    parser.add_argument("source", nargs="?", help="файл с текстом диаграммы")
    parser.add_argument("-o", "--out", help="куда сохранить PNG (включает "
                                           "режим командной строки)")
    parser.add_argument("-s", "--scale", type=float, default=1.0,
                        help="множитель размера картинки (по умолчанию 1)")
    args = parser.parse_args(argv)

    if args.out:
        if not args.source:
            parser.error("для экспорта нужен входной файл")
        return _cli(args)

    from umlstudio.gui import run
    run(args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
