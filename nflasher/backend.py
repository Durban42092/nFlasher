"""
nphonekit / nphonecli wrapper layer.

Provides async subprocess management, device detection,
PIT download, and partition flashing using nphonecli.
Fallback: raw libusb via pyusb for direct Odin4 protocol.

nphonecli protocol reference:
  https://github.com/Samsung-Lsm/nphone (community reverse)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

DEFAULT_NPHONECLI = "nphonecli"
DEFAULT_HEIMDALL  = "heimdall"
DEFAULT_ODIN4     = "odin4"


# ── Enums ─────────────────────────────────────────────────────────────────────

class DeviceState(Enum):
    DISCONNECTED = auto()
    DETECTED     = auto()
    CONNECTED    = auto()
    DOWNLOADING  = auto()
    ERROR        = auto()


class FlashBackend(Enum):
    NPHONECLI = "nphonecli"
    HEIMDALL  = "heimdall"
    ODIN4     = "odin4"
    AUTO      = "auto"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class DeviceInfo:
    serial:   str  = ""
    model:    str  = ""
    product:  str  = ""
    firmware: str  = ""
    imei:     str  = ""
    chip:     str  = ""
    protocol: str  = ""
    raw:      dict = field(default_factory=dict)

    def __str__(self) -> str:
        parts = []
        if self.model:
            parts.append(f"Model: {self.model}")
        if self.product:
            parts.append(f"Product: {self.product}")
        if self.firmware:
            parts.append(f"Firmware: {self.firmware}")
        if self.serial:
            parts.append(f"Serial: {self.serial}")
        if self.chip:
            parts.append(f"Chip: {self.chip}")
        if self.imei:
            parts.append(f"IMEI: {self.imei}")
        if self.protocol:
            parts.append(f"Protocol: {self.protocol}")
        return "\n".join(parts) if parts else "Unknown Device"


@dataclass
class FlashPartition:
    flag:     str       # --bl, --ap, --cp, --csc, --userdata, --pit
    filepath: str
    name:     str = ""  # partition name override (heimdall)


@dataclass
class FlashOptions:
    reboot:            bool = True
    t_flash:           bool = False
    efs_clear:         bool = False
    bootloader_update: bool = False
    reset_time:        bool = False
    flash_lock:        bool = False
    verify:            bool = False
    resume:            bool = False


# ── Backend helpers ───────────────────────────────────────────────────────────

def detect_backend() -> FlashBackend:
    """Return the first available flash backend found on PATH."""
    for backend, cmd in [
        (FlashBackend.NPHONECLI, DEFAULT_NPHONECLI),
        (FlashBackend.ODIN4,     DEFAULT_ODIN4),
        (FlashBackend.HEIMDALL,  DEFAULT_HEIMDALL),
    ]:
        if shutil.which(cmd):
            return backend
    return FlashBackend.NPHONECLI


def backend_version(backend: FlashBackend) -> str:
    """Return version string for the given backend binary."""
    cmd_map: dict[FlashBackend, list[str]] = {
        FlashBackend.NPHONECLI: [DEFAULT_NPHONECLI, "--version"],
        FlashBackend.ODIN4:     [DEFAULT_ODIN4,     "--version"],
        FlashBackend.HEIMDALL:  [DEFAULT_HEIMDALL,  "--version"],  # heimdall uses --version
    }
    cmd = cmd_map.get(backend)
    if not cmd:
        return "unknown"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except Exception:
        return "not found"


def reboot_device(
    mode:    str,
    backend: FlashBackend,
    log_fn:  Callable[[str], None],
) -> None:
    """Reboot the connected device into the specified mode."""
    cmd_map: dict[FlashBackend, dict[str, list[str]]] = {
        FlashBackend.NPHONECLI: {
            "normal":   [DEFAULT_NPHONECLI, "reboot"],
            "download": [DEFAULT_NPHONECLI, "reboot", "--download"],
            "recovery": [DEFAULT_NPHONECLI, "reboot", "--recovery"],
        },
        FlashBackend.HEIMDALL: {
            "normal":   [DEFAULT_HEIMDALL, "reset"],
            "download": [DEFAULT_HEIMDALL, "download-mode"],
            "recovery": [DEFAULT_HEIMDALL, "reset"],
        },
        # odin4 is flash-only; reboot is handled by nphonecli/heimdall
        FlashBackend.ODIN4: {
            "normal":   [DEFAULT_NPHONECLI, "reboot"],
            "download": [DEFAULT_NPHONECLI, "reboot", "--download"],
            "recovery": [DEFAULT_NPHONECLI, "reboot", "--recovery"],
        },
    }
    cmd = cmd_map.get(backend, {}).get(mode)
    if not cmd:
        log_fn(f"[reboot] Unknown mode or backend: {mode} / {backend.value}")
        return
    try:
        subprocess.run(cmd, timeout=15)
        log_fn(f"[reboot] Reboot ({mode}) complete.")
    except Exception as exc:
        log_fn(f"[reboot] Error: {exc}")


# ── FlashEngine ───────────────────────────────────────────────────────────────

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
        self._proc         = None
        self._flash_thread = None
        self._abort_event  = threading.Event()

    def _log(self, msg: str) -> None:
        self.on_log(msg)

    def _progress(self, pct: float, label: str = "") -> None:
        self.on_progress(pct, label)

    def flash(self, partitions: list[FlashPartition], options: FlashOptions) -> None:
        if not partitions:
            self._log("[error] No partitions selected for flashing.")
            self.on_done(False, "No partitions selected")
            return

        self._abort_event.clear()
        self._flash_thread = threading.Thread(
            target=self._run_flash,
            args=(partitions, options),
            daemon=True,
        )
        self._flash_thread.start()

    def _run_flash(self, partitions: list[FlashPartition], options: FlashOptions) -> None:
        # Guard here too — tests may call _run_flash directly
        if not partitions:
            self.on_done(False, "No partitions selected")
            return
        try:
            if self.backend == FlashBackend.NPHONECLI:
                ok, msg = self._flash_nphonecli(partitions, options)
            elif self.backend == FlashBackend.ODIN4:
                ok, msg = self._flash_odin4(partitions, options)
            elif self.backend == FlashBackend.HEIMDALL:
                ok, msg = self._flash_heimdall(partitions, options)
            else:
                ok, msg = False, "No flash backend available"
        except Exception as exc:
            ok, msg = False, str(exc)
        self.on_done(ok, msg)

    def _run_cmd(self, cmd: list[str]) -> bool:
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

    def _flash_nphonecli(
        self, partitions: list[FlashPartition], options: FlashOptions
    ) -> tuple[bool, str]:
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

    def _flash_odin4(
        self, partitions: list[FlashPartition], options: FlashOptions
    ) -> tuple[bool, str]:
        cmd = ["odin4"]
        flag_map = {
            "--bl": "-b", "--ap": "-a", "--cp": "-c",
            "--csc": "-s", "--userdata": "-u", "--pit": "--pit",
        }
        for p in partitions:
            odin_flag = flag_map.get(p.flag, p.flag)
            cmd += [odin_flag, p.filepath]
        if options.t_flash:
            cmd.append("--tflash")
        ok = self._run_cmd(cmd)
        return ok, "Flash complete" if ok else "Flash failed (see log)"

    def _flash_heimdall(
        self, partitions: list[FlashPartition], options: FlashOptions
    ) -> tuple[bool, str]:
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

    def abort(self) -> None:
        self._abort_event.set()
        if self._proc:
            self._proc.terminate()
        self._log("[aborted] Flash operation aborted by user.")

    def is_running(self) -> bool:
        return self._flash_thread is not None and self._flash_thread.is_alive()


# ── PITManager ────────────────────────────────────────────────────────────────

class PITManager:
    """Downloads PIT partition tables from a connected device."""

    def __init__(self, on_log: Callable[[str], None], backend: FlashBackend):
        self.on_log  = on_log
        self.backend = backend

    def download_pit(self, dest_path: str) -> bool:
        cmd_map: dict[FlashBackend, list[str]] = {
            FlashBackend.NPHONECLI: [DEFAULT_NPHONECLI, "pit", "--save", dest_path],
            FlashBackend.HEIMDALL:  [DEFAULT_HEIMDALL,  "download", "--pit", dest_path],
            # odin4 does not support standalone PIT download; fall back to nphonecli
            FlashBackend.ODIN4:     [DEFAULT_NPHONECLI, "pit", "--save", dest_path],
        }
        cmd = cmd_map.get(self.backend)
        if not cmd:
            self.on_log("[pit] Backend does not support PIT download")
            return False
        try:
            self.on_log(f"[pit] {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                self.on_log(f"[pit] Error: {result.stderr.strip()}")
            return result.returncode == 0
        except Exception as exc:
            self.on_log(f"[pit] Exception: {exc}")
            return False


# ── DeviceManager ─────────────────────────────────────────────────────────────

class DeviceManager:
    """Polls for Samsung devices in Download Mode and emits state changes."""

    POLL_INTERVAL = 2.0

    def __init__(
        self,
        on_state_change: Callable[[DeviceState, DeviceInfo | None], None],
        on_log:          Callable[[str], None],
        backend:         FlashBackend,
    ):
        self.on_state_change = on_state_change
        self.on_log          = on_log
        self.backend         = backend
        self.state           = DeviceState.DISCONNECTED
        self._poll_thread    = None
        self._stop_event     = threading.Event()

    def start_polling(self) -> None:
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_polling(self) -> None:
        self._stop_event.set()

    def _poll_loop(self) -> None:
        # Poll immediately on start, then on each interval
        while not self._stop_event.is_set():
            new_state, info = self._detect_device()
            if new_state != self.state:
                self.state = new_state
                self.on_state_change(new_state, info)
            self._stop_event.wait(self.POLL_INTERVAL)

    def _detect_device(self) -> tuple[DeviceState, DeviceInfo | None]:
        probe_map: dict[FlashBackend, Callable[[], DeviceInfo | None]] = {
            FlashBackend.NPHONECLI: self._probe_nphonecli,
            FlashBackend.ODIN4:     self._probe_nphonecli,  # odin4 has no device-info cmd
            FlashBackend.HEIMDALL:  self._probe_heimdall,
        }
        probe = probe_map.get(self.backend, self._probe_nphonecli)
        info = probe()
        if info is not None:
            return DeviceState.CONNECTED, info
        return DeviceState.DISCONNECTED, None

    def _probe_nphonecli(self) -> DeviceInfo | None:
        """
        Try JSON output first (nphonecli devices --json), fall back to
        plain-text parsing if the --json flag is not supported.
        Returns None if no device is found or binary is unavailable.
        """
        # --- attempt 1: structured JSON ---
        try:
            result = subprocess.run(
                [DEFAULT_NPHONECLI, "devices", "--json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                return DeviceInfo(
                    serial   = data.get("serial",   ""),
                    model    = data.get("model",    ""),
                    product  = data.get("product",  ""),
                    firmware = data.get("firmware", ""),
                    imei     = data.get("imei",     ""),
                    chip     = data.get("chip",     ""),
                    protocol = data.get("protocol", "ODIN"),
                    raw      = data,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        except (json.JSONDecodeError, KeyError):
            pass  # fall through to text probe

        # --- attempt 2: plain-text fallback ---
        try:
            result = subprocess.run(
                [DEFAULT_NPHONECLI, "devices"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            info = DeviceInfo(protocol="ODIN")
            for line in result.stdout.splitlines():
                key, _, val = line.partition(":")
                val = val.strip()
                key = key.strip().lower()
                if key == "model":
                    info.model = val
                elif key == "serial":
                    info.serial = val
                elif key == "firmware":
                    info.firmware = val
                elif key == "product":
                    info.product = val
                elif key == "chip":
                    info.chip = val
                elif key == "imei":
                    info.imei = val
            return info if (info.model or info.serial) else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _probe_heimdall(self) -> DeviceInfo | None:
        """Run `heimdall detect` and return a basic DeviceInfo on success."""
        try:
            result = subprocess.run(
                [DEFAULT_HEIMDALL, "detect"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return DeviceInfo(protocol="HEIMDALL")
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
