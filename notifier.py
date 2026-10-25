"""Отправка пушей на телефон через ntfy (https://ntfy.sh)."""
import json
import logging
import threading
import urllib.request

log = logging.getLogger(__name__)


class Ntfy:
    def __init__(self, server, topic):
        self.server = server.rstrip("/")
        self.topic = topic

    def send(self, title, message, priority=4, tags=None):
        # JSON-публикация, а не заголовки: в HTTP-заголовках нельзя кириллицу.
        body = json.dumps({
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": priority,
            "tags": tags or [],
        }).encode("utf-8")
        req = urllib.request.Request(self.server, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                log.info("ntfy: отправлено (%s) %s", resp.status, title)
                return True
        except Exception as e:
            log.error("ntfy: не удалось отправить: %s", e)
            return False

    def send_async(self, *args, **kwargs):
        threading.Thread(target=self.send, args=args, kwargs=kwargs, daemon=True).start()
