#!/usr/bin/env python3
"""Interfaz GTK4/libadwaita para la pantalla del ID-COOLING FX360 LCD.

La interfaz no le habla a la pantalla: edita ~/.config/fxlcd/config.json y controla
el servicio de usuario `fxlcd` (daemon.py), que sigue corriendo al cerrar la ventana.
"""
import io
import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config  # noqa: E402
import layout  # noqa: E402
import metrics  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
from lcd import SIZE, fit  # noqa: E402

APP_ID = "io.github.cabraloca69.fxlcd"
SERVICE = "fxlcd.service"
ROTATIONS = [0, 90, 180, 270]
CANVAS = 360
V, H = Gtk.Orientation.VERTICAL, Gtk.Orientation.HORIZONTAL

CSS = """
.lcd {
  border-radius: 28px;
  background: black;
  box-shadow: 0 0 0 6px alpha(currentColor, 0.06), 0 10px 32px alpha(black, 0.45);
  transition: box-shadow 250ms;
}
.lcd.live {
  box-shadow: 0 0 0 3px @accent_bg_color, 0 10px 36px alpha(@accent_bg_color, 0.35);
}
.tile { border-radius: 18px; background: black; transition: box-shadow 200ms; }
.tile.active { box-shadow: 0 0 0 3px @accent_bg_color; }
.thumb { border-radius: 8px; background: black; }
.badge { font-size: 0.75em; font-weight: 800; padding: 2px 7px; border-radius: 6px; }
"""


# ---------- utilidades ----------

def to_texture(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=1)
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


def rgba(h):
    c = Gdk.RGBA()
    c.parse(h if isinstance(h, str) and h.startswith("#") else "#00c8ff")
    return c


def hexcolor(c):
    return "#%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))


def systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def ensure_unit():
    """Instala/actualiza el servicio de usuario apuntando a esta carpeta."""
    with open(os.path.join(paths.HERE, "fxlcd.service")) as f:
        text = f.read().replace("@DIR@", paths.HERE)
    try:
        with open(paths.UNIT) as f:
            if f.read() == text:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(paths.UNIT), exist_ok=True)
    with open(paths.UNIT, "w") as f:
        f.write(text)
    systemctl("daemon-reload")


def clear(box):
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def title_of(item):
    return "Medidores" if item == config.STATS else item


def heading(title, subtitle, *suffix):
    row = Gtk.Box(spacing=12)
    col = Gtk.Box(orientation=V, spacing=4, hexpand=True)
    col.append(Gtk.Label(label=title, css_classes=["title-2"], xalign=0))
    col.append(Gtk.Label(label=subtitle, css_classes=["dim-label"], xalign=0, wrap=True))
    row.append(col)
    for w in suffix:
        row.append(w)
    return row


def pill(label, icon, cls="suggested-action"):
    return Gtk.Button(child=Adw.ButtonContent(label=label, icon_name=icon),
                      css_classes=["pill", cls], valign=Gtk.Align.CENTER)


# ---------- ventana ----------

