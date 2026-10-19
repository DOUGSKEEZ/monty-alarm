#!/usr/bin/env python3
"""
Button lights for the Monty alarm
Follows the alarm's state (signals/alarm_display.txt) and sets each button's
LED to its look in settings.BUTTON_LIGHTS. Runs as button-leds.service, apart
from the alarm, so a light problem can never stop the alarm ringing.
Talks to the buttons' own firmware (firmware/button/) with USB vendor requests;
pads with the factory firmware (8808:6600) are never touched.

  python3 core/button_leds.py watch            # what the service runs
  python3 core/button_leds.py info
  python3 core/button_leds.py set 1.4 255 0 0 [solid|breathe|blink|fast]
  python3 core/button_leds.py off [1.4]
  python3 core/button_leds.py boot 1.4         # bootloader, for reflashing

Pads are named by USB port as in settings.py: 1.4 is Snooze, 1.3 is Check.
Needs write access to /dev/bus/usb: user pi gets it from the udev rule that
scripts/install.sh installs (firmware/button/99-monty-buttons.rules).
"""

import ctypes
import fcntl
import os
import sys
import time
from pathlib import Path

import settings
from statefiles import read_display

VENDOR_ID, PRODUCT_ID = 0x1209, 0x0001   # pid.codes test PID, see firmware/button/src/config.h
PRODUCT_NAME = "Monty Alarm Button"

REQ_SET_LED, REQ_GET_INFO, REQ_BOOTLOADER = 0x10, 0x11, 0x1B
MODES = {"solid": 0, "breathe": 1, "blink": 2, "fast": 3}

USB_DEVICES = Path("/sys/bus/usb/devices")
USB_HUB = "1-1"     # The Pi 4's internal hub; port 1.4 is sysfs device 1-1.4
POLL_SECONDS = 0.5  # How often watch() checks the alarm state


class CtrlTransfer(ctypes.Structure):
    """struct usbdevfs_ctrltransfer from linux/usbdevice_fs.h"""
    _fields_ = [("bRequestType", ctypes.c_uint8), ("bRequest", ctypes.c_uint8),
                ("wValue", ctypes.c_uint16), ("wIndex", ctypes.c_uint16),
                ("wLength", ctypes.c_uint16), ("timeout", ctypes.c_uint32),
                ("data", ctypes.c_void_p)]


# _IOWR('U', 0, struct usbdevfs_ctrltransfer)
USBDEVFS_CONTROL = (3 << 30) | (ctypes.sizeof(CtrlTransfer) << 16) | (ord("U") << 8)


def find_pads():
    """Map port ("1.4") to sysfs dir for every pad running our firmware"""
    pads = {}
    for dev in USB_DEVICES.glob(f"{USB_HUB}.*"):
        try:
            if (int((dev / "idVendor").read_text(), 16) == VENDOR_ID
                    and int((dev / "idProduct").read_text(), 16) == PRODUCT_ID
                    and (dev / "product").read_text().strip() == PRODUCT_NAME):
                pads[dev.name.split("-", 1)[1]] = dev  # "1-1.4" -> "1.4"
        except (OSError, ValueError):
            continue  # Unplugged mid-scan, or an interface entry
    return pads


def device_node(dev):
    return f"/dev/bus/usb/{int((dev / 'busnum').read_text()):03d}/{int((dev / 'devnum').read_text()):03d}"


def control(dev, request_type, request, value=0, index=0, length=0):
    """Send one control request to a pad; returns the bytes it sent back"""
    buf = ctypes.create_string_buffer(max(length, 1))
    xfer = CtrlTransfer(request_type, request, value, index, length, 1000,
                        ctypes.cast(buf, ctypes.c_void_p) if length else None)
    fd = os.open(device_node(dev), os.O_RDWR)
    try:
        received = fcntl.ioctl(fd, USBDEVFS_CONTROL, xfer)
    finally:
        os.close(fd)
    return buf.raw[:received] if length else b""


