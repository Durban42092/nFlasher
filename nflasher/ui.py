"""
nFlasher - GTK4 Frontend
Samsung device flash tool using nphonecli / odin4 / heimdall backends.

Implements:
  - Odin4 for Linux partition layout  (BL / AP / CP / CSC / USERDATA)
  - heimdall-flash-frontend features  (PIT viewer, partition table, log)
  - nphonecli/nphonekit backend       (device detection, flash, reboot)
"""

import os
import sys
import tempfile
import threading
from datetime import datetime

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402
except (ImportError, ValueError) as _gi_err:
    raise ImportError(
        "nFlasher UI requires GTK4 and libadwaita. "
        "Install with: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
    ) from _gi_err

from .backend import (  # noqa: E402
    DeviceInfo,
    DeviceManager,
    DeviceState,
    FlashBackend,
    FlashEngine,
    FlashOptions,
    FlashPartition,
    PITManager,
    backend_version,
    detect_backend,
    reboot_device,
)
from .pit import PITParseError, parse_pit, pit_summary  # noqa: E402

APP_ID = "io.github.nflasher"
APP_NAME = "nFlasher"
APP_VERSION = "1.0.0"

# Odin-style partition slots
PARTITION_SLOTS = [
    ("BL", "--bl", "Bootloader / Sboot / LK", "*.tar *.tar.md5 *.bin"),
    ("AP", "--ap", "Android Platform / PDA / System", "*.tar *.tar.md5 *.zip"),
    ("CP", "--cp", "Modem / Radio baseband", "*.tar *.tar.md5 *.bin"),
    ("CSC", "--csc", "Country Specific Code / Vendor", "*.tar *.tar.md5"),
    ("USERDATA", "--userdata", "User data partition", "*.tar *.tar.md5 *.img"),
]


# ── CSS theme ────────────────────────────────────────────────────────────────

NFLASHER_CSS = """
/* nFlasher dark theme */
window {
    background-color: #0D0D0F;
    color: #E0E0E0;
}

.nf-titlebar {
    background: linear-gradient(135deg, #13131A 0%, #1A1A28 100%);
    border-bottom: 1px solid #2A2A40;
    padding: 8px 16px;
}

.nf-logo-label {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 22px;
    font-weight: bold;
    color: #4FC3F7;
    letter-spacing: 4px;
}

.nf-version-label {
    font-size: 10px;
    color: #5A5A7A;
    font-family: monospace;
}

.nf-device-panel {
    background-color: #12121C;
    border: 1px solid #2A2A40;
    border-radius: 6px;
    padding: 12px;
}

.nf-device-connected {
    color: #66BB6A;
    font-weight: bold;
}

.nf-device-disconnected {
    color: #EF5350;
}

.nf-device-info {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #90A4AE;
}

.nf-partition-frame {
    background-color: #13131E;
    border: 1px solid #252540;
    border-radius: 4px;
}

.nf-partition-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: bold;
    color: #4FC3F7;
    min-width: 80px;
}

.nf-file-entry {
    font-family: monospace;
    font-size: 11px;
    background-color: #0A0A14;
    color: #B0BEC5;
    border: 1px solid #2A2A40;
}

.nf-browse-btn {
    background: #1E1E30;
    color: #90CAF9;
    border: 1px solid #3A3A5C;
    border-radius: 3px;
    padding: 4px 10px;
    font-size: 11px;
}

.nf-browse-btn:hover {
    background: #2A2A45;
    border-color: #4FC3F7;
}

.nf-flash-btn {
    background: linear-gradient(135deg, #1565C0, #0D47A1);
    color: white;
    font-size: 14px;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 10px 32px;
    letter-spacing: 1px;
}

.nf-flash-btn:hover {
    background: linear-gradient(135deg, #1976D2, #1565C0);
}

.nf-flash-btn:disabled {
    background: #1A1A2A;
    color: #44445A;
}

.nf-abort-btn {
    background: linear-gradient(135deg, #B71C1C, #880E0E);
    color: white;
    font-size: 13px;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 10px 24px;
}

.nf-abort-btn:hover {
    background: linear-gradient(135deg, #C62828, #B71C1C);
}

.nf-log-view {
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 11px;
    background-color: #08080F;
    color: #B2DFDB;
}

.nf-progress-bar trough {
    background: #1A1A2A;
    border-radius: 3px;
    min-height: 12px;
}

.nf-progress-bar progress {
    background: linear-gradient(90deg, #0D47A1, #4FC3F7);
    border-radius: 3px;
}

.nf-tab-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: bold;
}

.nf-options-check {
    font-size: 11px;
    color: #90A4AE;
}

.nf-status-ok    { color: #66BB6A; }
.nf-status-warn  { color: #FFA726; }
.nf-status-error { color: #EF5350; }
.nf-status-info  { color: #4FC3F7; }

.nf-section-header {
    font-size: 10px;
    font-weight: bold;
    color: #5A5A7A;
    letter-spacing: 2px;
}

.nf-pit-view {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    background-color: #09090F;
    color: #80CBC4;
}

.nf-backend-badge {
    background: #1E1E35;
    color: #7986CB;
    border: 1px solid #3949AB;
    border-radius: 3px;
    padding: 2px 8px;
    font-family: monospace;
    font-size: 10px;
}
"""