class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="FX360 LCD", default_width=1000, default_height=720)
        self.set_size_request(360, 480)
        self.cfg = config.load()
        self._save_id = None
        self._sync = False
        self.flip = []
        self.thumbs = {}
        self.lib_items = []
        self.preview_src = self.preview_key = None
        self.preview_tex = {}
        self.sel = None
        self.boxes = []
        self.drag_from = None
        self.elem_rows = []
        self.xy_rows = None
        self.values = metrics.read()

        try:
            ensure_unit()
        except OSError as e:
            print("No pude instalar el servicio:", e, file=sys.stderr)
        self._actions()
        self._build()
        self.rebuild_preview()
        self.rebuild_library()
        self.rebuild_sequences()
        self.rebuild_design()
        self.update_play()
        if self.cfg["enabled"] and not self.service_active():
            systemctl("start", SERVICE)
        self.poll_status()
        GLib.timeout_add(40, self.tick_preview)
        GLib.timeout_add(1500, self.poll_status)
        GLib.timeout_add(1000, self.tick_metrics)

    # ---------- armado ----------

    def _build(self):
        self.toasts = Adw.ToastOverlay()
        self.stack = Adw.ViewStack()
        self.toasts.set_child(self.stack)
        view = Adw.ToolbarView()
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.header = Adw.HeaderBar(title_widget=self.switcher)
        self.narrow_title = Adw.WindowTitle(title="FX360 LCD")
        view.add_top_bar(self.header)
        view.set_content(self.toasts)
        self.switch_bar = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(self.switch_bar)
        self.set_content(view)

        self.stack.add_titled_with_icon(self._page_screen(), "screen", "Pantalla", "video-display-symbolic")
        self.stack.add_titled_with_icon(self._page_library(), "library", "Biblioteca", "folder-pictures-symbolic")
        self.stack.add_titled_with_icon(self._page_sequences(), "sequences", "Secuencias", "view-list-symbolic")
        self.stack.add_titled_with_icon(self._page_design(), "design", "Diseño", "applications-graphics-symbolic")
        self.stack.connect("notify::visible-child-name", self.on_page)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.connect("apply", lambda *_: self.set_narrow(True))
        bp.connect("unapply", lambda *_: self.set_narrow(False))
        self.add_breakpoint(bp)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)
        self.connect("close-request", self.on_close)

    def set_narrow(self, narrow):
        self.header.set_title_widget(self.narrow_title if narrow else self.switcher)
        self.switch_bar.set_reveal(narrow)
        for b in self.flip:
            b.set_orientation(V if narrow else H)

    def _page(self, child):
        clamp = Adw.Clamp(maximum_size=1100, child=child)
        return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp)

    def _flipbox(self):
        b = Gtk.Box(spacing=36, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        self.flip.append(b)
        return b

    def _actions(self):
        for name, ptype, cb in [("show-item", "s", self.show_item),
                                ("lib-delete", "s", self.ask_delete_item),
                                ("lib-bg", "s", self.use_as_background),
                                ("seq-add", "(ss)", self.add_step),
                                ("lay-add", "s", self.add_widget)]:
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(ptype))
            a.connect("activate", lambda _a, p, cb=cb: cb(p.unpack()))
            self.add_action(a)

    def toast(self, msg, button=None, action=None, target=None):
        t = Adw.Toast(title=msg, timeout=3)
        if button:
            t.set_button_label(button)
            t.set_action_name(action)
            t.set_action_target_value(GLib.Variant.new_string(target))
        self.toasts.add_toast(t)

    def confirm(self, heading_, body, label, on_yes):
        d = Adw.AlertDialog(heading=heading_, body=body)
        d.add_response("cancel", "Cancelar")
        d.add_response("ok", label)
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: on_yes() if r == "ok" else None)
        d.present(self)

    # ---------- config / servicio ----------

    def save_soon(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(250, self.save_now)

    def save_now(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = None
        config.save(self.cfg)
        return False

    def service_active(self):
        return systemctl("is-active", "--quiet", SERVICE).returncode == 0

    def service_enabled(self):
        return systemctl("is-enabled", SERVICE).stdout.strip() == "enabled"

    def start_streaming(self):
        self.cfg["enabled"] = True
        self.save_now()
        try:
            ensure_unit()
        except OSError as e:
            self.toast(f"No pude instalar el servicio: {e}")
        r = systemctl("start", SERVICE)
        if r.returncode:
            self.toast(f"No pude iniciar el servicio: {r.stderr.strip()}")
        self.source_changed()

    def source_changed(self):
        self.rebuild_preview()
        self.update_play()
        self.rebuild_library()
        self.rebuild_sequences()
        self.poll_status()

    # ---------- página: Pantalla ----------

    def _page_screen(self):
        body = self._flipbox()
        left = Gtk.Box(orientation=V, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.preview = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=False,
                                   halign=Gtk.Align.CENTER, css_classes=["lcd"])
        self.preview.set_size_request(SIZE, SIZE)
        self.preview.set_overflow(Gtk.Overflow.HIDDEN)
        left.append(self.preview)
        self.now_label = Gtk.Label(css_classes=["title-4"], margin_top=8,
                                   ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=26)
        left.append(self.now_label)
        self.status_label = Gtk.Label(css_classes=["dim-label", "caption"], wrap=True,
                                      max_width_chars=34, justify=Gtk.Justification.CENTER)
        left.append(self.status_label)
        self.play = Gtk.Button(css_classes=["pill"], halign=Gtk.Align.CENTER, margin_top=6)
        self.play.connect("clicked", self.on_play)
        left.append(self.play)
        body.append(left)

        right = Gtk.Box(orientation=V, spacing=24, hexpand=True, valign=Gtk.Align.CENTER)
        g = Adw.PreferencesGroup(title="Pantalla")
        bright_row = Adw.ActionRow(title="Brillo")
        self.bright = Gtk.Scale.new_with_range(H, 0, 100, 5)
        self.bright.set_hexpand(True)
        self.bright.set_size_request(160, -1)
        self.bright.set_draw_value(True)
        self.bright.set_value_pos(Gtk.PositionType.RIGHT)
        self.bright.set_format_value_func(lambda _s, v: f"{v:.0f}%")
        self.bright.set_value(self.cfg["brightness"])
        self.bright.connect("value-changed", self.on_brightness)
        bright_row.add_suffix(self.bright)
        g.add(bright_row)
        rot = Adw.ComboRow(title="Rotación", subtitle="Si la imagen sale girada en el cooler",
                           model=Gtk.StringList.new([f"{r}°" for r in ROTATIONS]))
        rot.set_selected(ROTATIONS.index(self.cfg["rotate"]) if self.cfg["rotate"] in ROTATIONS else 0)
        rot.connect("notify::selected", self.on_rotate)
        g.add(rot)
        interval = Adw.SpinRow.new_with_range(0.5, 10, 0.5)
        interval.set_title("Refresco de medidores")
        interval.set_subtitle("Segundos entre actualizaciones")
        interval.set_value(self.cfg["interval"])
        interval.connect("notify::value", self.on_interval)
        g.add(interval)
        right.append(g)

        g2 = Adw.PreferencesGroup(title="Segundo plano",
                                  description="La pantalla sigue andando aunque cierres esta ventana.")
        self.autostart = Adw.SwitchRow(title="Iniciar con la sesión",
                                       subtitle="Al entrar a la PC retoma lo último que mostraba",
                                       active=self.service_enabled())
        self.autostart.connect("notify::active", self.on_autostart)
        g2.add(self.autostart)
        right.append(g2)
        body.append(right)
        return self._page(body)

    def rebuild_preview(self):
        self.preview_tex = {}
        self.preview_key = None
        try:
            self.preview_src = sources.build(self.cfg)
            self.now_label.set_label(sources.describe(self.cfg))
        except (OSError, ValueError) as e:
            self.preview_src = None
            self.preview.set_paintable(None)
            self.now_label.set_label(str(e))

    def tick_preview(self):
        if self.preview_src is None or self.stack.get_visible_child_name() != "screen":
            return True
        key, img = self.preview_src.current(time.monotonic())
        if key != self.preview_key:
            tex = self.preview_tex.get(key)
            if tex is None:
                tex = to_texture(img)
                if key[0] != "t":  # los medidores cambian siempre: no se cachean
                    if len(self.preview_tex) > 600:
                        self.preview_tex.clear()
                    self.preview_tex[key] = tex
            self.preview.set_paintable(tex)
            self.preview_key = key
        return True

    def poll_status(self):
        st = config.read_status()
        active = self.service_active()
        state = st.get("state") if active else "stopped"
        if not self.cfg["enabled"]:
            text, short = "Detenido: el cooler muestra su pantalla por defecto", "Detenido"
        elif state == "streaming":
            text = short = "● En la pantalla"
        elif state == "no-device":
            text, short = "Pantalla no encontrada, reintentando…", "Pantalla no encontrada"
        elif state == "error":
            text, short = st.get("msg", "Error"), "Error"
        elif not active:
            text, short = "El servicio no está corriendo", "Servicio detenido"
        else:
            text = short = "Iniciando…"
        self.status_label.set_label(text)
        self.narrow_title.set_subtitle(short)
        if self.cfg["enabled"] and state == "streaming":
            self.preview.add_css_class("live")
        else:
            self.preview.remove_css_class("live")
        return True

    def update_play(self):
        on = self.cfg["enabled"]
        self.play.set_label("Detener" if on else "Mostrar en la pantalla")
        self.play.set_css_classes(["pill", "destructive-action" if on else "suggested-action"])

    def on_play(self, _btn):
        if self.cfg["enabled"]:
            self.cfg["enabled"] = False
            self.save_now()
            self.source_changed()
        else:
            self.start_streaming()

    def on_brightness(self, scale):
        self.cfg["brightness"] = int(scale.get_value())
        self.save_soon()  # el servicio lo aplica en vivo

    def on_rotate(self, row, _p):
        self.cfg["rotate"] = ROTATIONS[row.get_selected()]
        self.save_soon()

    def on_interval(self, row, _p):
        self.cfg["interval"] = row.get_value()
        self.save_soon()
        self.rebuild_preview()

    def on_autostart(self, row, _p):
        want = row.get_active()
        if want == self.service_enabled():
            return
        try:
            ensure_unit()
        except OSError:
            pass
        r = systemctl("enable" if want else "disable", SERVICE)
        if r.returncode:
            self.toast(f"No pude cambiarlo: {r.stderr.strip()}")
            row.set_active(not want)

    # ---------- página: Biblioteca ----------

    def _page_library(self):
        box = Gtk.Box(orientation=V, spacing=24, margin_top=24, margin_bottom=24,
                      margin_start=24, margin_end=24)
        add = pill("Agregar", "list-add-symbolic")
        add.connect("clicked", self.on_add_files)
        box.append(heading("Biblioteca", "Tocá una para mostrarla en el cooler. "
                           "También podés arrastrar imágenes o GIFs a la ventana.", add))
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=2, max_children_per_line=6,
                                row_spacing=18, column_spacing=18, valign=Gtk.Align.START)
        self.flow.connect("child-activated", self.on_tile)
        box.append(self.flow)
        return self._page(box)

    def thumb(self, item):
        """(textura, es_animado) de un ítem, cacheado por fecha de modificación."""
        if item == config.STATS:
            return to_texture(layout.render(self.cfg["layout"], self.values)[0]), False
        path = config.item_path(item)
        try:
            key = (item, os.path.getmtime(path))
            if key not in self.thumbs:
                im = Image.open(path)
                self.thumbs[key] = (to_texture(fit(im, 256)), getattr(im, "is_animated", False))
            return self.thumbs[key]
        except OSError:
            return None, False

    def _items_menu(self, seq):
        m = Gio.Menu()
        for item in [config.STATS] + config.library():
            it = Gio.MenuItem.new(title_of(item), None)
            it.set_action_and_target_value("win.seq-add", GLib.Variant("(ss)", (seq, item)))
            m.append_item(it)
        return m

    def _tile(self, item):
        src = self.cfg["source"]
        active = (src.get("kind") == "stats" and item == config.STATS) or \
                 (src.get("kind") == "media" and src.get("item") == item)
        tex, animated = self.thumb(item)
        v = Gtk.Box(orientation=V, spacing=8, halign=Gtk.Align.CENTER)
        ov = Gtk.Overlay(halign=Gtk.Align.CENTER)
        pic = Gtk.Image(paintable=tex, pixel_size=148, css_classes=["tile"])
        pic.set_overflow(Gtk.Overflow.HIDDEN)
        if active:
            pic.add_css_class("active")
        ov.set_child(pic)
        if animated:
            ov.add_overlay(Gtk.Label(label="GIF", css_classes=["badge", "osd"], halign=Gtk.Align.START,
                                     valign=Gtk.Align.END, margin_start=8, margin_bottom=8))
        menu = Gio.Menu()
        seqs = Gio.Menu()
        for name in self.cfg["sequences"]:
            it = Gio.MenuItem.new(name, None)
            it.set_action_and_target_value("win.seq-add", GLib.Variant("(ss)", (name, item)))
            seqs.append_item(it)
        if seqs.get_n_items():
            menu.append_submenu("Agregar a secuencia", seqs)
        if item != config.STATS:
            for label, action in [("Usar de fondo en los medidores", "win.lib-bg"),
                                  ("Eliminar", "win.lib-delete")]:
                it = Gio.MenuItem.new(label, None)
                it.set_action_and_target_value(action, GLib.Variant.new_string(item))
                menu.append_item(it)
        if menu.get_n_items():
            ov.add_overlay(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                          css_classes=["osd", "circular"], halign=Gtk.Align.END,
                                          valign=Gtk.Align.START, margin_top=6, margin_end=6))
        v.append(ov)
        v.append(Gtk.Label(label=title_of(item), css_classes=["caption"],
                           ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=16))
        return v

    def rebuild_library(self):
        self.flow.remove_all()
        self.lib_items = [config.STATS] + config.library()
        for item in self.lib_items:
            self.flow.append(self._tile(item))

    def on_tile(self, _flow, child):
        self.show_item(self.lib_items[child.get_index()])

    def show_item(self, item):
        self.cfg["source"] = {"kind": "stats"} if item == config.STATS else {"kind": "media", "item": item}
        self.start_streaming()
        self.toast(f"Mostrando {title_of(item)}")

    def on_add_files(self, _btn):
        filt = Gtk.FileFilter(name="Imágenes y GIFs")
        filt.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dlg = Gtk.FileDialog(title="Agregar a la biblioteca", filters=filters, default_filter=filt)
        dlg.open_multiple(self, None, self.on_files_picked)

    def on_files_picked(self, dlg, res):
        try:
            files = dlg.open_multiple_finish(res)
        except GLib.Error:
            return  # cancelado
        self.add_files([files.get_item(i).get_path() for i in range(files.get_n_items())])

    def on_drop(self, _target, value, _x, _y):
        self.add_files([f.get_path() for f in value.get_files()])
        return True

    def add_files(self, paths_):
        added = []
        for p in paths_:
            if p and p.lower().endswith(config.MEDIA_EXT):
                try:
                    added.append(config.add_to_library(p))
                except OSError as e:
                    self.toast(f"No pude copiar {os.path.basename(p)}: {e}")
        if not added:
            self.toast("Sólo se pueden agregar imágenes (PNG, JPG, WEBP, BMP) o GIFs")
            return
        self.rebuild_library()
        self.rebuild_sequences()
        self.rebuild_design()
        self.stack.set_visible_child_name("library")
        if len(added) == 1:
            self.toast(f"Se agregó {added[0]}", "Mostrar", "win.show-item", added[0])
        else:
            self.toast(f"Se agregaron {len(added)} archivos")

    def ask_delete_item(self, item):
        def do():
            config.remove_from_library(self.cfg, item)
            self.save_now()
            self.rebuild_design()
            self.source_changed()
        self.confirm(f"¿Eliminar «{item}»?",
                     "Se borra de la biblioteca y de las secuencias que lo usen.", "Eliminar", do)

    def use_as_background(self, item):
        self.cfg["layout"]["background_image"] = item
        self.save_now()
        self.rebuild_design()
        self.rebuild_preview()
        self.toast(f"{item} es ahora el fondo de los medidores")

    # ---------- página: Secuencias ----------

    def _page_sequences(self):
        box = Gtk.Box(orientation=V, spacing=24, margin_top=24, margin_bottom=24,
                      margin_start=24, margin_end=24)
        new = pill("Nueva", "list-add-symbolic")
        new.connect("clicked", self.on_new_sequence)
        box.append(heading("Secuencias", "Alterná imágenes, GIFs y medidores, "
                           "cada uno con su duración. Se repiten en loop.", new))
        self.seq_box = Gtk.Box(orientation=V, spacing=24)
        box.append(self.seq_box)
        return self._page(box)

    def _seq_desc(self, name):
        steps = self.cfg["sequences"].get(name, [])
        src = self.cfg["source"]
        playing = self.cfg["enabled"] and src.get("kind") == "sequence" and src.get("name") == name
        total = sum(s["seconds"] for s in steps)
        n = len(steps)
        return ("● En la pantalla · " if playing else "") + \
            f"{n} paso{'s' if n != 1 else ''} · {total} s por vuelta"

    def rebuild_sequences(self):
        clear(self.seq_box)
        seqs = self.cfg["sequences"]
        if not seqs:
            self.seq_box.append(Adw.StatusPage(icon_name="view-list-symbolic",
                                               title="Todavía no hay secuencias",
                                               description="Creá una con «Nueva» y agregale pasos."))
            return
        for name, steps in seqs.items():
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(name), description=self._seq_desc(name))
            hdr = Gtk.Box(spacing=4)
            play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Mostrar en la pantalla",
                              css_classes=["flat"], valign=Gtk.Align.CENTER)
            play.connect("clicked", lambda _b, n=name: self.play_sequence(n))
            add = Gtk.MenuButton(icon_name="list-add-symbolic", tooltip_text="Agregar paso",
                                 css_classes=["flat"], valign=Gtk.Align.CENTER, menu_model=self._items_menu(name))
            dele = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Eliminar secuencia",
                              css_classes=["flat"], valign=Gtk.Align.CENTER)
            dele.connect("clicked", lambda _b, n=name: self.ask_delete_sequence(n))
            for w in (play, add, dele):
                hdr.append(w)
            g.set_header_suffix(hdr)
            if not steps:
                g.add(Adw.ActionRow(title="Sin pasos", subtitle="Usá + para agregar imágenes, GIFs o los medidores"))
            for i, step in enumerate(steps):
                g.add(self._step_row(name, g, i, step, len(steps)))
            self.seq_box.append(g)

    def _step_row(self, name, group, i, step, n):
        row = Adw.ActionRow(title=GLib.markup_escape_text(title_of(step["item"])), title_lines=1)
        pic = Gtk.Image(paintable=self.thumb(step["item"])[0], pixel_size=40,
                        css_classes=["thumb"], valign=Gtk.Align.CENTER)
        pic.set_overflow(Gtk.Overflow.HIDDEN)
        row.add_prefix(pic)
        spin = Gtk.SpinButton.new_with_range(1, 3600, 1)
        spin.set_value(step["seconds"])
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_tooltip_text("Duración en segundos")

        def on_secs(s):
            step["seconds"] = s.get_value_as_int()
            group.set_description(self._seq_desc(name))
            self.save_soon()
            self.rebuild_preview()
        spin.connect("value-changed", on_secs)
        row.add_suffix(spin)
        row.add_suffix(Gtk.Label(label="s", css_classes=["dim-label"]))
        for icon, tip, delta, ok in [("go-up-symbolic", "Subir", -1, i > 0),
                                     ("go-down-symbolic", "Bajar", 1, i < n - 1)]:
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["flat", "circular"],
                           valign=Gtk.Align.CENTER, sensitive=ok)
            b.connect("clicked", lambda _b, d=delta: self.move_step(name, i, d))
            row.add_suffix(b)
        rm = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Quitar",
                        css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
        rm.connect("clicked", lambda _b: self.remove_step(name, i))
        row.add_suffix(rm)
        return row

    def seq_changed(self):
        self.save_now()
        self.rebuild_sequences()
        self.rebuild_library()  # los menús de "Agregar a secuencia"
        self.rebuild_preview()

    def on_new_sequence(self, _btn):
        d = Adw.AlertDialog(heading="Nueva secuencia")
        entry = Gtk.Entry(placeholder_text="Nombre", activates_default=True)
        d.set_extra_child(entry)
        d.add_response("cancel", "Cancelar")
        d.add_response("create", "Crear")
        d.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("create")
        d.set_close_response("cancel")

        def on_response(_d, r):
            if r != "create":
                return
            name = entry.get_text().strip() or f"Secuencia {len(self.cfg['sequences']) + 1}"
            if name in self.cfg["sequences"]:
                self.toast(f"Ya existe «{name}»")
                return
            self.cfg["sequences"][name] = []
            self.seq_changed()
        d.connect("response", on_response)
        d.present(self)

    def add_step(self, pair):
        name, item = pair
        self.cfg["sequences"].setdefault(name, []).append({"item": item, "seconds": 10})
        self.seq_changed()
        self.toast(f"{title_of(item)} agregado a «{name}»")

    def move_step(self, name, i, delta):
        steps = self.cfg["sequences"][name]
        j = i + delta
        if 0 <= j < len(steps):
            steps[i], steps[j] = steps[j], steps[i]
            self.seq_changed()

    def remove_step(self, name, i):
        del self.cfg["sequences"][name][i]
        self.seq_changed()

    def play_sequence(self, name):
        if not self.cfg["sequences"].get(name):
            self.toast("Agregale pasos primero")
            return
        self.cfg["source"] = {"kind": "sequence", "name": name}
        self.start_streaming()
        self.toast(f"Mostrando la secuencia «{name}»")

    def ask_delete_sequence(self, name):
        def do():
            del self.cfg["sequences"][name]
            if self.cfg["source"] == {"kind": "sequence", "name": name}:
                self.cfg["source"] = {"kind": "stats"}
            self.seq_changed()
            self.source_changed()
        self.confirm(f"¿Eliminar la secuencia «{name}»?", "Los archivos quedan en la biblioteca.",
                     "Eliminar", do)

    # ---------- página: Diseño ----------

    def _page_design(self):
        body = self._flipbox()
        left = Gtk.Box(orientation=V, spacing=12, valign=Gtk.Align.START, halign=Gtk.Align.CENTER)
        self.canvas = Gtk.Picture(content_fit=Gtk.ContentFit.FILL, can_shrink=False, css_classes=["lcd"],
                                  halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.canvas.set_size_request(CANVAS, CANVAS)
        self.canvas.set_overflow(Gtk.Overflow.HIDDEN)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.canvas.add_controller(drag)
        left.append(self.canvas)
        left.append(Gtk.Label(label="Tocá un elemento para editarlo y arrastralo para moverlo.",
                              css_classes=["dim-label", "caption"], wrap=True, max_width_chars=44,
                              justify=Gtk.Justification.CENTER))
        body.append(left)

        right = Gtk.Box(orientation=V, spacing=24, hexpand=True)
        g = Adw.PreferencesGroup(title="Fondo")
        self.bg_color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                              valign=Gtk.Align.CENTER)
        self.bg_color.connect("notify::rgba", self.on_bg_color)
        row = Adw.ActionRow(title="Color")
        row.add_suffix(self.bg_color)
        g.add(row)
        self.bg_image = Adw.ComboRow(title="Imagen", subtitle="Se ve detrás de los medidores")
        self.bg_image.connect("notify::selected", self.on_bg_image)
        g.add(self.bg_image)
        right.append(g)

        self.elems = Adw.PreferencesGroup(title="Elementos")
        hdr = Gtk.Box(spacing=4)
        reset = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Restablecer diseño",
                           css_classes=["flat"], valign=Gtk.Align.CENTER)
        reset.connect("clicked", self.on_reset_layout)
        menu = Gio.Menu()
        for kind, label in layout.TYPES.items():
            it = Gio.MenuItem.new(label, None)
            it.set_action_and_target_value("win.lay-add", GLib.Variant.new_string(kind))
            menu.append_item(it)
        add = Gtk.MenuButton(icon_name="list-add-symbolic", tooltip_text="Agregar elemento",
                             css_classes=["flat"], valign=Gtk.Align.CENTER, menu_model=menu)
        hdr.append(reset)
        hdr.append(add)
        self.elems.set_header_suffix(hdr)
        right.append(self.elems)
        self.props_box = Gtk.Box(orientation=V)
        right.append(self.props_box)
        body.append(right)
        return self._page(body)

    def widgets(self):
        return self.cfg["layout"]["widgets"]

    def rebuild_design(self):
        L = self.cfg["layout"]
        self._sync = True
        self.bg_color.set_rgba(rgba(L.get("background", "#0a0a10")))
        self.bg_items = [None] + [n for n in config.library()]
        self.bg_image.set_model(Gtk.StringList.new(["Ninguna"] + self.bg_items[1:]))
        bg = L.get("background_image")
        self.bg_image.set_selected(self.bg_items.index(bg) if bg in self.bg_items else 0)
        self._sync = False

        for r in self.elem_rows:
            self.elems.remove(r)
        self.elem_rows = []
        if self.sel is not None and self.sel >= len(self.widgets()):
            self.sel = None
        for i, w in enumerate(self.widgets()):
            row = Adw.ActionRow(title=GLib.markup_escape_text(layout.describe(w)), activatable=True)
            if i == self.sel:
                row.add_prefix(Gtk.Image(icon_name="object-select-symbolic", css_classes=["accent"]))
            row.connect("activated", lambda _r, i=i: self.select(i))
            rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Eliminar",
                            css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
            rm.connect("clicked", lambda _b, i=i: self.delete_widget(i))
            row.add_suffix(rm)
            self.elems.add(row)
            self.elem_rows.append(row)
        self.rebuild_props()
        self.render_canvas()

    def select(self, i):
        if i != self.sel:
            self.sel = i
            self.rebuild_design()

    def render_canvas(self):
        img, self.boxes = layout.render(self.cfg["layout"], self.values, out=CANVAS, selected=self.sel)
        self.canvas.set_paintable(to_texture(img))

    def layout_changed(self):
        self.render_canvas()
        self.save_soon()

    def set_prop(self, key, val):
        if self._sync or self.sel is None:
            return
        w = self.widgets()[self.sel]
        w[key] = val
        self.elem_rows[self.sel].set_title(GLib.markup_escape_text(layout.describe(w)))
        self.layout_changed()

    # filas de propiedades
    def _combo(self, title, names, selected, cb):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(names))
        row.set_selected(selected)
        row.connect("notify::selected", lambda r, _p: cb(r.get_selected()))
        return row

    def _spin(self, title, lo, hi, val, key):
        row = Adw.SpinRow.new_with_range(lo, hi, 1)
        row.set_title(title)
        row.set_value(val)
        row.connect("notify::value", lambda r, _p: self.set_prop(key, int(r.get_value())))
        return row

    def _entry(self, title, val, key):
        row = Adw.EntryRow(title=title)
        row.set_text(val or "")
        row.connect("changed", lambda e: self.set_prop(key, e.get_text()))
        return row

    def rebuild_props(self):
        clear(self.props_box)
        self.xy_rows = None
        if self.sel is None:
            return
        w = self.widgets()[self.sel]
        t = w["type"]
        g = Adw.PreferencesGroup(title=layout.TYPES.get(t, t))
        rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Eliminar elemento",
                        css_classes=["flat"], valign=Gtk.Align.CENTER)
        rm.connect("clicked", lambda _b: self.delete_widget(self.sel))
        g.set_header_suffix(rm)
        names = [metrics.name(k) for k in metrics.KEYS]
        has_metric = t in ("gauge", "bar", "value")

        if has_metric:
            cur = metrics.KEYS.index(w["metric"]) if w.get("metric") in metrics.KEYS else 0
            g.add(self._combo("Métrica", names, cur, lambda i: self.set_prop("metric", metrics.KEYS[i])))
        if t == "gauge":
            subs = [None] + metrics.KEYS
            cur = subs.index(w.get("sub")) if w.get("sub") in subs else 0
            g.add(self._combo("Dato secundario", ["Ninguno"] + names, cur,
                              lambda i: self.set_prop("sub", subs[i])))
        if has_metric:
            g.add(self._entry("Etiqueta", w.get("label"), "label"))
        if t == "label":
            g.add(self._entry("Texto", w.get("text"), "text"))
        if t == "clock":
            fmts = list(layout.CLOCK_FORMATS)
            cur = fmts.index(w.get("format")) if w.get("format") in fmts else 0
            g.add(self._combo("Formato", list(layout.CLOCK_FORMATS.values()), cur,
                              lambda i: self.set_prop("format", fmts[i])))
        shapes = {"gauge": layout.GAUGE_SHAPES, "bar": layout.BAR_SHAPES}.get(t)
        if shapes:
            keys = list(shapes)
            cur = keys.index(w.get("shape")) if w.get("shape") in keys else 0
            g.add(self._combo("Forma", list(shapes.values()), cur, lambda i: self.set_prop("shape", keys[i])))
        size_title, lo, hi = {"gauge": ("Radio", 10, 120), "bar": ("Ancho", 20, 240)}.get(t, ("Tamaño", 6, 120))
        g.add(self._spin(size_title, lo, hi, w.get("size", 20), "size"))
        if t in ("gauge", "bar"):
            g.add(self._spin("Grosor", 1, 40, w.get("thickness", 9), "thickness"))

        color_row = Adw.ActionRow(title="Color")
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        btn.set_rgba(rgba(w.get("color") if w.get("color", "auto") != "auto" else
                          ("#ffffff" if t in ("clock", "label") else "#00c8ff")))
        btn.connect("notify::rgba", lambda b, _p: self.set_prop("color", hexcolor(b.get_rgba())))
        color_row.add_suffix(btn)
        if has_metric:
            auto = Adw.SwitchRow(title="Color automático", active=w.get("color", "auto") == "auto",
                                 subtitle="Celeste, naranja o rojo según la temperatura"
                                 if metrics.is_temp(w.get("metric")) else "Usa el celeste de acento")
            color_row.set_sensitive(not auto.get_active())

            def on_auto(r, _p):
                color_row.set_sensitive(not r.get_active())
                self.set_prop("color", "auto" if r.get_active() else hexcolor(btn.get_rgba()))
            auto.connect("notify::active", on_auto)
            g.add(auto)
        g.add(color_row)

        xr = self._spin("Posición horizontal", 0, SIZE, w["x"], "x")
        yr = self._spin("Posición vertical", 0, SIZE, w["y"], "y")
        g.add(xr)
        g.add(yr)
        self.xy_rows = (xr, yr)
        self.props_box.append(g)

    def on_drag_begin(self, _g, x, y):
        s = (self.canvas.get_width() or CANVAS) / SIZE
        i = layout.hit(self.boxes, x / s, y / s)
        self.select(i)
        self.drag_from = (self.widgets()[i]["x"], self.widgets()[i]["y"]) if i is not None else None

    def on_drag_update(self, _g, dx, dy):
        if self.drag_from is None or self.sel is None:
            return
        s = (self.canvas.get_width() or CANVAS) / SIZE
        w = self.widgets()[self.sel]
        w["x"] = max(0, min(SIZE, round(self.drag_from[0] + dx / s)))
        w["y"] = max(0, min(SIZE, round(self.drag_from[1] + dy / s)))
        self.render_canvas()
        if self.xy_rows:
            self._sync = True
            self.xy_rows[0].set_value(w["x"])
            self.xy_rows[1].set_value(w["y"])
            self._sync = False

    def on_drag_end(self, *_):
        if self.drag_from is not None:
            self.drag_from = None
            self.save_soon()

    def add_widget(self, kind):
        self.widgets().append(layout.new_widget(kind))
        self.sel = len(self.widgets()) - 1
        self.rebuild_design()
        self.save_soon()

    def delete_widget(self, i):
        if i is None or i >= len(self.widgets()):
            return
        del self.widgets()[i]
        self.sel = None
        self.rebuild_design()
        self.save_soon()

    def on_bg_color(self, btn, _p):
        if not self._sync:
            self.cfg["layout"]["background"] = hexcolor(btn.get_rgba())
            self.layout_changed()

    def on_bg_image(self, row, _p):
        if not self._sync:
            i = row.get_selected()
            self.cfg["layout"]["background_image"] = self.bg_items[i] if i < len(self.bg_items) else None
            self.layout_changed()

    def on_reset_layout(self, _btn):
        def do():
            self.cfg["layout"] = layout.default()
            self.sel = None
            self.save_now()
            self.rebuild_design()
            self.rebuild_preview()
        self.confirm("¿Restablecer el diseño?", "Vuelve a los medidores originales.", "Restablecer", do)

    # ---------- general ----------

    def tick_metrics(self):
        self.values = metrics.read()
        if self.stack.get_visible_child_name() == "design":
            self.render_canvas()
        return True

    def on_page(self, *_):
        page = self.stack.get_visible_child_name()
        if page == "design":
            self.render_canvas()
        elif page == "library":
            self.rebuild_library()  # refresca la miniatura de los medidores
        elif page == "screen":
            self.rebuild_preview()

    def on_close(self, _win):
        self.save_now()
        return False  # el servicio sigue corriendo


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
