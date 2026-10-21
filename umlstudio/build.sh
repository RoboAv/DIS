#!/usr/bin/env bash
# Собирает UML Studio в один файл для Linux. Запускать на Linux или в WSL:
#   bash build.sh
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

if ! "$PYTHON" -c "import tkinter, PIL" >/dev/null 2>&1; then
  echo "Нужны tkinter и Pillow."
  echo "Debian/Ubuntu: sudo apt install python3-tk fonts-dejavu"
  echo "Затем: $PYTHON -m pip install pillow pyinstaller"
  exit 1
fi

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "Не установлен PyInstaller: $PYTHON -m pip install pyinstaller"
  exit 1
fi

# У ELF нет значка файла. logo.ico кладётся внутрь, окно читает его само.
"$PYTHON" -m PyInstaller --noconfirm --onefile --windowed \
  --name "UML Studio" \
  --add-data "assets/logo.ico:assets" \
  --hidden-import PIL.ImageTk \
  main.py

echo
echo "Готово: $(pwd)/dist/UML Studio"
