# fxlcd

Control de la pantalla LCD del AIO **ID-COOLING FX360 LCD** (y FX240 LCD) desde Linux.
El software oficial es solo para Windows.

Dispositivo: USB `2000:3000` (`CMX Systems HOTSPOTEKUSB HID DEMO`), pantalla de 240×240.

## Modos

```bash
./fxlcd.py stats                 # hora, temp/uso de CPU y GPU, RAM
./fxlcd.py image foto.jpg        # imagen fija (se recorta a 240x240)
./fxlcd.py gif animacion.gif     # GIF animado
```

| Opción | Descripción |
| :--- | :--- |
| `--rotate {0,90,180,270}` | Rotación en sentido horario |
| `--brightness 0-100` | Brillo (default 100) |
| `--interval N` | Segundos entre refrescos en `stats` (default 1) |
| `--preview out.png` | En `stats`: guarda el render en un PNG sin tocar la pantalla |

Se corta con `Ctrl+C`.

## Requisitos

- Python 3.9+, `python-pillow`, `python-psutil`
- Sensores: `k10temp` (CPU AMD) o `coretemp` (Intel), y `amdgpu` para la GPU.

## Permisos

Crear la regla udev para que el usuario con sesión activa pueda escribir en la pantalla:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2000", ATTRS{idProduct}=="3000", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/99-fxlcd.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Protocolo

Escrituras HID de 1024 bytes (report id `0x00`), con ~3 ms entre cada una.
El display necesita el stream continuo: el frame se reenvía en loop.

```text
43 52 54 00 00   "CRT"
44 52 41 00 00   "DRA"
LL LL            32 + tamaño del JPEG, big-endian
B1               byte mágico
00 * 19          relleno
FF D8 ... FF D9  JPEG baseline 4:2:0, 240x240
```

Brillo: `CRT\0\0` + `LIG\0\0` + un byte de 0 a 100.

El protocolo lo descifró [w1n-ror/fx_lcd_software-for-linux](https://github.com/w1n-ror/fx_lcd_software-for-linux).

## Aviso

No está afiliado a ID-COOLING. Solo manda imágenes a la pantalla; no toca la bomba ni los ventiladores.

## Licencia

Dominio público ([Unlicense](LICENSE)): hacé lo que quieras con el código.
