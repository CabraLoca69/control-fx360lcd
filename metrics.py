"""Lectura de sensores (CPU AMD/Intel, GPU AMD, RAM, NVMe)."""
import glob
import os

import psutil


def _gpu_dir():
    for p in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        return os.path.dirname(p)
    return None


GPU = _gpu_dir()


def _read(path, scale=1.0):
    try:
        with open(path) as f:
            return float(f.read()) * scale
    except (OSError, ValueError, TypeError):
        return None


def _hwmon(name):
    if not GPU:
        return None
    for p in glob.glob(f"{GPU}/hwmon/hwmon*/{name}"):
        return p
    return None


_cap = _read(_hwmon("power1_cap"), 1e-6)

# clave -> (nombre, unidad, máximo de la escala, es temperatura)
METRICS = {
    "cpu_temp":    ("CPU · temperatura", "°C", 100, True),
    "cpu_usage":   ("CPU · uso", "%", 100, False),
    "cpu_freq":    ("CPU · frecuencia", "GHz", 6, False),
    "gpu_temp":    ("GPU · temperatura", "°C", 100, True),
    "gpu_hotspot": ("GPU · hotspot", "°C", 110, True),
    "gpu_usage":   ("GPU · uso", "%", 100, False),
    "gpu_power":   ("GPU · consumo", "W", _cap or 300, False),
    "gpu_fan":     ("GPU · ventilador", "RPM", 3500, False),
    "vram":        ("VRAM · uso", "%", 100, False),
    "ram":         ("RAM · uso", "%", 100, False),
    "disk_temp":   ("SSD · temperatura", "°C", 80, True),
}
KEYS = list(METRICS)


def name(key):
    return METRICS[key][0] if key in METRICS else "—"


def maximum(key):
    return METRICS[key][2]


def is_temp(key):
    return key in METRICS and METRICS[key][3]


def fmt(key, val):
    if val is None or key not in METRICS:
        return "--"
    unit = METRICS[key][1]
    if unit == "GHz":
        return f"{val:.1f}GHz"
    if unit == "RPM":
        return f"{val:.0f}"
    return f"{val:.0f}{unit}"


def _temp(temps, chip, label=None):
    for s in temps.get(chip, []):
        if label is None or s.label == label:
            return s.current
    return None


def read():
    temps = psutil.sensors_temperatures()
    cpu = _temp(temps, "k10temp", "Tctl") or _temp(temps, "coretemp", "Package id 0") \
        or _temp(temps, "coretemp")
    freq = psutil.cpu_freq()
    used = _read(f"{GPU}/mem_info_vram_used") if GPU else None
    total = _read(f"{GPU}/mem_info_vram_total") if GPU else None
    power = _read(_hwmon("power1_average"), 1e-6) or _read(_hwmon("power1_input"), 1e-6)
    return {
        "cpu_temp": cpu,
        "cpu_usage": psutil.cpu_percent(),
        "cpu_freq": freq.current / 1000 if freq else None,
        "gpu_temp": _temp(temps, "amdgpu", "edge"),
        "gpu_hotspot": _temp(temps, "amdgpu", "junction"),
        "gpu_usage": _read(f"{GPU}/gpu_busy_percent") if GPU else None,
        "gpu_power": power,
        "gpu_fan": _read(_hwmon("fan1_input")),
        "vram": used / total * 100 if used is not None and total else None,
        "ram": psutil.virtual_memory().percent,
        "disk_temp": _temp(temps, "nvme", "Composite"),
    }
