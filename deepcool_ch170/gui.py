"""Window for choosing what the CH170 case panel shows."""

import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from .config import Config, load, save
from .sensors import Sampler

STYLE = """
window { background-color: #14181b; color: #e7eeef; }
label { color: #e7eeef; }
.card {
  background-color: #1e2528;
  border: 1px solid rgba(231, 238, 239, 0.07);
  border-radius: 12px;
  padding: 16px;
}
.dim { color: #8ea0a2; font-size: 12px; }
.muted { color: #8ea0a2; }
.name { color: #5ee0d6; font-weight: 700; }
.slot { font-size: 15px; font-weight: 600; }
button.suggested-action {
  background-color: #00c8be;
  color: #102022;
  border-radius: 8px;
  padding: 6px 16px;
}
button.suggested-action label { color: #102022; }
button.suggested-action:hover { background-color: #2ad8ce; }
checkbutton check,
checkbutton radio {
  border-color: #6a787b;
  background-color: #14181b;
  color: #e7eeef;
}
checkbutton check:checked,
checkbutton radio:checked {
  background-color: #00c8be;
  border-color: #00c8be;
  color: #102022;
}
switch {
  background-color: #2c3538;
  border: 1px solid #3e494c;
}
switch slider {
  background-color: #d5e0e1;
  border-radius: 99px;
}
switch:checked {
  background-color: #00c8be;
  border-color: #00c8be;
}
switch:checked slider { background-color: #f4f8f8; }
spinbutton button {
  background: transparent;
  color: #c5d4d4;
}
spinbutton button:hover { color: #00c8be; }
spinbutton:focus, entry:focus { border-color: #00c8be; }
"""


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CH170 Display")
        self.set_default_size(820, 248)
        self._apply_style()
        self._cfg = load()
        self._sampler = Sampler()
        self._sampler.read(self._cfg)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{edge}")(16)
        self.set_child(root)

        header = Gtk.Box(spacing=12)
        header.set_valign(Gtk.Align.CENTER)
        self._ready = False
        on_row, self._on = _switch("On", self._cfg.enabled)
        self._on.connect("notify::active", self._on_toggle)
        title = Gtk.Label(label="Case display", xalign=0, hexpand=True)
        title.set_valign(Gtk.Align.CENTER)
        self._status = Gtk.Label(xalign=1)
        self._status.add_css_class("muted")
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_save)
        header.append(on_row)
        header.append(title)
        header.append(self._status)
        header.append(apply_btn)
        root.append(header)

        body = Gtk.Box(spacing=12)
        body.set_valign(Gtk.Align.CENTER)
        root.append(body)

        self._modes = {}
        modes = Gtk.Box(spacing=8)
        group = None
        for key, label in (("auto", "Cycle"), ("cpu", "CPU"), ("gpu", "GPU"), ("psu", "PSU")):
            button = Gtk.CheckButton(label=label)
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.set_active(key == self._cfg.mode)
            button.connect("toggled", self._sync_cycle)
            self._modes[key] = button
            modes.append(button)

        self._checks = {}
        cycle = Gtk.Box(spacing=16)
        for key, label in (("cpu", "CPU"), ("gpu", "GPU"), ("psu", "PSU")):
            row, switch = _switch(label, key in self._cfg.pages)
            switch.connect("notify::active", self._sync_cycle)
            self._checks[key] = switch
            cycle.append(row)

        self._dwell = _spin(1, 60, 1, self._cfg.dwell_sec)
        self._unit = Gtk.DropDown.new_from_strings(["°C", "°F"])
        self._unit.set_selected(1 if self._cfg.fahrenheit else 0)
        self._overhead = _spin(0, 500, 5, self._cfg.psu_overhead_w)
        self._capacity = _spin(0, 5000, 50, self._cfg.psu_capacity_w)
        timing = Gtk.Box(spacing=12)
        timing.append(_inline("Seconds", self._dwell))
        timing.append(_inline("Unit", self._unit))
        self._psu_row = Gtk.Box(spacing=12)
        self._psu_row.append(_inline("Extra W", self._overhead))
        self._psu_row.append(_inline("Supply W", self._capacity))

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        controls.set_hexpand(True)
        controls.append(modes)
        controls.append(cycle)
        controls.append(timing)
        controls.append(self._psu_row)
        body.append(_card("Show", controls))

        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        grid.set_halign(Gtk.Align.START)
        grid.set_valign(Gtk.Align.CENTER)
        self._cells = {}
        for col, heading in enumerate(("Temp", "Power", "Use", ""), start=1):
            grid.attach(_dim(heading), col, 0, 1, 1)
        for row, key in enumerate(("cpu", "gpu", "psu"), start=1):
            grid.attach(_name(key.upper()), 0, row, 1, 1)
            cells = [_value() for _ in range(4)]
            for col, cell in enumerate(cells, start=1):
                grid.attach(cell, col, row, 1, 1)
            self._cells[key] = cells
        readout = _card("On the case", grid)
        readout.set_hexpand(False)
        readout.set_valign(Gtk.Align.CENTER)
        body.append(readout)

        self._sync_cycle()
        self._refresh_status()
        self._ready = True
        GLib.timeout_add(1000, self._tick)

    def _apply_style(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(STYLE.encode())
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_toggle(self, switch, _pspec):
        if not self._ready:
            return
        cfg = load()
        cfg.enabled = bool(switch.get_active())
        save(cfg)
        self._status.set_label("" if cfg.enabled else "Off")

    def _psu_shown(self):
        mode = self._selected_mode()
        if mode == "psu":
            return True
        return mode == "auto" and self._checks["psu"].get_active()

    def _sync_cycle(self, *_args):
        cycling = self._selected_mode() == "auto"
        for switch in self._checks.values():
            switch.set_sensitive(cycling)
        self._psu_row.set_visible(self._psu_shown())

    def _tick(self):
        self._cfg = load()
        reading = self._sampler.read(self._cfg)
        unit = "°F" if self._cfg.fahrenheit else "°C"
        _set_row(
            self._cells["cpu"],
            f"{_temp(reading.cpu_temp_c, self._cfg.fahrenheit)}{unit}",
            f"{reading.cpu_watts} W",
            f"{reading.cpu_pct}%",
            f"{reading.cpu_mhz} MHz",
        )
        _set_row(
            self._cells["gpu"],
            f"{_temp(reading.gpu_temp_c, self._cfg.fahrenheit)}{unit}",
            f"{reading.gpu_watts} W",
            f"{reading.gpu_pct}%",
            f"{reading.gpu_mhz} MHz",
        )
        usage = f"{reading.psu_pct}%" if self._cfg.psu_capacity_w else "—"
        psu_temp = "—" if reading.psu_temp_c is None else f"{_temp(reading.psu_temp_c, self._cfg.fahrenheit)}{unit}"
        fan = "— rpm" if reading.psu_rpm is None else f"{reading.psu_rpm} rpm"
        _set_row(self._cells["psu"], psu_temp, f"{reading.psu_watts} W", usage, fan)
        return True

    def _selected_mode(self):
        for key, button in self._modes.items():
            if button.get_active():
                return key
        return "auto"

    def _on_save(self, _button):
        pages = [key for key, switch in self._checks.items() if switch.get_active()]
        cfg = Config(
            mode=self._selected_mode(),
            pages=pages,
            dwell_sec=int(self._dwell.get_value()),
            update_ms=self._cfg.update_ms,
            fahrenheit=self._unit.get_selected() == 1,
            gpu_pci=self._cfg.gpu_pci,
            enabled=self._on.get_active(),
            psu_overhead_w=int(self._overhead.get_value()),
            psu_capacity_w=int(self._capacity.get_value()),
        )
        save(cfg)
        self._refresh_status(saved=True)

    def _refresh_status(self, saved=False):
        if saved and daemon_is_ours():
            self._status.set_label("Applied")
        elif daemon_is_ours():
            self._status.set_label("")
        else:
            self._status.set_label("Case writer is old")


def daemon_is_ours():
    try:
        text = subprocess.check_output(
            ["systemctl", "show", "-p", "MainPID", "--value", "deepcool-digital.service"],
            text=True,
        ).strip()
        pid = int(text)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return False
    if pid <= 0:
        return False
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"deepcool_ch170" in command


def _temp(celsius, fahrenheit):
    value = celsius * 9.0 / 5.0 + 32.0 if fahrenheit else celsius
    return f"{value:.0f}"


def _card(title, child):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.add_css_class("card")
    box.set_hexpand(True)
    box.set_valign(Gtk.Align.CENTER)
    heading = Gtk.Label(label=title, xalign=0)
    box.append(heading)
    box.append(child)
    return box


def _dim(text):
    label = Gtk.Label(label=text, xalign=1)
    label.add_css_class("dim")
    label.set_width_chars(8)
    return label


def _name(text):
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("name")
    label.set_width_chars(4)
    return label


def _value():
    label = Gtk.Label(label="—", xalign=1)
    label.add_css_class("slot")
    label.set_width_chars(8)
    return label


def _set_row(cells, *values):
    for cell, value in zip(cells, values):
        cell.set_label(value)


def _inline(text, widget):
    row = Gtk.Box(spacing=8)
    row.set_valign(Gtk.Align.CENTER)
    label = Gtk.Label(label=text)
    label.set_valign(Gtk.Align.CENTER)
    widget.set_valign(Gtk.Align.CENTER)
    row.append(label)
    row.append(widget)
    return row


def _switch(text, active):
    row = Gtk.Box(spacing=6)
    switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    row.append(switch)
    row.append(Gtk.Label(label=text))
    return row, switch


def _spin(low, high, step, value):
    spin = Gtk.SpinButton.new_with_range(low, high, step)
    spin.set_value(value)
    return spin


def main():
    app = Gtk.Application(application_id="local.ch170.Display")
    app.connect("activate", lambda application: Window(application).present())
    app.run(None)


if __name__ == "__main__":
    main()
