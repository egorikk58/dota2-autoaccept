"""Окно «Подключи телефон»: личный топик, QR-код, кнопки копирования и тестового пуша."""
import threading
import tkinter as tk

import qrcode
from PIL import ImageTk

_lock = threading.Lock()


def show(server, topic, on_copy, on_test, block=False):
    """Открывает окно; по умолчанию в отдельном потоке, чтобы не блокировать трей.
    Второе окно поверх первого не откроется."""
    if not _lock.acquire(blocking=False):
        return

    def run():
        try:
            _window(server, topic, on_copy, on_test)
        finally:
            _lock.release()

    if block:
        run()
    else:
        threading.Thread(target=run, name="welcome", daemon=True).start()


def _qr_image(data):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return getattr(img, "get_image", lambda: img._img)().convert("RGB")


def _window(server, topic, on_copy, on_test):
    url = f"{server.rstrip('/')}/{topic}"
    root = tk.Tk()
    root.title("Dota 2 Auto Accept")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frm = tk.Frame(root, padx=20, pady=16)
    frm.pack()
    tk.Label(frm, text="Подключи телефон", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

    steps = (
        "1. Установи приложение ntfy\n"
        "    (App Store или Google Play).\n\n"
        "2. Нажми «+» → Subscribe to topic,\n"
        "    вставь топик ниже, сервер ntfy.sh.\n\n"
        "3. Нажми «Тестовый пуш» —\n"
        "    на телефон должно прийти уведомление.\n\n"
        "QR-код открывает страницу топика:\n"
        "на Android — сразу в приложении ntfy,\n"
        "на iPhone — в браузере, оттуда\n"
        "можно скопировать топик."
    )
    tk.Label(frm, text=steps, justify="left", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="nw", pady=(10, 0))

    photo = ImageTk.PhotoImage(_qr_image(url))
    tk.Label(frm, image=photo).grid(row=1, column=1, padx=(16, 0), pady=(10, 0), sticky="n")

    tk.Label(frm, text="Твой личный топик:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(14, 2))
    entry = tk.Entry(frm, font=("Consolas", 13), width=30, justify="center")
    entry.insert(0, topic)
    entry.configure(state="readonly")
    entry.grid(row=3, column=0, columnspan=2, sticky="we")

    status = tk.StringVar(value="Никому не показывай топик — по нему можно читать твои уведомления.")
    tk.Label(frm, textvariable=status, fg="#666", font=("Segoe UI", 9), wraplength=420, justify="left").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(6, 10))

    def copy():
        on_copy()
        status.set("Топик скопирован в буфер обмена.")

    def test():
        status.set("Отправляю…")
        root.update_idletasks()
        ok = on_test()
        status.set("Отправлено! Проверь телефон." if ok else "Не получилось отправить — проверь интернет.")

    btns = tk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=2, sticky="e")
    tk.Button(btns, text="Копировать топик", command=copy, padx=10).pack(side="left", padx=4)
    tk.Button(btns, text="Тестовый пуш", command=test, padx=10).pack(side="left", padx=4)
    tk.Button(btns, text="Готово", command=root.destroy, padx=16).pack(side="left", padx=4)

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    root.mainloop()
