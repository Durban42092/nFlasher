"""nFlasher - Samsung device flash tool for Linux."""

from .pit     import PITFile, PITEntry, parse_pit, serialize_pit, pit_summary
from .backend import (
    DeviceManager, FlashEngine, PITManager,
    FlashBackend, FlashOptions, FlashPartition,
    DeviceInfo, DeviceState,
    detect_backend, backend_version, reboot_device,
)

__version__  = "1.0.0"
__author__   = "nFlasher"
__license__  = "GPL-3.0"
