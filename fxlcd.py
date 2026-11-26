#!/usr/bin/env python3
"""Control de la pantalla LCD del ID-COOLING FX360 LCD (USB 2000:3000) en Linux.

Protocolo (ingeniería inversa de github.com/w1n-ror/fx_lcd_software-for-linux):
  frame = "CRT\0\0" "DRA\0\0" <len BE 2 bytes = 32+jpeg> 0xB1 <19 x 00> <JPEG 240x240>
  enviado en reportes HID de 1024 bytes (report id 0), ~3 ms entre reportes.
  "LIG\0\0" <0-100> = brillo.  El display necesita el stream continuo.

Uso:
  fxlcd.py image foto.png
  fxlcd.py gif animacion.gif
  fxlcd.py stats
  opciones: --rotate 0/90/180/270  --brightness 0-100
"""
import argparse
import glob
import io
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence

VID, PID = 0x2000, 0x3000
SIZE = 240
CHUNK = 1024
DELAY = 0.003


def find_hidraw():
    for dev in glob.glob("/sys/class/hidraw/hidraw*"):
        with open(f"{dev}/device/uevent") as f:
            if f"HID_ID=0003:{VID:08X}:{PID:08X}" in f.read():
                return "/dev/" + os.path.basename(dev)
    sys.exit("No encontré la pantalla (USB 2000:3000). ¿Está conectada?")


class LCD:
    def __init__(self, rotate=0):
        path = find_hidraw()
        try:
            self.fd = os.open(path, os.O_WRONLY)
        except PermissionError:
            sys.exit(f"Sin permiso sobre {path}. Instalá la regla udev (ver README) o usá sudo.")
        self.rotate = rotate

    def _report(self, payload):
        os.write(self.fd, b"\x00" + payload.ljust(CHUNK, b"\x00"))

    def brightness(self, pct):
        self._report(b"CRT\x00\x00LIG\x00\x00" + bytes([max(0, min(100, pct))]))

    def encode(self, img):
        img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE))
        if self.rotate:
            img = img.rotate(-self.rotate)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, subsampling=2)
        jpg = buf.getvalue()
        head = b"CRT\x00\x00DRA\x00\x00" + (len(jpg) + 32).to_bytes(2, "big") + b"\xb1" + b"\x00" * 19
        return head + jpg

    def send(self, frame):
        for i in range(0, len(frame), CHUNK):
            self._report(frame[i:i + CHUNK])
            time.sleep(DELAY)


# ---------- modos ----------

def run_image(lcd, path):
    frame = lcd.encode(Image.open(path))
    while True:
        lcd.send(frame)


def run_gif(lcd, path):
    im = Image.open(path)
    frames = [(lcd.encode(f.copy()), f.info.get("duration", 100) / 1000)
              for f in ImageSequence.Iterator(im)]
    print(f"{len(frames)} frames cargados")
    while True:
        for frame, dur in frames:
            t0 = time.monotonic()
            lcd.send(frame)
            # mantener el stream vivo hasta que toque el siguiente frame
            while time.monotonic() - t0 < dur:
                lcd.send(frame)


def read_stats():
    import psutil
    temps = psutil.sensors_temperatures()
    cpu_t = next((s.current for s in temps.get("k10temp", []) if s.label == "Tctl"), None)
    if cpu_t is None and "coretemp" in temps:  # Intel
        cpu_t = temps["coretemp"][0].current
    gpu_t = next((s.current for s in temps.get("amdgpu", []) if s.label == "edge"), None)
    gpu_u = None
    for p in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        with open(p) as f:
            gpu_u = int(f.read())
        break
    return {
        "cpu_t": cpu_t, "cpu_u": psutil.cpu_percent(),
        "gpu_t": gpu_t, "gpu_u": gpu_u,
        "ram": psutil.virtual_memory().percent,
    }


FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"


def font(n):
    try:
        return ImageFont.truetype(FONT, n)
    except OSError:
        return ImageFont.load_default()


def temp_color(t):
    if t is None or t < 60:
        return (0, 200, 255)
    if t < 80:
        return (255, 170, 0)
    return (255, 50, 50)


def gauge(d, cx, cy, r, pct, color, label, value, sub):
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, 135, 405, fill=(45, 45, 55), width=9)
    if pct:
        d.arc(box, 135, 135 + 270 * min(pct, 100) / 100, fill=color, width=9)
    d.text((cx, cy - 4), value, font=font(22), fill="white", anchor="mm")
    d.text((cx, cy + 17), sub, font=font(11), fill=(160, 160, 170), anchor="mm")
    d.text((cx, cy + r + 2), label, font=font(14), fill=color, anchor="mm")


def draw_stats(s):
    img = Image.new("RGB", (SIZE, SIZE), (10, 10, 16))
    d = ImageDraw.Draw(img)
    d.text((SIZE // 2, 22), time.strftime("%H:%M"), font=font(26), fill="white", anchor="mm")
    fmt = lambda t: f"{t:.0f}°C" if t is not None else "--"
    gauge(d, 62, 105, 48, s["cpu_t"], temp_color(s["cpu_t"]), "CPU",
          fmt(s["cpu_t"]), f"{s['cpu_u']:.0f}%")
    gauge(d, 178, 105, 48, s["gpu_t"], temp_color(s["gpu_t"]), "GPU",
          fmt(s["gpu_t"]), f"{s['gpu_u']}%" if s["gpu_u"] is not None else "")
    # barra de RAM
    y = 195
    d.text((20, y), "RAM", font=font(13), fill=(160, 160, 170), anchor="lm")
    d.rounded_rectangle((58, y - 6, 180, y + 6), 6, fill=(45, 45, 55))
    d.rounded_rectangle((58, y - 6, 58 + 122 * s["ram"] / 100, y + 6), 6, fill=(150, 100, 255))
    d.text((222, y), f"{s['ram']:.0f}%", font=font(13), fill="white", anchor="rm")
    return img


def run_stats(lcd, interval):
    import psutil
    psutil.cpu_percent()  # primera llamada inicializa
    last = 0
    frame = None
    while True:
        if time.monotonic() - last >= interval:
            frame = lcd.encode(draw_stats(read_stats()))
            last = time.monotonic()
        lcd.send(frame)


def main():
    ap = argparse.ArgumentParser(description="Pantalla LCD ID-COOLING FX360")
    ap.add_argument("mode", choices=["image", "gif", "stats"])
    ap.add_argument("path", nargs="?", help="imagen o gif")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--brightness", type=int, default=100)
    ap.add_argument("--interval", type=float, default=1.0, help="segundos entre refrescos (stats)")
    ap.add_argument("--preview", help="(stats) guardar el render en este PNG y salir, sin tocar la pantalla")
    a = ap.parse_args()

    if a.mode == "stats" and a.preview:
        draw_stats(read_stats()).save(a.preview)
        return
    if a.mode in ("image", "gif") and not (a.path and os.path.isfile(a.path)):
        ap.error("falta la ruta a un archivo existente")

    lcd = LCD(a.rotate)
    lcd.brightness(a.brightness)
    try:
        {"image": lambda: run_image(lcd, a.path),
         "gif": lambda: run_gif(lcd, a.path),
         "stats": lambda: run_stats(lcd, a.interval)}[a.mode]()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
