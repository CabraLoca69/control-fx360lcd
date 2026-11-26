"""Config compartida entre la interfaz y el servicio, biblioteca y estado."""
import copy
import fcntl
import json
import os
import shutil

import layout
import paths

MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
STATS = "stats"  # ítem especial: los medidores

DEFAULTS = {
    "enabled": False,               # si el servicio debe transmitir
    "source": {"kind": "stats"},    # stats | {"kind":"media","item":n} | {"kind":"sequence","name":n}
    "brightness": 100,
    "rotate": 0,
    "interval": 1.0,                # refresco de los medidores (s)
    "sequences": {},                # nombre -> [{"item": n | "stats", "seconds": s}]
    "layout": layout.DEFAULT,
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(paths.CONFIG) as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    tmp = paths.CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, paths.CONFIG)  # atómico: el servicio nunca lee un archivo a medias


def mtime():
    try:
        return os.stat(paths.CONFIG).st_mtime_ns
    except OSError:
        return None


# ---------- biblioteca ----------

def library():
    try:
        names = os.listdir(paths.LIBRARY)
    except OSError:
        return []
    files = [n for n in names if n.lower().endswith(MEDIA_EXT)]
    return sorted(files, key=lambda n: os.path.getmtime(os.path.join(paths.LIBRARY, n)), reverse=True)


def item_path(name):
    return os.path.join(paths.LIBRARY, name)


def add_to_library(src):
    """Copia un archivo a la biblioteca y devuelve su nombre ahí."""
    os.makedirs(paths.LIBRARY, exist_ok=True)
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    name, n = base, 2
    while os.path.exists(item_path(name)):
        name, n = f"{stem}-{n}{ext}", n + 1
    shutil.copy2(src, item_path(name))
    return name


def remove_from_library(cfg, name):
    try:
        os.remove(item_path(name))
    except OSError:
        pass
    for seq in cfg["sequences"].values():
        seq[:] = [s for s in seq if s["item"] != name]
    if cfg["source"] == {"kind": "media", "item": name}:
        cfg["source"] = {"kind": "stats"}
    if cfg["layout"].get("background_image") == name:
        cfg["layout"]["background_image"] = None


# ---------- estado del servicio ----------

def write_status(state, msg=""):
    os.makedirs(paths.RUNTIME, exist_ok=True)
    tmp = paths.STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"state": state, "msg": msg, "pid": os.getpid()}, f)
    os.replace(tmp, paths.STATUS)


def read_status():
    try:
        with open(paths.STATUS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"state": "stopped", "msg": ""}


def device_lock():
    """Lock exclusivo sobre la pantalla (servicio o CLI). None si ya lo tiene otro."""
    os.makedirs(paths.RUNTIME, exist_ok=True)
    fd = os.open(paths.LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None