def set_led(dev, r, g, b, effect="solid"):
    control(dev, 0x40, REQ_SET_LED, value=r | g << 8, index=b | MODES[effect] << 8)


def get_info(dev):
    data = control(dev, 0xC0, REQ_GET_INFO, length=8)
    if len(data) != 8 or data[0] != ord("M"):
        raise OSError(f"unexpected GET_INFO reply {data.hex()}")
    effect = {v: k for k, v in MODES.items()}.get(data[6], data[6])
    return {"version": f"{data[1]}.{data[2]}", "rgb": tuple(data[3:6]),
            "effect": effect, "key_down": bool(data[7])}


def enter_bootloader(dev):
    control(dev, 0x40, REQ_BOOTLOADER)


def alarm_state(display):
    """'ringing', 'snoozing' or 'idle' from the alarm's display text"""
    if display == "WAKE!":
        return "ringing"
    if display.startswith("SNZ"):
        return "snoozing"
    return "idle"


def watch():
    """Keep both lights matching the alarm state, forever"""
    for looks in settings.BUTTON_LIGHTS.values():
        for _, effect in looks.values():
            if effect not in MODES:
                raise SystemExit(f"Unknown light effect {effect!r} in settings.BUTTON_LIGHTS")
    roles = {settings.SNOOZE_PORT: "snooze", settings.CHECK_PORT: "check"}
    print(f"💡 Button lights: Snooze on USB {settings.SNOOZE_PORT}, Check on USB {settings.CHECK_PORT}")

    state, stopped_until = None, 0.0
    shown = {}       # port -> (device node, look) last sent; a replugged pad gets a new node
    failing = set()  # ports whose last request failed, so each failure is logged once
    while True:
        new_state = alarm_state(read_display())
        if new_state != state:
            if state in ("ringing", "snoozing") and new_state == "idle":
                stopped_until = time.monotonic() + settings.STOPPED_LIGHT_SECONDS
                print("💡 Alarm ended")
            else:
                print(f"💡 Alarm {new_state}")
            state = new_state
        look_name = "stopped" if state == "idle" and time.monotonic() < stopped_until else state

        for port, dev in find_pads().items():
            role = roles.get(port)
            if not role:
                continue
            look = settings.BUTTON_LIGHTS[look_name][role]
            try:
                sent = (device_node(dev), look)
                if shown.get(port) == sent:
                    continue
                (r, g, b), effect = look
                set_led(dev, r, g, b, effect)
                shown[port] = sent
                if port in failing:
                    print(f"✅ {role} light on USB {port} working again")
                    failing.discard(port)
            except OSError as e:
                if port not in failing:
                    print(f"⚠️ {role} light on USB {port}: {e} (retrying)")
                    failing.add(port)
        time.sleep(POLL_SECONDS)


def main(argv):
    if len(argv) < 2 or argv[1] not in ("watch", "info", "set", "off", "boot"):
        print(__doc__.strip())
        return 2
    command, args = argv[1], argv[2:]
    if command == "watch":
        watch()
        return 0

    pads = find_pads()
    if command == "info":
        if not pads:
            print("No pads with the Monty firmware found")
            return 1
        for port, dev in sorted(pads.items()):
            print(f"{port}: {get_info(dev)}")
        return 0

    targets = [args[0]] if args else (sorted(pads) if command == "off" else [])
    if not targets or any(port not in pads for port in targets):
        print(f"Name a port with the Monty firmware: {', '.join(sorted(pads)) or 'none found'}")
        return 1

    for port in targets:
        if command == "set":
            r, g, b = (int(v) for v in args[1:4])
            set_led(pads[port], r, g, b, args[4] if len(args) > 4 else "solid")
        elif command == "off":
            set_led(pads[port], 0, 0, 0)
        elif command == "boot":
            enter_bootloader(pads[port])
            print(f"{port}: sent to the bootloader (4348:55e0 for 60 s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
