# nFlasher

**Samsung device flash tool for Linux** — GTK4 frontend unifying `nphonecli`, `odin4`, and `heimdall` backends into a single polished GUI.

```
 ███╗   ██╗███████╗██╗      █████╗ ███████╗██╗  ██╗███████╗██████╗
 ████╗  ██║██╔════╝██║     ██╔══██╗██╔════╝██║  ██║██╔════╝██╔══██╗
 ██╔██╗ ██║█████╗  ██║     ███████║███████╗███████║█████╗  ██████╔╝
 ██║╚██╗██║██╔══╝  ██║     ██╔══██║╚════██║██╔══██║██╔══╝  ██╔══██╗
 ██║ ╚████║██║     ███████╗██║  ██║███████║██║  ██║███████╗██║  ██║
 ╚═╝  ╚═══╝╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
```

---

## Features

| Feature | nFlasher | Heimdall-Frontend | Odin4 |
|---------|----------|-------------------|-------|
| Partition slots (BL/AP/CP/CSC/USERDATA) | ✅ | ✅ | ✅ |
| PIT download from device | ✅ | ✅ | ❌ |
| PIT parse + viewer | ✅ | ✅ | ❌ |
| PIT save/export | ✅ | ✅ | ❌ |
| Live log output | ✅ | ✅ | ✅ |
| Progress tracking | ✅ | ✅ | ✅ |
| T-Flash / EFS Clear options | ✅ | ❌ | ✅ |
| Reboot modes (normal/download/recovery) | ✅ | ✅ | ❌ |
| Backend hot-swap (nphonecli/odin4/heimdall) | ✅ | ❌ | ❌ |
| Device auto-detection polling | ✅ | ✅ | ✅ |
| GTK4 / libadwaita UI | ✅ | GTK2/3 | Qt5 |

---

## Installation

### 1. Install system dependencies

```bash
# Debian / Ubuntu / Mint
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 libgirepository1.0-dev python3-dev

# Fedora / RHEL
sudo dnf install python3-gobject python3-gobject-devel gtk4 libadwaita

# Arch Linux
sudo pacman -S python-gobject gtk4 libadwaita
```

### 2. Install a flash backend (at least one required)

```bash
# nphonecli — recommended
git clone https://github.com/Samsung-Lsm/nphone
cd nphone && make && sudo make install

# OR: odin4 (AUR / prebuilt)
yay -S odin4-bin          # Arch
# or download from: https://github.com/Benjamin-Dobell/Heimdall

# OR: heimdall (widely packaged)
sudo apt install heimdall-flash    # Debian/Ubuntu
sudo pacman -S heimdall            # Arch
```

### 3. Install nFlasher

```bash
git clone https://github.com/nflasher/nflasher
cd nflasher

pip install -e .             # editable install
# OR
pip install .
```

### 4. Configure USB permissions

```bash
sudo cp data/99-nflasher-samsung.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev $USER   # log out and back in
```

---

## Usage

```bash
nflasher           # Launch GUI
python -m nflasher # Alternatively
```

### Flash Procedure

1. Put your Samsung device into **Download Mode**:
   - **Older (physical Home button)**: Power + Vol Down + Home
   - **Newer (Bixby button)**: Power + Vol Down + Bixby
   - **Newer (no dedicated button)**: Power + Vol Down (long press)
2. Connect via USB
3. nFlasher detects the device automatically (green indicator)
4. Select partition files using the **Browse** buttons
5. Set options in the **OPTIONS** tab if needed
6. Click **▶ START**

### PIT Management

- **Download PIT from Device** — pulls partition table from connected device
- **Open Local PIT** — parse and inspect a .pit file on disk
- **Save PIT** — export parsed PIT back to binary

---

## Architecture

```
nflasher/
├── __init__.py        — public API
├── __main__.py        — python -m nflasher entry
├── pit.py             — PIT v1/v2 binary parser + serializer
├── backend.py         — DeviceManager, FlashEngine, PITManager wrappers
│                         for nphonecli / odin4 / heimdall
└── ui.py              — GTK4 / libadwaita frontend
```

### Backend selection priority

```
nphonecli  →  odin4  →  heimdall  (first found on $PATH wins)
```

Switch at runtime via **OPTIONS → Backend**.

### nphonecli command mapping

| nFlasher action | nphonecli command |
|-----------------|-------------------|
| Detect device | `nphonecli detect --json` |
| Flash BL | `nphonecli flash --bl BL.tar.md5` |
| Flash AP | `nphonecli flash --ap AP.tar.md5` |
| Flash CP | `nphonecli flash --cp CP.tar.md5` |
| Flash CSC | `nphonecli flash --csc CSC.tar.md5` |
| Flash USERDATA | `nphonecli flash --userdata USERDATA.img` |
| Download PIT | `nphonecli pit --download device.pit` |
| Reboot | `nphonecli reboot [--download] [--recovery]` |

---

## PIT Binary Format

```
Header (28 bytes):
  u32 magic       = 0x12349876
  u32 entry_count
  u32 unknown[5]

Entry v1 (132 bytes) / v2 (136 bytes):
  u32 binary_type   (0=PHONE_BOOT 1=PDA 2=MODEM 3=CSC 4=USERDATA)
  u32 device_type   (0=ONENAND 1=NAND 2=MOVINAND 3=EMMC ...)
  u32 identifier
  u32 attributes    (filesystem flags)
  u32 update_attrib
  u32 block_size
  u32 block_count
  u32 file_offset   (v1 only)
  u32 file_size
  char partition_name[32]
  char flash_filename[32]
  char fota_filename[32]
```

---

## License

GPL-3.0 — see [LICENSE](LICENSE)

Compatible with and inspired by:
- [Heimdall](https://github.com/Benjamin-Dobell/Heimdall) (MIT)
- [odin4](https://github.com/amo12937/odin4) (GPL)
- [nphonekit](https://github.com/Samsung-Lsm/nphone) (Apache-2.0)
