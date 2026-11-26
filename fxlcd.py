#!/usr/bin/env python3
"""CLI para la pantalla del ID-COOLING FX360 LCD.

  fxlcd.py stats                  medidores (con el diseño guardado en la interfaz)
  fxlcd.py image foto.png         imagen fija
  fxlcd.py gif animacion.gif      GIF animado
  opciones: --rotate 0/90/180/270  --brightness 0-100  --interval s

Si el servicio está transmitiendo, detenelo antes (systemctl --user stop fxlcd).
"""
import argparse
import os
import sys
import time

import config
import layout
import metrics
import sources
from lcd import LCD, LCDError


def main():
    ap = argparse.ArgumentParser(description="Pantalla LCD ID-COOLING FX360")
    ap.add_argument("mode", choices=["image", "gif", "stats"])
    ap.add_argument("path", nargs="?", help="imagen o gif")
    ap.add_argument("--rotate", type=int, default=None, choices=[0, 90, 180, 270])
    ap.add_argument("--brightness", type=int, default=None)
    ap.add_argument("--interval", type=float, default=None, help="segundos entre refrescos (stats)")
    ap.add_argument("--preview", help="(stats) guardar el render en este PNG y salir, sin tocar la pantalla")
    a = ap.parse_args()
    cfg = config.load()

    if a.mode == "stats" and a.preview:
        layout.render(cfg["layout"], metrics.read())[0].save(a.preview)
        return
    if a.mode == "stats":
        src = sources.Stats(cfg["layout"], a.interval or cfg["interval"])
    elif a.path and os.path.isfile(a.path):
        src = sources.load_media(a.path)
    else:
        ap.error("falta la ruta a un archivo existente")

    if config.device_lock() is None:
        sys.exit("El servicio está usando la pantalla. Detenelo con: systemctl --user stop fxlcd")
    try:
        lcd = LCD(cfg["rotate"] if a.rotate is None else a.rotate)
    except LCDError as e:
        sys.exit(str(e))
    lcd.brightness(cfg["brightness"] if a.brightness is None else a.brightness)
    cache = {}
    try:
        while True:
            key, img = src.current(time.monotonic())
            if key not in cache:
                if len(cache) > 600:  # los medidores generan claves nuevas siempre
                    cache.clear()
                cache[key] = lcd.encode(img)
            lcd.send(cache[key])
    except KeyboardInterrupt:
        pass
    finally:
        lcd.close()


if __name__ == "__main__":
    main()
