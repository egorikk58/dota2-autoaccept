"""Dota 2 Auto Accept — автопринятие найденной игры + пуш на телефон через ntfy.

Запуск:  pythonw main.py                 — иконка в трее
         python main.py --test-image F   — проверить детектор на скриншоте
         python main.py --test-notify    — отправить тестовый пуш
"""
import argparse
import copy
import ctypes
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import pystray
from PIL import Image, ImageDraw

import detector
import gsi
import notifier
import winutil

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"

DEFAULT_CONFIG = {
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",  # генерируется при первом запуске
    "gsi_port": 53000,
    "scan_interval": 0.7,
    "cooldown_after_accept": 25,
    "focus_on_flash": True,
    "notify_pick_started": True,
    "save_debug_screenshots": True,
    "detector": dict(detector.DEFAULTS),
}

log = logging.getLogger("autoaccept")


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(LOG_DIR / "autoaccept.log", maxBytes=1_000_000,
                                    backupCount=2, encoding="utf-8")]
    if sys.stdout:  # под pythonw stdout нет
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg["detector"].update(user.pop("detector", {}))
        cfg.update(user)
    if not cfg["ntfy_topic"]:
        # Топик в ntfy.sh публичный — кто знает имя, тот читает. Поэтому у каждого свой, неугадываемый.
        cfg["ntfy_topic"] = "dota-" + secrets.token_hex(8)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


def copy_to_clipboard(text):
    subprocess.run(["clip"], input=text.encode("utf-16-le"), check=False,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def show_welcome(topic):
    """Первый запуск: показываем пользователю его личный топик."""
    copy_to_clipboard(topic)
    text = (
        f"Твой личный ntfy-топик:\n\n    {topic}\n\n"
        "(уже скопирован в буфер обмена)\n\n"
        "1. Установи приложение ntfy на телефон (App Store / Google Play).\n"
        "2. Нажми «+» → Subscribe to topic → вставь топик, сервер ntfy.sh.\n"
        "3. В меню иконки в трее нажми «Тестовый пуш на телефон».\n\n"
        "Никому не показывай топик: по нему можно читать твои уведомления.\n"
        "Скопировать его ещё раз можно из меню иконки в трее."
    )
    threading.Thread(target=ctypes.windll.user32.MessageBoxW,
                     args=(None, text, "Dota 2 Auto Accept", 0x40), daemon=True).start()


STARTUP_LNK = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup\Dota2AutoAccept.lnk"


def autostart_enabled():
    return STARTUP_LNK.exists()


def set_autostart(enable):
    if not enable:
        STARTUP_LNK.unlink(missing_ok=True)
        log.info("автозапуск выключен")
        return
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath = $env:EXE; $s.Arguments = $env:ARGS;"
        "$s.WorkingDirectory = $env:DIR; $s.Save()"
    )
    env = {**os.environ, "LNK": str(STARTUP_LNK), "EXE": str(pythonw),
           "ARGS": f'"{APP_DIR / "main.py"}" --wait-for-dota', "DIR": str(APP_DIR)}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    log.info("автозапуск включён: %s", STARTUP_LNK)


def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color, outline=(20, 20, 20), width=3)
    d.text((24, 18), "D", fill=(255, 255, 255))
    return img


