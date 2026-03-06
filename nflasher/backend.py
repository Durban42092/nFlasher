"""
nphonekit / nphonecli wrapper layer.

Provides async subprocess management, device detection,
PIT download, and partition flashing using nphonecli.
Fallback: raw libusb via pyusb for direct Odin4 protocol.

nphonecli protocol reference:
  https://github.com/Samsung-Lsm/nphone (community reverse)
"""

import os
import re
import json
import time
import struct
import threading
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict
from enum import Enum, auto


# ── Protocol constants ──────────────────────────────────────────────────────
SAMSUNG_VID              = 0x04E8
ODIN_PID_SET             = {0x6860, 0x685D, 0x6601, 0x6640}

DEFAULT_NPHONECLI        = shutil.which("nphonecli") or "nphonecli"
DEFAULT_HEIMDALL         = shutil.which("heimdall") or "heimdall"
DEFAULT_ODIN4            = shutil.which("odin4") or "odin4"


class DeviceState(Enum):
    DISCONNECTED  = auto()
    DETECTED      = auto()
    CONNECTED     = auto()
    DOWNLOADING   = auto()
    ERROR         = auto()


class FlashBackend(Enum):
    NPHONECLI    = "nphonecli"
    HEIMDALL     = "heimdall"
    ODIN4        = "odin4"
    AUTO         = "auto"


@dataclass
class DeviceInfo:
    serial:       str = ""
    model:        str = ""
    product:      str = ""
    firmware:     str = ""
    imei:         str = ""
    chip:         str = ""
    protocol:     str = ""
    raw:          Dict = field(default_factory=dict)

    def __str__(self):
        parts = []
        if self.model:    parts.append(f"Model: {self.model}")
        if self.product:  parts.append(f"Product: {self.product}")
        if self.firmware: parts.append(f"Firmware: {self.firmware}")
        if self.serial:   parts.append(f"Serial: {self.serial}")
        if self.chip:     parts.append(f"Chip: {self.chip}")
        if self.imei:     parts.append(f"IMEI: {self.imei}")
        if self.protocol: parts.append(f"Protocol: {self.protocol}")
        return "\n".join(parts) if parts else "Unknown Device"


@dataclass
class FlashPartition:
    flag:     str        # --bl, --ap, --cp, --csc, --userdata, --pit
    filepath: str
    name:     str = ""   # partition name override (heimdall)


@dataclass
class FlashOptions:
    reboot:           bool = True
    t_flash:          bool = False
    efs_clear:        bool = False
    bootloader_update: bool = False
    reset_time:       bool = False
    flash_lock:       bool = False
    verify:           bool = False
    resume:           bool = False


# ── Backend detection ───────────────────────────────────────────────────────

def detect_backend() -> FlashBackend:
    """Determine best available flashing backend."""
    if shutil.which("nphonecli"):
        return FlashBackend.NPHONECLI
    if shutil.which("odin4"):
        return FlashBackend.ODIN4
    if shutil.which("heimdall"):
        return FlashBackend.HEIMDALL
    return FlashBackend.NPHONECLI  # will error gracefully


def backend_version(backend: FlashBackend) -> str:
    try:
        cmd = {
            FlashBackend.NPHONECLI: ["nphonecli", "--version"],
            FlashBackend.ODIN4:     ["odin4", "--version"],
            FlashBackend.HEIMDALL:  ["heimdall", "version"],
        }[backend]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout + r.stderr).strip().splitlines()[0]
    except Exception as e:
        return f"unavailable ({e})"


# ── Device management ───────────────────────────────────────────────────────

