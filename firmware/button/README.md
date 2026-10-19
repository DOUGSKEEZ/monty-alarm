# Button firmware (CH552E)

Firmware for the alarm's two single-key USB pads, replacing the factory firmware so the Pi can set their RGB LEDs. Each pad stays a plain boot keyboard that sends `a`, so `core/alarm_button_handler.py` works unchanged; `core/button_leds.py` sets the lights.

Based on [CAPS bLOCK](https://github.com/wagiminator/CH552-MouseWiggler) by Stefan Wagner (wagiminator): the USB stack, NeoPixel driver and helpers in `src/` are his, with small changes. Like the original, this firmware is licensed under [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/).

## Hardware
The pads are sold as "Mini 1-Key" macro keyboards (factory USB ID `8808:6600`, board marked `@1key_XGM`). Traced on 2026-10-19:

| CH552E pin | Port | Connected to |
| --- | --- | --- |
| 1 | P1.4 | Key switch, to GND (pressed = low) |
| 2 | P1.5 | Addressable RGB LED data (GRB order), through R3 |
| 3, 4 | P1.6, P1.7 | Nothing |
| 5 | RST | Reset (enabled in the chip's config) |
| 6, 7 | P3.6, P3.7 | USB D+, D− |
| 8, 9, 10 | GND, VCC, V33 | Power; the 3.3 V pad is the bottom of C5 |

## What it does
- USB `1209:0001` (the [pid.codes](https://pid.codes) test PID, for private use), product "Monty Alarm Button", one boot keyboard interface (`:1.0`).
- Sends `a` while the key is held (5 ms debounce).
- LED off at power-up, after a 0.3 s dim green blink that shows the firmware is running.
- Vendor control requests on endpoint 0 (no driver needed; `core/button_leds.py` sends them through usbfs):

| Request | Type | wValue | wIndex | Data |
| --- | --- | --- | --- | --- |
| `0x10` SET_LED | `0x40` | R \| G << 8 | B \| effect << 8 | none. Effects: 0 solid, 1 breathe (2.56 s), 2 blink (1 s), 3 fast blink (1/8 s) |
| `0x11` GET_INFO | `0xC0` | 0 | 0 | 8 bytes: `'M'`, version major, minor, R, G, B, effect, key down |
| `0x1B` BOOTLOADER | `0x40` | 0 | 0 | none. Detaches and jumps to the WCH bootloader (`4348:55e0`) |

## Build
```bash
sudo apt install sdcc   # 4.2.0 on Raspberry Pi OS 12
make bin                # -> button.bin
```

## Update a pad that already runs this firmware
The bootloader waits 60 s for a flash, then starts the firmware again. Needs [wchisp](https://github.com/ch32-rs/wchisp) (a prebuilt release is in `~/.local/bin/wchisp` on the Pi) and `uhubctl` (apt). `wchisp` and `button_leds.py` need no sudo: the udev rule installed by `scripts/install.sh` gives the `plugdev` group both the firmware's `1209:0001` and the bootloader's `4348:55e0`.
```bash
python3 core/button_leds.py boot 1.4                 # 1.4 = Snooze, 1.3 = Check
~/.local/bin/wchisp flash firmware/button/button.bin  # within 60 s
# The pad restarts without the Pi noticing, so it stays listed as 4348:55e0.
# Power-cycle the USB ports (all four switch together on a Pi 4):
sudo uhubctl -l 2 -a off; sudo uhubctl -l 1-1 -a off; sleep 2
sudo uhubctl -l 2 -a on;  sudo uhubctl -l 1-1 -a on
python3 core/button_leds.py info                     # check the new version
```

## First flash, or recovery
A pad with the factory firmware, or one whose firmware doesn't answer, needs the bootloader entered by hand. The CH552's bootloader (v2.50 here) starts when D+ is pulled up at power-on:

1. Open the pad and lay the board chip side up, with its cable in the Pi.
2. Cut the Pi's USB power: `sudo uhubctl -l 2 -a off; sudo uhubctl -l 1-1 -a off`.
3. Hold a 10 kΩ resistor from the bottom of C5 (3.3 V) to the chip's D+ pin (pin 6: with pin 1's dot at the bottom right, it's the top-left pin). **Never connect D+ to 5 V.**
4. Switch the power back on (`-a on`) and keep holding for 3 s. `lsusb` shows `4348:55e0`.
5. Flash within 60 s, as above, then power-cycle the ports.

The factory firmware is read-protected, so there's no way back to it once a pad is flashed.
