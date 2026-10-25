"""Поиск зелёной кнопки «ПРИНЯТЬ» на снимке окна Dota 2."""
import cv2
import numpy as np

DEFAULTS = {
    # Область поиска в долях окна: [x0, y0, x1, y1] — диалог всегда по центру.
    "roi": [0.2, 0.2, 0.8, 0.85],
    # Зелёный в HSV OpenCV (H: 0..180, S/V: 0..255)
    "hue_min": 35, "hue_max": 85, "sat_min": 90, "val_min": 80,
    # Размер кнопки в долях окна
    "min_width_frac": 0.07, "max_width_frac": 0.40,
    "min_height_frac": 0.025, "max_height_frac": 0.15,
    "min_aspect": 1.8, "max_aspect": 8.0,
    # Насколько контур заполняет свой прямоугольник (кнопка — сплошной прямоугольник)
    "min_fill": 0.6,
}


def find_accept_button(img_bgr, cfg=None):
    """Возвращает (cx, cy, (x, y, w, h)) в координатах снимка или None."""
    c = {**DEFAULTS, **(cfg or {})}
    h, w = img_bgr.shape[:2]
    x0, y0 = int(w * c["roi"][0]), int(h * c["roi"][1])
    x1, y1 = int(w * c["roi"][2]), int(h * c["roi"][3])
    roi = img_bgr[y0:y1, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (c["hue_min"], c["sat_min"], c["val_min"]), (c["hue_max"], 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if not (w * c["min_width_frac"] <= bw <= w * c["max_width_frac"]):
            continue
        if not (h * c["min_height_frac"] <= bh <= h * c["max_height_frac"]):
            continue
        if not (c["min_aspect"] <= bw / bh <= c["max_aspect"]):
            continue
        if cv2.contourArea(cnt) / (bw * bh) < c["min_fill"]:
            continue
        if best is None or bw * bh > best[2] * best[3]:
            best = (bx + x0, by + y0, bw, bh)

    if best is None:
        return None
    bx, by, bw, bh = best
    return bx + bw // 2, by + bh // 2, best


def annotate(img_bgr, hit, cfg=None):
    """Копия снимка с нарисованной областью поиска и найденной кнопкой — для отладки."""
    c = {**DEFAULTS, **(cfg or {})}
    out = img_bgr.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (int(w * c["roi"][0]), int(h * c["roi"][1])),
                  (int(w * c["roi"][2]), int(h * c["roi"][3])), (255, 200, 0), 2)
    if hit:
        x, y, bw, bh = hit[2]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (0, 0, 255), 3)
        cv2.circle(out, (hit[0], hit[1]), 6, (0, 0, 255), -1)
    return out
