"""Dota 2 Game State Integration: официальный способ узнать, что ты в матче.

Dota сама шлёт POST-запросы с состоянием игры на локальный сервер.
Нужен параметр запуска -gamestateintegration и cfg-файл (ставится автоматически)."""
import json
import logging
import re
import threading
import time
import winreg
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

CFG_NAME = "gamestate_integration_autoaccept.cfg"
CFG_TEMPLATE = """"dota2-autoaccept"
{{
    "uri"           "http://127.0.0.1:{port}/"
    "timeout"       "5.0"
    "buffer"        "0.1"
    "throttle"      "0.5"
    "heartbeat"     "10.0"
    "data"
    {{
        "provider"  "1"
        "map"       "1"
    }}
}}
"""


def find_dota_dirs():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        steam = Path(r"C:\Program Files (x86)\Steam")
    libs = {steam}
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
            libs.add(Path(p.replace("\\\\", "\\")))
    return [d for lib in libs
            if (d := lib / "steamapps" / "common" / "dota 2 beta" / "game" / "dota").is_dir()]


def install_config(port):
    """Кладёт cfg в папку Dota. Возвращает путь или None."""
    dirs = find_dota_dirs()
    if not dirs:
        log.warning("GSI: папка Dota 2 не найдена")
        return None
    content = CFG_TEMPLATE.format(port=port)
    for d in dirs:
        target = d / "cfg" / "gamestate_integration" / CFG_NAME
        try:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                log.info("GSI: конфиг записан в %s", target)
            return target
        except OSError as e:
            log.error("GSI: не удалось записать %s: %s", target, e)
    return None


class GsiServer:
    def __init__(self, port, on_state_change=None):
        self.port = port
        self.on_state_change = on_state_change
        self.game_state = None  # None = главное меню, иначе DOTA_GAMERULES_STATE_*
        self.last_update = 0.0

    @property
    def connected(self):
        return time.time() - self.last_update < 30

    @property
    def in_match(self):
        return self.connected and self.game_state is not None

    def _handle(self, data):
        self.last_update = time.time()
        state = (data.get("map") or {}).get("game_state")
        if state != self.game_state:
            log.info("GSI: %s -> %s", self.game_state, state)
            old, self.game_state = self.game_state, state
            if self.on_state_change:
                self.on_state_change(old, state)

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                try:
                    server._handle(json.loads(body or b"{}"))
                except Exception as e:
                    log.error("GSI: плохой запрос: %s", e)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as e:
            log.error("GSI: порт %s занят: %s", self.port, e)
            return False
        threading.Thread(target=httpd.serve_forever, name="gsi", daemon=True).start()
        log.info("GSI: слушаю 127.0.0.1:%s", self.port)
        return True
