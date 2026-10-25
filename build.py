"""Сборка dist/DotaAutoAccept.exe:  pip install -r requirements.txt pyinstaller && python build.py"""
from pathlib import Path

import PyInstaller.__main__

from main import make_icon

ROOT = Path(__file__).resolve().parent
ICON = ROOT / "build" / "icon.ico"

ICON.parent.mkdir(exist_ok=True)
make_icon((60, 170, 70), size=256).save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

PyInstaller.__main__.run([
    str(ROOT / "main.py"),
    "--name", "DotaAutoAccept",
    "--onefile",
    "--windowed",  # без консольного окна
    "--icon", str(ICON),
    "--noconfirm",
    "--clean",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
])
