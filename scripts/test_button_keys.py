#!/usr/bin/env python3
"""
Print every key event from the two alarm buttons, to check which is which.
Stop the button service first (it grabs the buttons):
    sudo systemctl stop alarm-buttons.service
    python3 scripts/test_button_keys.py
    sudo systemctl start alarm-buttons.service
"""

import asyncio
import sys
from pathlib import Path

from evdev import InputDevice, ecodes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'core'))
import settings

VALUES = {1: "PRESS", 0: "RELEASE", 2: "REPEAT"}


async def monitor_device(path, name):
    try:
        device = InputDevice(path)
    except OSError as e:
        print(f"❌ {name}: cannot open {path}: {e}")
        return
    print(f"📟 {name}: {device.name} at {path}")
    async for event in device.async_read_loop():
        if event.type == ecodes.EV_KEY:
            key = ecodes.KEY.get(event.code, f"UNKNOWN({event.code})")
            print(f"   {name}: {key} {VALUES.get(event.value, event.value)}")


async def main():
    print("🔍 Press the buttons and watch the key codes (Ctrl+C to quit)")
    await asyncio.gather(
        *(monitor_device(path, "SNOOZE") for path in settings.SNOOZE_DEVICES),
        *(monitor_device(path, "CHECK") for path in settings.CHECK_DEVICES),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
