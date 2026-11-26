# fxlcd

Control de la pantalla LCD del AIO **ID-COOLING FX360 LCD** (y FX240 LCD) desde Linux.
El software oficial es solo para Windows.

Dispositivo: USB `2000:3000` (`CMX Systems HOTSPOTEKUSB HID DEMO`), pantalla de 240×240.

## Interfaz gráfica

```bash
./fxlcd-gui.py
```

App GTK4/libadwaita con cuatro secciones:

- **Pantalla**: preview en vivo de lo que muestra el cooler, iniciar/detener, brillo
  (se aplica en vivo), rotación, refresco de los medidores e inicio con la sesión.
- **Biblioteca**: las imágenes y GIFs que agregás (botón *Agregar* o arrastrándolos a la
  ventana) se copian a `~/.local/share/fxlcd/library/`. Tocar una la muestra al instante.
- **Secuencias**: listas con nombre que alternan imágenes, GIFs y los medidores, cada paso
  con su duración, en loop.
- **Diseño**: editor de los medidores. Elementos (indicador en arco, anillo o semicírculo;
  barra; valor grande; reloj; texto) que se mueven arrastrándolos sobre la preview, con
  métrica, etiqueta, color (fijo o automático según la temperatura), tamaño y grosor.
  Fondo de color o imagen de la biblioteca.

Métricas: temperatura, uso y frecuencia de CPU; temperatura, hotspot, uso, consumo y
ventilador de GPU; VRAM; RAM; temperatura del SSD NVMe.

Para que aparezca en el lanzador de aplicaciones:

```bash
sed "s|@DIR@|$PWD|" fxlcd.desktop > ~/.local/share/applications/fxlcd.desktop
```

### Cómo funciona

La interfaz no le habla a la pantalla: edita `~/.config/fxlcd/config.json` y maneja el
servicio de usuario `fxlcd` (`daemon.py`), que es el que transmite y recarga la config en
caliente. Por eso la pantalla **sigue andando al cerrar la ventana**. La interfaz instala
el servicio sola en `~/.config/systemd/user/fxlcd.service` la primera vez que se abre.

```bash
systemctl --user status fxlcd      # ver el estado
journalctl --user -u fxlcd -f      # ver el log
systemctl --user stop fxlcd        # detenerlo
```

## Línea de comandos

Para usarla sin interfaz (con el servicio detenido):

```bash
./fxlcd.py stats                 # medidores, con el diseño guardado
./fxlcd.py image foto.jpg        # imagen fija (se recorta a 240x240)
./fxlcd.py gif animacion.gif     # GIF animado
```

| Opción | Descripción |
| :--- | :--- |
| `--rotate {0,90,180,270}` | Rotación en sentido horario |
| `--brightness 0-100` | Brillo |
| `--interval N` | Segundos entre refrescos en `stats` |
| `--preview out.png` | En `stats`: guarda el render en un PNG sin tocar la pantalla |

Se corta con `Ctrl+C`.

## Requisitos

- Python 3.9+, `python-pillow`, `python-psutil`
- Interfaz: `python-gobject`, `gtk4` y `libadwaita` 1.5 o más nueva (GTK 4.12+)
- Sensores: `k10temp` (CPU AMD) o `coretemp` (Intel), `amdgpu` para la GPU, `nvme` para el SSD.

## Archivos

| Archivo | Qué hace |
| :--- | :--- |
| `lcd.py` | Protocolo USB de la pantalla |
| `metrics.py` | Lectura de sensores |
| `layout.py` | Diseño y dibujo de los medidores |
| `sources.py` | Contenido a mostrar: imagen, GIF, medidores, secuencia |
| `config.py`, `paths.py` | Config, biblioteca y estado compartidos |
| `daemon.py` | Servicio que transmite a la pantalla |
| `fxlcd-gui.py` | Interfaz |
| `fxlcd.py` | CLI |

## Permisos

Crear una regla udev para que tu usuario pueda escribir en la pantalla sin `sudo`:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2000", ATTRS{idProduct}=="3000", GROUP="users", MODE="0660", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/99-fxlcd.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

`uaccess` alcanza en escritorios con systemd-logind (GNOME, KDE). Con `seatd`
(algunos setups de Hyprland/Sway) no aplica, por eso también se da acceso al grupo
`users`. Verificá que tu usuario esté en ese grupo con `id`.

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