# ── Partition row widget ─────────────────────────────────────────────────────


class PartitionRow(Gtk.Box):
    def __init__(self, slot: str, flag: str, tooltip: str, patterns: str):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.slot = slot
        self.flag = flag
        self.filepath = None
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(8)
        self.set_margin_end(8)

        # Enabled checkbox
        self.chk = Gtk.CheckButton()
        self.chk.set_active(False)
        self.chk.connect("toggled", self._on_toggle)
        self.append(self.chk)

        # Slot label
        lbl = Gtk.Label(label=slot)
        lbl.add_css_class("nf-partition-label")
        lbl.set_xalign(0)
        lbl.set_tooltip_text(tooltip)
        self.append(lbl)

        # File path entry
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(f"Select {slot} file…")
        self.entry.set_hexpand(True)
        self.entry.set_editable(False)
        self.entry.add_css_class("nf-file-entry")
        self.append(self.entry)

        # Browse button
        self.browse_btn = Gtk.Button(label="Browse…")
        self.browse_btn.add_css_class("nf-browse-btn")
        self.browse_btn.connect("clicked", self._on_browse)
        self.append(self.browse_btn)

        # Clear button
        clr = Gtk.Button(label="✕")
        clr.add_css_class("nf-browse-btn")
        clr.set_tooltip_text("Clear selection")
        clr.connect("clicked", self._on_clear)
        self.append(clr)

        self._update_sensitivity()

    def _on_toggle(self, _):
        self._update_sensitivity()

    def _update_sensitivity(self):
        active = self.chk.get_active()
        self.entry.set_sensitive(active)
        self.browse_btn.set_sensitive(active)

    def _on_clear(self, _):
        self.entry.set_text("")
        self.filepath = None

    def _on_browse(self, _):
        dialog = Gtk.FileDialog()
        dialog.set_title(f"Select {self.slot} File")
        dialog.open(self.get_root(), None, self._on_file_chosen)

    def _on_file_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self.filepath = path
                self.entry.set_text(os.path.basename(path))
                self.entry.set_tooltip_text(path)
                self.chk.set_active(True)
        except GLib.Error:
            pass

    def get_partition(self) -> FlashPartition | None:
        if self.chk.get_active() and self.filepath:
            return FlashPartition(flag=self.flag, filepath=self.filepath)
        return None


# ── Main window ──────────────────────────────────────────────────────────────


class NFlasherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(960, 780)
        self.set_size_request(800, 600)

        self._backend = detect_backend()
        self._options = FlashOptions()
        self._pit_data = None
        self._flash_engine = None
        self._device_mgr = None
        self._partition_rows = []
        self._pit_row = None

        self._build_ui()
        self._init_backend()
        self._log_event(f"nFlasher {APP_VERSION} started")
        self._log_event(f"Backend: {self._backend.value} — {backend_version(self._backend)}")

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        root.append(self._build_header())

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        content.set_vexpand(True)
        root.append(content)

        left = self._build_left_panel()
        left.set_size_request(580, -1)
        content.append(left)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        content.append(sep)

        right = self._build_right_panel()
        right.set_hexpand(True)
        content.append(right)

        root.append(self._build_statusbar())

    def _build_header(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class("nf-titlebar")
        bar.set_margin_top(0)

        logo = Gtk.Label(label="nFLASHER")
        logo.add_css_class("nf-logo-label")
        bar.append(logo)

        ver = Gtk.Label(label=f"v{APP_VERSION}")
        ver.add_css_class("nf-version-label")
        bar.append(ver)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self._backend_badge = Gtk.Label(label=self._backend.value.upper())
        self._backend_badge.add_css_class("nf-backend-badge")
        bar.append(self._backend_badge)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Device status pill
        self._device_status_lbl = Gtk.Label(label="● NO DEVICE")
        self._device_status_lbl.add_css_class("nf-device-disconnected")
        self._device_status_lbl.set_margin_end(8)
        bar.append(self._device_status_lbl)

        return bar

    def _build_left_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        notebook.set_hexpand(True)
        box.append(notebook)

        # ── Tab 1: Flash ─────────────────────────────────────────────────────
        flash_page = self._build_flash_tab()
        tab1 = Gtk.Label(label="FLASH")
        tab1.add_css_class("nf-tab-label")
        notebook.append_page(flash_page, tab1)

        # ── Tab 2: PIT ───────────────────────────────────────────────────────
        pit_page = self._build_pit_tab()
        tab2 = Gtk.Label(label="PIT")
        tab2.add_css_class("nf-tab-label")
        notebook.append_page(pit_page, tab2)

        # ── Tab 3: Options ───────────────────────────────────────────────────
        opt_page = self._build_options_tab()
        tab3 = Gtk.Label(label="OPTIONS")
        tab3.add_css_class("nf-tab-label")
        notebook.append_page(opt_page, tab3)

        # ── Tab 4: Device ────────────────────────────────────────────────────
        dev_page = self._build_device_tab()
        tab4 = Gtk.Label(label="DEVICE")
        tab4.add_css_class("nf-tab-label")
        notebook.append_page(dev_page, tab4)

        # ── Action bar ───────────────────────────────────────────────────────
        box.append(self._build_action_bar())
        return box

    def _build_flash_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        scroll.set_child(vbox)

        hdr = Gtk.Label(label="PARTITION FILES")
        hdr.add_css_class("nf-section-header")
        hdr.set_xalign(0)
        hdr.set_margin_start(12)
        hdr.set_margin_bottom(4)
        vbox.append(hdr)

        for slot, flag, tooltip, patterns in PARTITION_SLOTS:
            row = PartitionRow(slot, flag, tooltip, patterns)
            frame = Gtk.Frame()
            frame.add_css_class("nf-partition-frame")
            frame.set_margin_start(8)
            frame.set_margin_end(8)
            frame.set_margin_bottom(2)
            frame.set_child(row)
            vbox.append(frame)
            self._partition_rows.append(row)

        # PIT row
        sep = Gtk.Separator()
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        sep.set_margin_start(12)
        sep.set_margin_end(12)
        vbox.append(sep)

        pit_hdr = Gtk.Label(label="PIT FILE  (optional — overrides device PIT)")
        pit_hdr.add_css_class("nf-section-header")
        pit_hdr.set_xalign(0)
        pit_hdr.set_margin_start(12)
        pit_hdr.set_margin_bottom(4)
        vbox.append(pit_hdr)

        self._pit_row = PartitionRow("PIT", "--pit", "Partition Information Table", "*.pit *.bin")
        pit_frame = Gtk.Frame()
        pit_frame.add_css_class("nf-partition-frame")
        pit_frame.set_margin_start(8)
        pit_frame.set_margin_end(8)
        pit_frame.set_child(self._pit_row)
        vbox.append(pit_frame)

        return scroll

    def _build_pit_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(8)
        vbox.set_margin_start(8)
        vbox.set_margin_end(8)
        vbox.set_margin_bottom(8)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vbox.append(btn_row)

        dl_btn = Gtk.Button(label="⬇ Download PIT from Device")
        dl_btn.add_css_class("nf-browse-btn")
        dl_btn.connect("clicked", self._on_download_pit)
        btn_row.append(dl_btn)

        open_btn = Gtk.Button(label="📂 Open Local PIT…")
        open_btn.add_css_class("nf-browse-btn")
        open_btn.connect("clicked", self._on_open_pit)
        btn_row.append(open_btn)

        save_btn = Gtk.Button(label="💾 Save PIT…")
        save_btn.add_css_class("nf-browse-btn")
        save_btn.connect("clicked", self._on_save_pit)
        btn_row.append(save_btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.add_css_class("nf-pit-view")
        self._pit_textview = tv
        self._pit_buffer = tv.get_buffer()
        scroll.set_child(tv)
        vbox.append(scroll)

        return vbox

    def _build_options_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(16)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)

        def mksection(title: str):
            lbl = Gtk.Label(label=title)
            lbl.add_css_class("nf-section-header")
            lbl.set_xalign(0)
            vbox.append(lbl)

        def mkcheck(label: str, tooltip: str, attr: str, default: bool = False) -> Gtk.CheckButton:
            chk = Gtk.CheckButton(label=label)
            chk.add_css_class("nf-options-check")
            chk.set_active(default)
            chk.set_tooltip_text(tooltip)
            chk.connect("toggled", lambda c: setattr(self._options, attr, c.get_active()))
            setattr(self._options, attr, default)
            vbox.append(chk)
            return chk

        mksection("FLASH BEHAVIOUR")
        mkcheck("Auto Reboot", "Reboot device automatically after successful flash", "reboot", True)
        mkcheck(
            "T-Flash (SD card flash)", "Flash to SD card instead of internal eMMC", "t_flash", False
        )

        mksection("SAFETY OPTIONS")
        mkcheck(
            "EFS Clear",
            "⚠ Wipe EFS partition (IMEI, network certs) — irreversible",
            "efs_clear",
            False,
        )
        mkcheck(
            "Bootloader Update",
            "Allow bootloader-updating flashes (required for BL)",
            "bootloader_update",
            False,
        )
        mkcheck(
            "Reset Flash Counter",
            "Reset binary/flash counter (trip-wire) on device",
            "reset_time",
            False,
        )

        mksection("VERIFICATION")
        mkcheck("Verify Flash", "Read-back and verify written data (slower)", "verify", False)

        mksection("BACKEND SELECTION")
        backend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(backend_box)

        for be in [FlashBackend.NPHONECLI, FlashBackend.ODIN4, FlashBackend.HEIMDALL]:
            btn = Gtk.Button(label=be.value)
            btn.add_css_class("nf-browse-btn")
            btn.connect("clicked", lambda _, b=be: self._set_backend(b))
            backend_box.append(btn)

        return vbox

    def _build_device_tab(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)

        frame = Gtk.Frame()
        frame.set_label("Connected Device")
        frame.add_css_class("nf-device-panel")

        self._device_info_lbl = Gtk.Label(
            label="No device connected.\nPut device into Download Mode\n(Power + Volume Down + Home / Bixby)"
        )
        self._device_info_lbl.add_css_class("nf-device-info")
        self._device_info_lbl.set_justify(Gtk.Justification.LEFT)
        self._device_info_lbl.set_xalign(0)
        self._device_info_lbl.set_margin_top(8)
        self._device_info_lbl.set_margin_start(8)
        self._device_info_lbl.set_margin_bottom(8)
        frame.set_child(self._device_info_lbl)
        vbox.append(frame)

        reboot_hdr = Gtk.Label(label="REBOOT DEVICE")
        reboot_hdr.add_css_class("nf-section-header")
        reboot_hdr.set_xalign(0)
        reboot_hdr.set_margin_top(12)
        vbox.append(reboot_hdr)

        rbt_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(rbt_row)

        for mode, label in [
            ("normal", "🔄 Reboot"),
            ("download", "⬇ Download Mode"),
            ("recovery", "🔧 Recovery"),
        ]:
            btn = Gtk.Button(label=label)
            btn.add_css_class("nf-browse-btn")
            btn.connect("clicked", lambda _, m=mode: self._on_reboot(m))
            rbt_row.append(btn)

        return vbox

    def _build_right_panel(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.set_margin_top(6)
        hdr.set_margin_start(8)
        hdr.set_margin_end(8)
        hdr.set_margin_bottom(4)

        log_lbl = Gtk.Label(label="OUTPUT LOG")
        log_lbl.add_css_class("nf-section-header")
        hdr.append(log_lbl)

        spc = Gtk.Box()
        spc.set_hexpand(True)
        hdr.append(spc)

        clr_btn = Gtk.Button(label="Clear")
        clr_btn.add_css_class("nf-browse-btn")
        clr_btn.connect("clicked", lambda _: self._log_buffer.set_text(""))
        hdr.append(clr_btn)

        vbox.append(hdr)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.add_css_class("nf-log-view")
        self._log_view = tv
        self._log_buffer = tv.get_buffer()
        self._setup_log_tags()
        scroll.set_child(tv)
        vbox.append(scroll)

        return vbox

    def _build_action_bar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Progress bar
        self._progress = Gtk.ProgressBar()
        self._progress.add_css_class("nf-progress-bar")
        self._progress.set_show_text(True)
        self._progress.set_text("Ready")
        box.append(self._progress)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(btn_row)

        self._flash_btn = Gtk.Button(label="▶ START")
        self._flash_btn.add_css_class("nf-flash-btn")
        self._flash_btn.set_hexpand(True)
        self._flash_btn.connect("clicked", self._on_flash_start)
        btn_row.append(self._flash_btn)

        self._abort_btn = Gtk.Button(label="■ ABORT")
        self._abort_btn.add_css_class("nf-abort-btn")
        self._abort_btn.set_sensitive(False)
        self._abort_btn.connect("clicked", self._on_flash_abort)
        btn_row.append(self._abort_btn)

        return box

    def _build_statusbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(2)
        bar.set_margin_bottom(4)

        self._status_lbl = Gtk.Label(label="Idle")
        self._status_lbl.add_css_class("nf-status-info")
        self._status_lbl.set_xalign(0)
        bar.append(self._status_lbl)

        spc = Gtk.Box()
        spc.set_hexpand(True)
        bar.append(spc)

        ts_lbl = Gtk.Label(label="nFlasher — Samsung Flash Tool")
        ts_lbl.add_css_class("nf-version-label")
        bar.append(ts_lbl)

        return bar

    # ── Log helpers ──────────────────────────────────────────────────────────

    def _setup_log_tags(self):
        buf = self._log_buffer
        buf.create_tag("ok", foreground="#66BB6A")
        buf.create_tag("warn", foreground="#FFA726")
        buf.create_tag("error", foreground="#EF5350")
        buf.create_tag("info", foreground="#4FC3F7")
        buf.create_tag("dim", foreground="#546E7A")

    def _log_event(self, msg: str):
        GLib.idle_add(self._append_log, msg)

    def _append_log(self, msg: str):
        buf = self._log_buffer
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        end = buf.get_end_iter()

        # Timestamp
        buf.insert_with_tags_by_name(end, f"[{ts}] ", "dim")
        end = buf.get_end_iter()

        # Colour by content
        lower = msg.lower()
        if any(k in lower for k in ("error", "fail", "abort", "fatal")):
            tag = "error"
        elif any(k in lower for k in ("warn", "caution")):
            tag = "warn"
        elif any(k in lower for k in ("ok", "done", "success", "complete", "finish")):
            tag = "ok"
        elif any(k in lower for k in ("[info]", "[pit]", "[exec]", "[poll")):
            tag = "info"
        else:
            tag = None

        if tag:
            buf.insert_with_tags_by_name(end, msg + "\n", tag)
        else:
            buf.insert(end, msg + "\n")

        # Auto-scroll
        adj = self._log_view.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    # ── Backend / device init ────────────────────────────────────────────────

    def _init_backend(self):
        self._flash_engine = FlashEngine(
            on_log=self._log_event,
            on_progress=self._on_flash_progress,
            on_done=self._on_flash_done,
            backend=self._backend,
        )
        self._pit_mgr = PITManager(
            on_log=self._log_event,
            backend=self._backend,
        )
        self._device_mgr = DeviceManager(
            on_state_change=self._on_device_state,
            on_log=self._log_event,
            backend=self._backend,
        )
        self._device_mgr.start_polling()

    def _set_backend(self, be: FlashBackend):
        self._backend = be
        self._backend_badge.set_label(be.value.upper())
        self._log_event(f"[config] Backend switched to {be.value} — {backend_version(be)}")
        if self._device_mgr:
            self._device_mgr.stop_polling()
        self._init_backend()

    # ── Device state callbacks ───────────────────────────────────────────────

    def _on_device_state(self, state: DeviceState, info: DeviceInfo | None):
        GLib.idle_add(self._update_device_ui, state, info)

    def _update_device_ui(self, state: DeviceState, info: DeviceInfo | None):
        if state == DeviceState.CONNECTED:
            self._device_status_lbl.set_label("● CONNECTED")
            self._device_status_lbl.remove_css_class("nf-device-disconnected")
            self._device_status_lbl.add_css_class("nf-device-connected")
            if info:
                self._device_info_lbl.set_text(str(info))
            self._status_lbl.set_label("Device connected — ready to flash")
            self._flash_btn.set_sensitive(True)
        else:
            self._device_status_lbl.set_label("● NO DEVICE")
            self._device_status_lbl.remove_css_class("nf-device-connected")
            self._device_status_lbl.add_css_class("nf-device-disconnected")
            self._device_info_lbl.set_text(
                "No device connected.\nPut device into Download Mode\n"
                "(Power + Vol Down + Home  or  Power + Vol Down + Bixby)"
            )
            self._status_lbl.set_label("Waiting for device…")
        return False

    # ── Flash callbacks ──────────────────────────────────────────────────────

    def _on_flash_progress(self, pct: float, label: str = ""):
        GLib.idle_add(self._update_progress, pct, label)

    def _update_progress(self, pct: float, label: str):
        self._progress.set_fraction(pct / 100.0)
        self._progress.set_text(f"{label}  {pct:.1f}%" if label else f"{pct:.1f}%")
        return False

    def _on_flash_done(self, ok: bool, msg: str):
        GLib.idle_add(self._flash_done_ui, ok, msg)

    def _flash_done_ui(self, ok: bool, msg: str):
        self._flash_btn.set_sensitive(True)
        self._abort_btn.set_sensitive(False)
        if ok:
            self._progress.set_fraction(1.0)
            self._progress.set_text("Flash Complete!")
            self._status_lbl.set_label("✔ Flash successful")
            self._log_event("[done] Flash completed successfully.")
        else:
            self._progress.set_fraction(0.0)
            self._progress.set_text("Failed")
            self._status_lbl.set_label(f"✖ Flash failed: {msg}")
            self._log_event(f"[error] Flash failed: {msg}")
        return False

    # ── User actions ─────────────────────────────────────────────────────────

    def _on_flash_start(self, _):
        partitions = []
        for row in self._partition_rows:
            p = row.get_partition()
            if p:
                partitions.append(p)

        pit_p = self._pit_row.get_partition() if self._pit_row else None
        if pit_p:
            partitions.insert(0, pit_p)

        if not partitions:
            self._show_dialog(
                "No Partitions Selected", "Enable and select at least one partition file to flash."
            )
            return

        self._flash_btn.set_sensitive(False)
        self._abort_btn.set_sensitive(True)
        self._progress.set_fraction(0.0)
        self._progress.set_text("Flashing…")
        self._status_lbl.set_label("Flashing…")
        self._log_event(f"[flash] Starting flash — {len(partitions)} partition(s)")

        self._flash_engine.flash(partitions, self._options)

    def _on_flash_abort(self, _):
        self._flash_engine.abort()
        self._abort_btn.set_sensitive(False)
        self._status_lbl.set_label("Aborting…")

    def _on_download_pit(self, _):
        fd, tmp = tempfile.mkstemp(suffix=".pit", prefix="nflasher_")
        os.close(fd)
        self._log_event(f"[pit] Downloading PIT from device → {tmp}")

        def do_dl():
            ok = self._pit_mgr.download_pit(tmp)
            GLib.idle_add(self._pit_downloaded, ok, tmp)

        threading.Thread(target=do_dl, daemon=True).start()

    def _pit_downloaded(self, ok: bool, path: str):
        if ok and os.path.exists(path):
            self._load_pit_file(path)
        else:
            self._log_event("[pit] PIT download failed — is device in Download Mode?")
        return False

    def _on_open_pit(self, _):
        dialog = Gtk.FileDialog()
        dialog.set_title("Open PIT File")
        dialog.open(self, None, self._pit_file_chosen)

    def _pit_file_chosen(self, dialog, result):
        try:
            f = dialog.open_finish(result)
            if f:
                self._load_pit_file(f.get_path())
        except GLib.Error:
            pass

    def _load_pit_file(self, path: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
            pit = parse_pit(data)
            self._pit_data = pit
            summary = pit_summary(pit)
            self._pit_buffer.set_text(summary)
            self._log_event(
                f"[pit] Loaded PIT: {os.path.basename(path)} — {pit.entry_count} partitions (v{pit.version})"
            )
        except PITParseError as e:
            self._log_event(f"[pit] Parse error: {e}")
        except Exception as e:
            self._log_event(f"[pit] Error loading: {e}")

    def _on_save_pit(self, _):
        if not self._pit_data:
            self._show_dialog("No PIT Loaded", "Download or open a PIT file first.")
            return
        dialog = Gtk.FileDialog()
        dialog.set_title("Save PIT File")
        dialog.set_initial_name("device.pit")
        dialog.save(self, None, self._pit_save_chosen)

    def _pit_save_chosen(self, dialog, result):
        try:
            f = dialog.save_finish(result)
            if f:
                from .pit import serialize_pit

                raw = serialize_pit(self._pit_data)
                with open(f.get_path(), "wb") as fh:
                    fh.write(raw)
                self._log_event(f"[pit] Saved to {f.get_path()}")
        except GLib.Error:
            pass

    def _on_reboot(self, mode: str):
        self._log_event(f"[reboot] Rebooting device → {mode}")
        threading.Thread(
            target=reboot_device, args=(mode, self._backend, self._log_event), daemon=True
        ).start()

    def _show_dialog(self, title: str, body: str):
        dlg = Adw.MessageDialog(transient_for=self, modal=True)
        dlg.set_heading(title)
        dlg.set_body(body)
        dlg.add_response("ok", "OK")
        dlg.present()


# ── Application ──────────────────────────────────────────────────────────────


class NFlasherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _):
        css = Gtk.CssProvider()
        css.load_from_data(NFLASHER_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        win = NFlasherWindow(self)
        win.present()


def main():
    app = NFlasherApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
