@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt || (echo Нужен Python 3.10+ с python.org & pause & exit /b 1)
python main.py --autostart on
start "" pythonw main.py --wait-for-dota
echo Готово. Запусти Dota 2 - в трее появится иконка.
pause
