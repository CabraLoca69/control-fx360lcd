"""Diseño personalizable de los medidores.

Un layout es un dict serializable:
  {"background": "#rrggbb", "background_image": <nombre en biblioteca> | None,
   "widgets": [ {"type": ..., "x": .., "y": .., ...}, ... ]}
Coordenadas en píxeles de la pantalla (240x240); (x, y) es el centro del widget.
"""
import copy
import os
import time
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

import metrics
import paths
from lcd import SIZE, fit

TYPES = {
    "gauge": "Indicador",
    "bar": "Barra",
    "value": "Valor",
    "clock": "Reloj",
    "label": "Texto",
}
GAUGE_SHAPES = {"arc": "Arco", "ring": "Anillo", "semi": "Semicírculo"}
BAR_SHAPES = {"round": "Redondeada", "square": "Recta"}
CLOCK_FORMATS = {"%H:%M": "24 h", "%H:%M:%S": "24 h con segundos",
                 "%I:%M %p": "12 h", "%d/%m": "Fecha", "%a %d": "Día"}

ACCENT = (0, 200, 255)
TRACK = (45, 45, 55)
DIM = (160, 160, 170)
WHITE = (255, 255, 255)

DEFAULT = {
    "background": "#0a0a10",
    "background_image": None,
    "widgets": [
        {"type": "clock", "x": 120, "y": 22, "size": 26, "format": "%H:%M", "color": "#ffffff"},
        {"type": "gauge", "x": 62, "y": 105, "size": 48, "thickness": 9, "shape": "arc",
         "metric": "cpu_temp", "sub": "cpu_usage", "label": "CPU", "color": "auto"},
        {"type": "gauge", "x": 178, "y": 105, "size": 48, "thickness": 9, "shape": "arc",
         "metric": "gpu_temp", "sub": "gpu_usage", "label": "GPU", "color": "auto"},
        {"type": "bar", "x": 119, "y": 195, "size": 122, "thickness": 12, "shape": "round",
         "metric": "ram", "label": "RAM", "color": "#9664ff"},
    ],
}

NEW = {
    "gauge": {"type": "gauge", "size": 40, "thickness": 8, "shape": "arc",
              "metric": "cpu_temp", "sub": None, "label": "CPU", "color": "auto"},
    "bar": {"type": "bar", "size": 120, "thickness": 12, "shape": "round",
            "metric": "ram", "label": "RAM", "color": "#9664ff"},
    "value": {"type": "value", "size": 32, "metric": "cpu_temp", "label": "CPU", "color": "auto"},
    "clock": {"type": "clock", "size": 26, "format": "%H:%M", "color": "#ffffff"},
    "label": {"type": "label", "size": 18, "text": "Hola", "color": "#ffffff"},
}


def default():
    return copy.deepcopy(DEFAULT)


def new_widget(kind, x=120, y=120):
    return {**copy.deepcopy(NEW[kind]), "x": x, "y": y}


def describe(w):
    t = TYPES.get(w["type"], w["type"])
    if w["type"] == "label":
        return f"{t} · {w.get('text', '')}"
    if w["type"] == "clock":
        return f"{t} · {CLOCK_FORMATS.get(w.get('format'), w.get('format'))}"
    return f"{t} · {metrics.name(w.get('metric'))}"


# ---------- dibujo ----------

