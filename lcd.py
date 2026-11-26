"""Protocolo USB de la pantalla del ID-COOLING FX360 LCD (USB 2000:3000).

Ingeniería inversa de github.com/w1n-ror/fx_lcd_software-for-linux:
  frame = "CRT\\0\\0" "DRA\\0\\0" <len BE 2 bytes = 32+jpeg> 0xB1 <19 x 00> <JPEG 240x240>
  enviado en reportes HID de 1024 bytes (report id 0), ~3 ms entre reportes.
  "CRT\\0\\0" "LIG\\0\\0" <0-100> = brillo.  El display necesita el stream continuo.
"""
import glob
import io
import os
import time

from PIL import ImageOps

VID, PID = 0x2000, 0x3000
SIZE = 240
CHUNK = 1024
DELAY = 0.003


class LCDError(Exception):
    pass


def find_hidraw():
    for dev in glob.glob("/sys/class/hidraw/hidraw*"):
        with open(f"{dev}/device/uevent") as f:
            if f"HID_ID=0003:{VID:08X}:{PID:08X}" in f.read():
                return "/dev/" + os.path.basename(dev)
    raise LCDError("No encontré la pantalla (USB 2000:3000). ¿Está conectada?")


def fit(img, size=SIZE):
    """Recorta/escala cualquier imagen a un cuadrado RGB."""
    return ImageOps.fit(img.convert("RGB"), (size, size))


class LCD:
    def __init__(self, rotate=0):
        self.path = find_hidraw()
        try:
            self.fd = os.open(self.path, os.O_WRONLY)
        except PermissionError:
            raise LCDError(f"Sin permiso sobre {self.path}. Instalá la regla udev (ver README).")
        self.rotate = rotate
        self._brightness = None  # se aplica entre frames para no cortar uno a la mitad

    def close(self):
        os.close(self.fd)

    def _report(self, payload):
        os.write(self.fd, b"\x00" + payload.ljust(CHUNK, b"\x00"))

    def brightness(self, pct):
        self._brightness = max(0, min(100, int(pct)))

    def encode(self, img):
        """img de 240x240 (ver fit); aplica rotación y arma el frame."""
        if self.rotate:
            img = img.rotate(-self.rotate)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, subsampling=2)
        jpg = buf.getvalue()
        head = b"CRT\x00\x00DRA\x00\x00" + (len(jpg) + 32).to_bytes(2, "big") + b"\xb1" + b"\x00" * 19
        return head + jpg

    def send(self, frame):
        if self._brightness is not None:
            self._report(b"CRT\x00\x00LIG\x00\x00" + bytes([self._brightness]))
            self._brightness = None
            time.sleep(DELAY)
        for i in range(0, len(frame), CHUNK):
            self._report(frame[i:i + CHUNK])
            time.sleep(DELAY)
