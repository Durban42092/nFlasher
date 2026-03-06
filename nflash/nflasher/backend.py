from __future__ import annotations
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
from typing import Optional, Callable, Dict
from enum import Enum, auto

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

# Rest of existing code ...
# Change type hints in FlashEngine methods to use string references for forward declaration.
# Example for flash method:
# def flash(self, partitions: list["FlashPartition"], options: "FlashOptions"):
# Repeat for _run_flash, _flash_nphonecli, _flash_odin4, _flash_heimdall.
# If any other methods use forward refs, update as needed.
