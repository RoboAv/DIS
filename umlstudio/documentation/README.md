# Документация для разработки

UML Studio рисует диаграмму из текста. Внешние движки не используются.

| Документ | О чём |
|---|---|
| [architecture.md](architecture.md) | модули и путь от текста до PNG |
| [layout.md](layout.md) | раскладка, `left`/`right`, ортогональные связи |
| [rendering.md](rendering.md) | формы и линии внутри них |

Краткое описание для сессии в Cursor — в [../cursor.md](../cursor.md).

## Где что лежит

```
umlstudio/                  этот каталог, отсюда запускается main.py
  main.py                   окно или экспорт PNG из командной строки
  cursor.md
  documentation/
  umlstudio/                пакет
    parser.py               текст → модель
    model.py                Node, Edge, Group, Diagram
    style.py                шрифты, стиль, размеры объектов
    layout.py               координаты и маршруты связей
    geometry.py             отрезки, скругление углов, точка на bbox
    shapes.py               контуры форм
    arrows.py               окончания связей
    renderer.py             Pillow
    theme.py                темы, виды объектов и связей по умолчанию
    api.py                  build / render_to_file
    gui/                    редактор Tkinter
```

Корень репозитория на уровень выше: там `README.md` для пользователя и `requirements.txt`.

## Как проверить картинку

```powershell
python main.py diagram.uml -o out.png -s 2
```

Либо из кода: `umlstudio.api.render_to_file(text, path)`. Окно после правок интерфейса стоит прогнать руками: предпросмотр, масштаб, список проблем.
