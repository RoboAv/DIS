# UML Studio — описание для разработки

Текстовый редактор UML-диаграмм. Слева исходник, справа PNG. Разбор, раскладка и рисование свои: Java, Graphviz и сеть не нужны. Зависимость для картинки — Pillow, окно — Tkinter.

Каталог приложения — этот `umlstudio/`. Пакет Python вложен ещё на уровень: `umlstudio/umlstudio/`. Запуск из этого каталога:

```powershell
pip install -r ..\requirements.txt
python main.py
python main.py diagram.uml -o diagram.png
```

Подробности по модулям: [documentation/README.md](documentation/README.md).

## Поток данных

`parse` → `StyleResolver.measure_node` → `layout_diagram` → `render_image`. Точка входа — `api.build` / `api.render_to_file`.

Синтаксис близок к PlantUML и описан справкой в программе (`F1`, текст в `umlstudio/gui/examples.py`). Меняя грамматику, обновляй и справку.

## Что не ломать без запроса

- `-[left]->` ставит цель слева от источника, `-[right]->` — справа, оба на одном уровне. То же для `слева` / `справа` и для `note left/right of`. Логика в `parser.DIR_WORDS` и `layout._apply_side_hints`.
- Ортогональные связи (`set edge_style = ortho`, значение по умолчанию) стремятся к минимуму углов. Прямая, если концы на одной оси и путь свободен; иначе один сдвиг на весь пролёт. Лишние опоры пропускаются, пока линия не пересекает чужой объект. Дополнительные углы только там, где прямой ход закрыт. Выход и вход остаются по оси уровня. Код: `_Level._orthogonal`. `straight` этот расчёт не включает.
- Горизонтали внутри объекта (разделители секций и линия шапки пакета) идут по `shapes.horizontal_chords`: концы лежат на контуре формы и линия не выходит за него. Контур должен совпадать с `draw_form`.
