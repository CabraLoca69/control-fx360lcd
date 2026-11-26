"""Fuentes de contenido. Cada una responde current(now) -> (clave, imagen 240x240).

La clave cambia sólo cuando cambia la imagen, así el que consume puede cachear
el JPEG (servicio) o la textura (interfaz).
"""
import itertools

from PIL import Image, ImageSequence

import config
import layout
import metrics
from lcd import fit

_ids = itertools.count()


class Static:
    def __init__(self, img):
        self.img, self.key = img, ("s", next(_ids))

    def reset(self, now):
        pass

    def current(self, now):
        return self.key, self.img


class Animated:
    def __init__(self, frames):  # [(img, segundos)]
        self.frames = frames
        self.total = sum(d for _, d in frames) or 1
        self.id = next(_ids)
        self.t0 = None

    def reset(self, now):
        self.t0 = now

    def current(self, now):
        if self.t0 is None:
            self.t0 = now
        e = (now - self.t0) % self.total
        for i, (img, d) in enumerate(self.frames):
            if e < d:
                return ("a", self.id, i), img
            e -= d
        return ("a", self.id, len(self.frames) - 1), self.frames[-1][0]


class Stats:
    def __init__(self, lay, interval):
        self.layout, self.interval = lay, max(0.2, interval)
        self.id, self.n, self.last, self.img = next(_ids), 0, None, None

    def reset(self, now):
        pass

    def current(self, now):
        if self.last is None or now - self.last >= self.interval:
            self.img, _ = layout.render(self.layout, metrics.read())
            self.n, self.last = self.n + 1, now
        return ("t", self.id, self.n), self.img


class Sequence:
    def __init__(self, steps):  # [(fuente, segundos)]
        self.steps = steps
        self.total = sum(s for _, s in steps)
        self.t0, self.idx = None, None

    def reset(self, now):
        self.t0, self.idx = now, None

    def current(self, now):
        if self.t0 is None:
            self.t0 = now
        e = (now - self.t0) % self.total
        for i, (src, secs) in enumerate(self.steps):
            if e < secs or i == len(self.steps) - 1:
                if i != self.idx:
                    self.idx = i
                    src.reset(now)  # cada paso arranca desde el principio
                return src.current(now)
            e -= secs


def load_media(path):
    im = Image.open(path)
    if getattr(im, "is_animated", False):
        frames = [(fit(f.copy()), max(0.02, f.info.get("duration", 100) / 1000))
                  for f in ImageSequence.Iterator(im)]
        return Animated(frames)
    return Static(fit(im))


def item_source(item, cfg):
    if item == config.STATS:
        return Stats(cfg["layout"], cfg["interval"])
    try:
        return load_media(config.item_path(item))
    except FileNotFoundError:
        raise ValueError(f"«{item}» ya no está en la biblioteca")
    except OSError as e:
        raise ValueError(f"No pude abrir «{item}»: {e}")


def build(cfg):
    """Fuente para la config actual. Lanza ValueError/OSError con un mensaje legible."""
    src = cfg["source"]
    kind = src.get("kind")
    if kind == "stats":
        return Stats(cfg["layout"], cfg["interval"])
    if kind == "media":
        return item_source(src["item"], cfg)
    if kind == "sequence":
        steps = cfg["sequences"].get(src.get("name"))
        if not steps:
            raise ValueError(f"La secuencia «{src.get('name')}» está vacía")
        return Sequence([(item_source(s["item"], cfg), max(1, s["seconds"])) for s in steps])
    raise ValueError(f"Fuente desconocida: {src}")


def describe(cfg):
    src = cfg["source"]
    if src.get("kind") == "media":
        return src["item"]
    if src.get("kind") == "sequence":
        return f"Secuencia «{src.get('name')}»"
    return "Medidores"
