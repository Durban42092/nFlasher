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
from typing import Optional, Callable, Dict # List removed
from enum import Enum, auto

# ... original code unchanged until ...

class FlashEngine:
    """
    Executes flash operations via nphonecli / odin4 / heimdall.
    Emits log lines and progress callbacks during operation.
    """

    def __init__(self,
        on_log: Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_done: Callable[[bool, str], None],
        backend: FlashBackend = FlashBackend.AUTO,
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

    def flash(self, partitions: list[FlashPartition], options: FlashOptions):
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

    def _run_flash(self, partitions: list[FlashPartition], options: FlashOptions):
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

    def _flash_nphonecli(self, partitions: list[FlashPartition], options: FlashOptions) -> tuple:
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

    def _flash_odin4(self, partitions: list[FlashPartition], options: FlashOptions) -> tuple:
        cmd = ["odin4"]
        flag_map = {"--bl": "-b", "--ap": "-a", "--cp": "-c", "--csc": "-s", "--userdata": "-u", "--pit": "--pit"}
        for p in partitions:
            odin_flag = flag_map.get(p.flag, p.flag)
            cmd += [odin_flag, p.filepath]
        if options.t_flash:
            cmd.append("--tflash")
        ok = self._run_cmd(cmd)
        return ok, "Flash complete" if ok else "Flash failed (see log)"

    def _flash_heimdall(self, partitions: list[FlashPartition], options: FlashOptions) -> tuple:
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

# ...rest of the code unchanged ...