ICON_ON = make_icon((60, 170, 70))
ICON_OFF = make_icon((130, 130, 130))
ICON_WAIT = make_icon((210, 160, 40))


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = True
        self.stop = threading.Event()
        self.flash = threading.Event()
        self.cooldown_until = 0.0
        self.awaiting_pick = False
        self.status = "запуск…"
        self.icon = None
        self.wait_for_dota = False
        self.dota_seen = 0.0
        self.ntfy =notifier.Ntfy(cfg["ntfy_server"], cfg["ntfy_topic"])
        self.gsi = gsi.GsiServer(cfg["gsi_port"], on_state_change=self.on_game_state)

    # --- статус и трей ---

    def set_status(self, text, icon=None):
        if text == self.status:
            return
        self.status = text
        log.info("статус: %s", text)
        if self.icon:
            self.icon.title = f"Dota 2 Auto Accept — {text}"[:127]
            self.icon.icon = ICON_OFF if not self.enabled else (icon or ICON_ON)
            self.icon.update_menu()

    def toggle(self, *_):
        self.enabled = not self.enabled
        self.set_status("включено" if self.enabled else "выключено")

    def test_notify(self, *_):
        self.ntfy.send_async("Dota 2 Auto Accept", "Тест: уведомления работают 👍", 3, ["white_check_mark"])

    def debug_screenshot(self, *_):
        hwnd = winutil.find_dota_window()
        if not hwnd:
            log.info("отладка: окно Dota 2 не найдено")
            return
        img = self.grab(hwnd)
        if img is None:
            log.info("отладка: не удалось снять окно")
            return
        hit = detector.find_accept_button(img, self.cfg["detector"])
        path = self.save_debug(img, hit, "manual")
        log.info("отладка: кнопка %s, снимок %s", "НАЙДЕНА" if hit else "не найдена", path)
        os.startfile(path)

    def save_debug(self, img, hit, tag):
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.png"
        cv2.imwrite(str(path), detector.annotate(img, hit, self.cfg["detector"]))
        return path

    def quit(self, *_):
        self.stop.set()
        if self.icon:
            self.icon.stop()

    # --- события ---

    def on_flash(self, hwnd):
        log.info("Dota мигает в панели задач")
        self.flash.set()

    def on_game_state(self, old, new):
        if new and self.awaiting_pick and self.cfg["notify_pick_started"]:
            self.awaiting_pick = False
            self.ntfy.send_async("Пик начался! ⚔️", "Все приняли игру — выбирай героя.", 5, ["crossed_swords"])

    # --- основной цикл ---

    def grab(self, hwnd):
        img = winutil.capture_window(hwnd)
        # PrintWindow иногда отдаёт чёрный кадр (эксклюзивный полноэкранный режим)
        if (img is None or img.max() < 10) and winutil.is_foreground(hwnd):
            img = winutil.capture_screen_rect(hwnd)
        return img

    def loop(self):
        while not self.stop.wait(self.cfg["scan_interval"]):
            if not self.enabled:
                continue
            try:
                self.tick()
            except Exception:
                log.exception("ошибка в цикле")

    def tick(self):
        if self.icon is None:  # иконка скрыта — ждём Dota в run()
            return
        hwnd = winutil.find_dota_window()
        if not hwnd:
            self.set_status("Dota 2 не запущена", ICON_WAIT)
            # Окно Dota пропадает на пару секунд при смене режима экрана — не прячемся сразу.
            if self.wait_for_dota and time.time() - self.dota_seen > 15:
                log.info("Dota 2 закрыта — прячу иконку")
                self.icon.stop()
            return
        self.dota_seen = time.time()
        if self.gsi.in_match:
            self.set_status("в матче — пауза", ICON_WAIT)
            return
        if time.time() < self.cooldown_until:
            return
        self.set_status("жду игру")

        flashed = self.flash.is_set()
        self.flash.clear()
        img = self.grab(hwnd)
        hit = detector.find_accept_button(img, self.cfg["detector"]) if img is not None else None

        if hit is None and flashed and self.cfg["focus_on_flash"]:
            # Окно свёрнуто или не снимается в фоне — разворачиваем и смотрим ещё раз.
            winutil.focus(hwnd)
            time.sleep(0.8)
            img = self.grab(hwnd)
            hit = detector.find_accept_button(img, self.cfg["detector"]) if img is not None else None

        if hit:
            self.accept(hwnd, img, hit)

    def accept(self, hwnd, img, hit):
        cx, cy, _ = hit
        log.info("найдена кнопка ПРИНЯТЬ в (%s, %s)", cx, cy)
        if self.cfg["save_debug_screenshots"]:
            self.save_debug(img, hit, "found")

        winutil.focus(hwnd)
        time.sleep(0.3)
        x, y, _, _ = winutil.client_rect_on_screen(hwnd)  # после фокуса окно могло сдвинуться
        winutil.click(x + cx, y + cy)

        time.sleep(1.0)
        img2 = self.grab(hwnd)
        if img2 is not None and detector.find_accept_button(img2, self.cfg["detector"]):
            log.info("кнопка всё ещё видна — жму Enter")
            winutil.focus(hwnd)
            winutil.press_enter()

        self.cooldown_until = time.time() + self.cfg["cooldown_after_accept"]
        self.awaiting_pick = True
        self.set_status("игра принята")
        self.ntfy.send_async("Игра найдена! 🎮", "Матч принят автоматически. Беги к компу!", 5, ["video_game"])

    def run(self, wait_for_dota=False):
        gsi.install_config(self.cfg["gsi_port"])
        self.gsi.start()
        winutil.start_flash_listener(self.on_flash)
        threading.Thread(target=self.loop, name="scanner", daemon=True).start()
        self.wait_for_dota = wait_for_dota

        if not wait_for_dota:
            self.run_icon()
            return
        # Режим автозапуска: без иконки ждём Dota, с Dota показываем трей, закрыли — снова ждём.
        while not self.stop.is_set():
            log.info("жду запуска Dota 2")
            while not self.stop.is_set() and not winutil.find_dota_window():
                self.stop.wait(2)
            if self.stop.is_set():
                break
            log.info("Dota 2 запущена — показываю иконку")
            self.dota_seen = time.time()
            self.run_icon()

    def run_icon(self):
        self.status = "запуск…"
        icon = pystray.Icon(
            "dota2-autoaccept", ICON_ON, "Dota 2 Auto Accept",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _: f"Статус: {self.status}", None, enabled=False),
                pystray.MenuItem("Автопринятие", self.toggle, checked=lambda _: self.enabled, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Тестовый пуш на телефон", self.test_notify),
                pystray.MenuItem(f"Скопировать мой ntfy-топик ({self.cfg['ntfy_topic']})",
                                 lambda *_: copy_to_clipboard(self.cfg["ntfy_topic"])),
                pystray.MenuItem("Скриншот Dota для отладки", self.debug_screenshot),
                pystray.MenuItem("Запускать вместе с Windows (ждать Dota)",
                                 lambda *_: set_autostart(not autostart_enabled()),
                                 checked=lambda _: autostart_enabled()),
                pystray.MenuItem("Открыть папку программы", lambda *_: os.startfile(APP_DIR)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self.quit),
            ),
        )
        log.info("запущено, ntfy-топик: %s", self.cfg["ntfy_topic"])
        self.icon = icon
        icon.run()
        self.icon = None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test-image", help="проверить детектор на скриншоте")
    p.add_argument("--test-notify", action="store_true", help="отправить тестовый пуш")
    p.add_argument("--wait-for-dota", action="store_true", help="сидеть без иконки, пока не запущена Dota")
    p.add_argument("--autostart", choices=["on", "off"], help="включить/выключить запуск вместе с Windows")
    args = p.parse_args()

    setup_logging()
    cfg = load_config()

    if args.test_image:
        img = cv2.imread(args.test_image)
        hit = detector.find_accept_button(img, cfg["detector"])
        print("кнопка найдена:", hit if hit else "нет")
        out = Path(args.test_image).with_suffix(".detected.png")
        cv2.imwrite(str(out), detector.annotate(img, hit, cfg["detector"]))
        print("разметка:", out)
        return
    if args.test_notify:
        ok = notifier.Ntfy(cfg["ntfy_server"], cfg["ntfy_topic"]).send(
            "Dota 2 Auto Accept", "Тест: уведомления работают 👍", 3, ["white_check_mark"])
        print("отправлено" if ok else "ошибка, см. logs/autoaccept.log", "— топик:", cfg["ntfy_topic"])
        return

    if args.autostart:
        set_autostart(args.autostart == "on")
        print("автозапуск:", "включён" if autostart_enabled() else "выключен")
        return

    if not cfg.get("welcome_shown"):
        show_welcome(cfg["ntfy_topic"])
        cfg["welcome_shown"] = True
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    App(cfg).run(wait_for_dota=args.wait_for_dota)


if __name__ == "__main__":
    main()