_FONTS = ["/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


@lru_cache(maxsize=256)
def font(px):
    px = max(1, int(round(px)))
    for f in _FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    return ImageFont.load_default(px)


def hex2rgb(h, fallback=WHITE):
    try:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback


def temp_color(t):
    if t is None or t < 60:
        return (0, 200, 255)
    if t < 80:
        return (255, 170, 0)
    return (255, 50, 50)


def color_of(w, val):
    c = w.get("color", "auto")
    if c == "auto":
        return temp_color(val) if metrics.is_temp(w.get("metric")) else ACCENT
    return hex2rgb(c)


def _union(*boxes):
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _text(d, xy, s, px, fill, anchor="mm"):
    if not s:
        return None
    f = font(px)
    d.text(xy, s, font=f, fill=fill, anchor=anchor)
    return d.textbbox(xy, s, font=f, anchor=anchor)


def _gauge(d, w, v, k):
    x, y = w["x"] * k, w["y"] * k
    r = w.get("size", 48) * k
    t = max(1, int(w.get("thickness", 9) * k))
    shape = w.get("shape", "arc")
    start, sweep = {"arc": (135, 270), "ring": (-90, 360), "semi": (180, 180)}.get(shape, (135, 270))
    metric = w.get("metric")
    val = v.get(metric)
    col = color_of(w, val)
    box = (x - r, y - r, x + r, y + r)
    d.arc(box, start, start + sweep, fill=TRACK, width=t)
    if val:
        frac = max(0.0, min(1.0, val / metrics.maximum(metric)))
        if frac > 0:
            d.arc(box, start, start + sweep * frac, fill=col, width=t)
    if shape == "semi":
        vy, sy, ly = y - 0.38 * r, y - 0.08 * r, y + 0.22 * r
        frame = (x - r, y - r, x + r, y)
    else:
        vy, sy = y - 0.08 * r, y + 0.35 * r
        ly = y + r + (0.04 * r if shape == "arc" else 0.32 * r)
        frame = box
    b1 = _text(d, (x, vy), metrics.fmt(metric, val), 0.46 * r, WHITE)
    sub = w.get("sub")
    b2 = _text(d, (x, sy), metrics.fmt(sub, v.get(sub)), 0.23 * r, DIM) if sub else None
    b3 = _text(d, (x, ly), w.get("label", ""), 0.29 * r, col)
    return _union(frame, b1, b2, b3)


def _bar(d, w, v, k):
    x, y = w["x"] * k, w["y"] * k
    bw, h = w.get("size", 122) * k, w.get("thickness", 12) * k
    x0, x1, y0, y1 = x - bw / 2, x + bw / 2, y - h / 2, y + h / 2
    rad = h / 2 if w.get("shape", "round") == "round" else 0
    metric = w.get("metric")
    val = v.get(metric)
    col = color_of(w, val)
    d.rounded_rectangle((x0, y0, x1, y1), rad, fill=TRACK)
    if val:
        frac = max(0.0, min(1.0, val / metrics.maximum(metric)))
        if frac > 0:
            d.rounded_rectangle((x0, y0, max(x0 + 2 * rad + 1, x0 + bw * frac), y1), rad, fill=col)
    px = max(h * 1.05, 9 * k)
    b1 = _text(d, (x0 - 6 * k, y), w.get("label", ""), px, DIM, "rm")
    b2 = _text(d, (x1 + 6 * k, y), metrics.fmt(metric, val), px, WHITE, "lm")
    return _union((x0, y0, x1, y1), b1, b2)


def _value(d, w, v, k):
    x, y, s = w["x"] * k, w["y"] * k, w.get("size", 32) * k
    metric = w.get("metric")
    val = v.get(metric)
    b1 = _text(d, (x, y), metrics.fmt(metric, val), s, WHITE)
    b2 = _text(d, (x, y - 0.8 * s), w.get("label", ""), 0.38 * s, color_of(w, val))
    return _union(b1, b2)


def _clock(d, w, v, k):
    c = hex2rgb(w.get("color")) if w.get("color", "auto") != "auto" else WHITE
    return _text(d, (w["x"] * k, w["y"] * k), time.strftime(w.get("format", "%H:%M")),
                 w.get("size", 26) * k, c)


def _label(d, w, v, k):
    c = hex2rgb(w.get("color")) if w.get("color", "auto") != "auto" else WHITE
    return _text(d, (w["x"] * k, w["y"] * k), w.get("text", ""), w.get("size", 18) * k, c)


DRAW = {"gauge": _gauge, "bar": _bar, "value": _value, "clock": _clock, "label": _label}


@lru_cache(maxsize=4)
def _background(name, mtime, px):
    path = os.path.join(paths.LIBRARY, name)
    return fit(Image.open(path), px)


def render(layout, values, out=SIZE, ss=2, selected=None):
    """Devuelve (imagen out x out, cajas de cada widget en coordenadas 240x240)."""
    px = int(out * ss)
    k = px / SIZE
    img = Image.new("RGB", (px, px), hex2rgb(layout.get("background"), (10, 10, 16)))
    bg = layout.get("background_image")
    if bg:
        path = os.path.join(paths.LIBRARY, bg)
        try:
            img.paste(_background(bg, os.path.getmtime(path), px))
        except OSError:
            pass
    d = ImageDraw.Draw(img)
    boxes = []
    for w in layout.get("widgets", []):
        try:
            b = DRAW[w["type"]](d, w, values, k)
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            b = None
        boxes.append(tuple(c / k for c in b) if b else (w.get("x", 0) - 5, w.get("y", 0) - 5,
                                                         w.get("x", 0) + 5, w.get("y", 0) + 5))
    if selected is not None and 0 <= selected < len(boxes):
        p = 4
        b = boxes[selected]
        d.rounded_rectangle(((b[0] - p) * k, (b[1] - p) * k, (b[2] + p) * k, (b[3] + p) * k),
                            radius=5 * k, outline=(53, 132, 228), width=max(1, int(1.5 * k)))
    if px != out:
        img = img.resize((out, out), Image.LANCZOS)
    return img, boxes


def hit(boxes, x, y):
    """Índice del widget bajo (x, y), el de más arriba primero."""
    for i in range(len(boxes) - 1, -1, -1):
        b = boxes[i]
        if b[0] - 3 <= x <= b[2] + 3 and b[1] - 3 <= y <= b[3] + 3:
            return i
    return None
