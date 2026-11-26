#!/usr/bin/env python3
"""Servicio que mantiene la pantalla del FX360 transmitiendo.

Lee ~/.config/fxlcd/config.json y la recarga en caliente cuando cambia.
Publica su estado en $XDG_RUNTIME_DIR/fxlcd/status.json.
"""
import json
import signal
import sys
import time

import config
import sources
from lcd import LCD, LCDError

# claves cuyo cambio obliga a reconstruir la fuente
CONTENT = ("source", "sequences", "layout", "interval")


class Daemon:
    def __init__(self):
        self.running = True
        self.cfg = None
        self.mtime = None
        self.source = None
        self.lcd = None
        self.cache = {}
        self.status = None
        self.next_try = 0.0

    def set_status(self, state, msg=""):
        if (state, msg) != self.status:
            self.status = (state, msg)
            config.write_status(state, msg)
            print(f"[{state}] {msg}", flush=True)

    def close_lcd(self):
        if self.lcd:
            self.lcd.close()
            self.lcd = None

    def reload(self):
        m = config.mtime()
        if m == self.mtime and self.cfg is not None:
            return
        self.mtime = m
        new = config.load()
        old = self.cfg or {}
        self.cfg = new
        if any(json.dumps(old.get(k), sort_keys=True) != json.dumps(new[k], sort_keys=True)
               for k in CONTENT):
            self.cache.clear()
            try:
                self.source = sources.build(new)
            except (OSError, ValueError) as e:
                self.source = None
                self.set_status("error", str(e))
        if self.lcd:
            if old.get("rotate") != new["rotate"]:
                self.lcd.rotate = new["rotate"]
                self.cache.clear()
            if old.get("brightness") != new["brightness"]:
                self.lcd.brightness(new["brightness"])

    def step(self):
        self.reload()
        if not self.cfg["enabled"]:
            self.close_lcd()
            self.set_status("idle")
            time.sleep(0.3)
            return
        if self.source is None:
            time.sleep(0.5)
            return
        if self.lcd is None:
            if time.monotonic() < self.next_try:
                time.sleep(0.3)
                return
            try:
                self.lcd = LCD(self.cfg["rotate"])
                self.lcd.brightness(self.cfg["brightness"])
                self.cache.clear()
            except LCDError as e:
                self.set_status("no-device", str(e))
                self.next_try = time.monotonic() + 2
                return
        key, img = self.source.current(time.monotonic())
        frame = self.cache.get(key)
        if frame is None:
            if len(self.cache) > 600:
                self.cache.clear()
            frame = self.cache[key] = self.lcd.encode(img)
        try:
            self.lcd.send(frame)
            self.set_status("streaming", sources.describe(self.cfg))
        except OSError as e:  # se desconectó
            self.close_lcd()
            self.set_status("no-device", f"Se perdió la pantalla: {e}")
            self.next_try = time.monotonic() + 2

    def run(self):
        while self.running:
            self.step()
        self.close_lcd()
        self.set_status("stopped")


def main():
    lock = config.device_lock()
    if lock is None:
        sys.exit("Otro proceso (servicio o CLI) ya está usando la pantalla.")
    d = Daemon()

    def stop(*_):
        d.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    d.run()


if __name__ == "__main__":
    main()