class DeviceManager:
    """
    Detects Samsung devices in Download Mode via nphonecli/odin4/heimdall.
    Runs a background poller thread to notify state changes.
    """

    def __init__(
        self,
        on_state_change: Optional[Callable[[DeviceState, Optional[DeviceInfo]], None]] = None,
        on_log:          Optional[Callable[[str], None]] = None,
        poll_interval:   float = 2.0,
        backend:         FlashBackend = FlashBackend.AUTO,
    ):
        self.on_state_change = on_state_change
        self.on_log          = on_log
        self.poll_interval   = poll_interval
        self.backend         = detect_backend() if backend == FlashBackend.AUTO else backend
        self._state          = DeviceState.DISCONNECTED
        self._device_info    = None
        self._poll_thread    = None
        self._stop_event     = threading.Event()

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)

    def start_polling(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_polling(self):
        self._stop_event.set()

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                info = self._probe_device()
                new_state = DeviceState.CONNECTED if info else DeviceState.DISCONNECTED
                if new_state != self._state:
                    self._state = new_state
                    self._device_info = info
                    if self.on_state_change:
                        self.on_state_change(new_state, info)
            except Exception as e:
                self._log(f"[poll error] {e}")
            self._stop_event.wait(self.poll_interval)

    def _probe_device(self) -> Optional[DeviceInfo]:
        if self.backend == FlashBackend.NPHONECLI:
            return self._probe_nphonecli()
        elif self.backend == FlashBackend.ODIN4:
            return self._probe_odin4()
        elif self.backend == FlashBackend.HEIMDALL:
            return self._probe_heimdall()
        return None

    def _probe_nphonecli(self) -> Optional[DeviceInfo]:
        try:
            r = subprocess.run(
                ["nphonecli", "detect", "--json"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                # Try without --json
                r = subprocess.run(
                    ["nphonecli", "detect"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode != 0:
                    return None
                return self._parse_nphonecli_text(r.stdout)

            data = json.loads(r.stdout)
            return DeviceInfo(
                serial=data.get("serial", ""),
                model=data.get("model", ""),
                product=data.get("product", ""),
                firmware=data.get("firmware", ""),
                imei=data.get("imei", ""),
                chip=data.get("chip", ""),
                protocol=data.get("protocol", "ODIN"),
                raw=data,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        except json.JSONDecodeError as e:
            self._log(f"[nphonecli json parse error] {e}")
            return None

    def _parse_nphonecli_text(self, text: str) -> Optional[DeviceInfo]:
        info = DeviceInfo()
        patterns = {
            "model":    r"(?i)model[:\s]+(\S+)",
            "serial":   r"(?i)serial[:\s]+(\S+)",
            "product":  r"(?i)product[:\s]+(\S+)",
            "firmware": r"(?i)firmware[:\s]+(\S+)",
            "imei":     r"(?i)imei[:\s]+(\S+)",
        }
        found = False
        for attr, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                setattr(info, attr, m.group(1))
                found = True
        info.protocol = "ODIN"
        return info if found else None

    def _probe_odin4(self) -> Optional[DeviceInfo]:
        try:
            r = subprocess.run(
                ["odin4", "-d"],
                capture_output=True, text=True, timeout=5
            )
            out = r.stdout + r.stderr
            if "no device" in out.lower() or r.returncode not in (0, 1):
                return None
            info = DeviceInfo(protocol="ODIN4")
            m = re.search(r"(?i)serial[:\s]+(\S+)", out)
            if m:
                info.serial = m.group(1)
            m = re.search(r"(?i)model[:\s]+(\S+)", out)
            if m:
                info.model = m.group(1)
            return info
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _probe_heimdall(self) -> Optional[DeviceInfo]:
        try:
            r = subprocess.run(
                ["heimdall", "detect"],
                capture_output=True, text=True, timeout=5
            )
            if "device detected" in (r.stdout + r.stderr).lower():
                return DeviceInfo(protocol="HEIMDALL")
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        return self._device_info


# ── Flash engine ────────────────────────────────────────────────────────────

class FlashEngine:
    """
    Executes flash operations via nphonecli / odin4 / heimdall.
    Emits log lines and progress callbacks during operation.
    """

    def __init__(
        self,
        on_log:      Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_done:     Callable[[bool, str], None],
        backend:     FlashBackend = FlashBackend.AUTO,
    ):
        self.on_log      = on_log
        self.on_progress = on_progress
        self.on_done     = on_done
        self.backend     = detect_backend() if backend == FlashBackend.AUTO else backend
        self._proc       = None
        self._flash_thread = None
        self._abort_event  = threading.Event()

    def _log(self, msg: str):
        self.on_log(msg)

    def _progress(self, pct: float, label: str = ""):
        self.on_progress(pct, label)

    def flash(self, partitions: List[FlashPartition], options: FlashOptions):
        if not partitions:
            self._log("[error] No partitions selected for flashing.")
            self.on_done(False, "No partitions selected")
            return

        self._abort_event.clear()
        self._flash_thread = threading.Thread(
            target=self._run_flash,
            args=(partitions, options),
            daemon=True
        )
        self._flash_thread.start()

    def _run_flash(self, partitions: List[FlashPartition], options: FlashOptions):
        try:
            if self.backend == FlashBackend.NPHONECLI:
                ok, msg = self._flash_nphonecli(partitions, options)
            elif self.backend == FlashBackend.ODIN4:
                ok, msg = self._flash_odin4(partitions, options)
            elif self.backend == FlashBackend.HEIMDALL:
                ok, msg = self._flash_heimdall(partitions, options)
            else:
                ok, msg = False, "No flash backend available"
        except Exception as e:
            ok, msg = False, str(e)
        self.on_done(ok, msg)

    def _run_cmd(self, cmd: List[str]) -> bool:
        self._log(f"[exec] {' '.join(cmd)}")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        progress_re = re.compile(r'(\d+(?:\.\d+)?)\s*%')
        for line in self._proc.stdout:
            if self._abort_event.is_set():
                self._proc.terminate()
                return False
            line = line.rstrip()
            self._log(line)
            m = progress_re.search(line)
            if m:
                self._progress(float(m.group(1)))
        self._proc.wait()
        return self._proc.returncode == 0

    def _flash_nphonecli(self, partitions: List[FlashPartition], options: FlashOptions) -> tuple:
        cmd = ["nphonecli", "flash"]
        for p in partitions:
            if p.flag == "--pit":
                cmd += ["--pit", p.filepath]
            else:
                cmd += [p.flag, p.filepath]
        if not options.reboot:
            cmd.append("--no-reboot")
        if options.t_flash:
            cmd.append("--tflash")
        if options.efs_clear:
            cmd.append("--efs-clear")
        if options.bootloader_update:
            cmd.append("--bootloader-update")
        if options.reset_time:
            cmd.append("--reset-time")
        if options.verify:
            cmd.append("--verify")

        ok = self._run_cmd(cmd)
        return ok, "Flash complete" if ok else "Flash failed (see log)"

    def _flash_odin4(self, partitions: List[FlashPartition], options: FlashOptions) -> tuple:
        cmd = ["odin4"]
        flag_map = {"--bl": "-b", "--ap": "-a", "--cp": "-c", "--csc": "-s", "--userdata": "-u", "--pit": "--pit"}
        for p in partitions:
            odin_flag = flag_map.get(p.flag, p.flag)
            cmd += [odin_flag, p.filepath]
        if options.t_flash:
            cmd.append("--tflash")
        ok = self._run_cmd(cmd)
        return ok, "Flash complete" if ok else "Flash failed (see log)"

    def _flash_heimdall(self, partitions: List[FlashPartition], options: FlashOptions) -> tuple:
        # Heimdall requires specifying partition name mappings
        cmd = ["heimdall", "flash"]
        hl_map = {
            "--bl":       "BOOT",
            "--ap":       "SYSTEM",
            "--cp":       "MODEM",
            "--csc":      "CSC",
            "--userdata": "USERDATA",
        }
        for p in partitions:
            if p.flag == "--pit":
                cmd += ["--pit", p.filepath]
                continue
            part_name = p.name if p.name else hl_map.get(p.flag, p.flag.lstrip("-").upper())
            cmd += [f"--{part_name}", p.filepath]
        if not options.reboot:
            cmd.append("--no-reboot")

        ok = self._run_cmd(cmd)
        return ok, "Flash complete" if ok else "Flash failed (see log)"

    def abort(self):
        self._abort_event.set()
        if self._proc:
            self._proc.terminate()
        self._log("[aborted] Flash operation aborted by user.")

    def is_running(self) -> bool:
        return self._flash_thread is not None and self._flash_thread.is_alive()


# ── PIT operations ──────────────────────────────────────────────────────────

class PITManager:
    """Download and manage PIT files from connected device."""

    def __init__(
        self,
        on_log:    Callable[[str], None],
        backend:   FlashBackend = FlashBackend.AUTO,
    ):
        self.on_log  = on_log
        self.backend = detect_backend() if backend == FlashBackend.AUTO else backend

    def download_pit(self, output_path: str) -> bool:
        """Download PIT from device to output_path."""
        self.on_log(f"[pit] Downloading PIT to {output_path}")
        try:
            if self.backend == FlashBackend.NPHONECLI:
                cmd = ["nphonecli", "pit", "--download", output_path]
            elif self.backend == FlashBackend.ODIN4:
                cmd = ["odin4", "--pit-download", output_path]
            elif self.backend == FlashBackend.HEIMDALL:
                cmd = ["heimdall", "download-pit", "--output", output_path]
            else:
                self.on_log("[error] No backend available")
                return False

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()
            for line in out.splitlines():
                self.on_log(f"[pit] {line}")
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            self.on_log("[pit] Timeout downloading PIT")
            return False
        except FileNotFoundError as e:
            self.on_log(f"[pit] Binary not found: {e}")
            return False


# ── Reboot helpers ──────────────────────────────────────────────────────────

def reboot_device(mode: str = "normal", backend: FlashBackend = FlashBackend.AUTO, log: Callable = print):
    """
    Reboot connected device.
    mode: 'normal' | 'download' | 'recovery'
    """
    backend = detect_backend() if backend == FlashBackend.AUTO else backend
    if backend == FlashBackend.NPHONECLI:
        cmds = {
            "normal":   ["nphonecli", "reboot"],
            "download": ["nphonecli", "reboot", "--download"],
            "recovery": ["nphonecli", "reboot", "--recovery"],
        }
    elif backend == FlashBackend.HEIMDALL:
        cmds = {
            "normal":   ["heimdall", "close-pc-screen"],
            "download": ["heimdall", "reset"],
            "recovery": ["heimdall", "close-pc-screen"],
        }
    elif backend == FlashBackend.ODIN4:
        cmds = {
            "normal":   ["odin4", "--reboot"],
            "download": ["odin4", "--reboot"],
            "recovery": ["odin4", "--reboot"],
        }
    else:
        log("[reboot] No backend available")
        return

    cmd = cmds.get(mode, cmds["normal"])
    log(f"[reboot] {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        for line in (r.stdout + r.stderr).splitlines():
            log(f"[reboot] {line}")
    except Exception as e:
        log(f"[reboot] error: {e}")
