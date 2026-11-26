"""Rutas de config, biblioteca y estado (XDG)."""
import os

_home = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or f"{_home}/.config", "fxlcd")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
LIBRARY = os.path.join(os.environ.get("XDG_DATA_HOME") or f"{_home}/.local/share", "fxlcd", "library")
RUNTIME = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "fxlcd")
STATUS = os.path.join(RUNTIME, "status.json")
LOCK = os.path.join(RUNTIME, "device.lock")
UNIT = os.path.join(os.environ.get("XDG_CONFIG_HOME") or f"{_home}/.config",
                    "systemd", "user", "fxlcd.service")
HERE = os.path.dirname(os.path.realpath(__file__))
