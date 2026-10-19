#!/usr/bin/env python3
"""
Shared settings for the Monty Alarm Clock
Every path, address and tuning value lives here so server.py,
alarm_trigger.py and alarm_button_handler.py always agree.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Monty backend. Set MONTY_URL in the environment to override.
MONTY_URL = os.environ.get("MONTY_URL", "http://192.168.10.15:3001")
SYNC_INTERVAL_SECONDS = 3600  # Ask Monty to re-push its schedule this often
SYNC_RETRY_SECONDS = 60       # ...or this often while Monty can't be reached

# Files the processes share
ALARM_STATE_FILE = BASE_DIR / "alarm_state.json"      # Pushed schedule (written only by server.py)
TRIGGER_STATE_FILE = BASE_DIR / "trigger_state.json"  # Last alarm handled (written only by alarm_trigger.py)
WAKEUP_CONFIG_FILE = BASE_DIR / "wakeup_config.json"  # Wake-up mode and MP3 track
MUSIC_DIR = BASE_DIR / "music"
SIGNALS_DIR = BASE_DIR / "signals"
SNOOZE_SIGNAL = SIGNALS_DIR / "alarm_snooze"
STOP_SIGNAL = SIGNALS_DIR / "alarm_stop"
DISPLAY_FILE = SIGNALS_DIR / "alarm_display.txt"      # WAKE!, SNZ HH:MM or empty, until there's a real display

# Buttons. Both run our firmware (firmware/button/: USB 1209:0001, one keyboard
# interface :1.0 that sends KEY_A) and look identical, so /dev/input/by-id
# can't tell them apart. by-path names the USB port instead: swap the plugs
# and the buttons swap.
SNOOZE_PORT = "1.4"
CHECK_PORT = "1.3"
_USB_PORT = "/dev/input/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0"
SNOOZE_DEVICES = [f"{_USB_PORT}:{SNOOZE_PORT}:1.0-event-kbd"]
CHECK_DEVICES = [f"{_USB_PORT}:{CHECK_PORT}:1.0-event-kbd"]
LONG_PRESS_SECONDS = 1.5  # Hold Check this long to stop the alarm

# Button lights, set by core/button_leds.py from the alarm's state. Each look is
# ((R, G, B), effect): R, G, B are 0-255 and effect is "solid", "breathe",
# "blink" (1 s on/off) or "fast" (1/8 s on/off).
_OFF = ((0, 0, 0), "solid")
_ENDED = ((160, 0, 140), "fast")  # Pink/purple: the alarm just ended
BUTTON_LIGHTS = {
    "idle":     {"snooze": _OFF, "check": _OFF},
    "ringing":  {"snooze": ((0, 200, 0), "breathe"), "check": ((120, 0, 0), "solid")},
    "snoozing": {"snooze": ((90, 35, 0), "solid"), "check": ((120, 0, 0), "solid")},
    "stopped":  {"snooze": _ENDED, "check": _ENDED},
}
STOPPED_LIGHT_SECONDS = 3  # How long "stopped" shows before the lights go off

# Audio goes straight to ALSA (see audio/asound.conf). PulseAudio is masked
# by scripts/install.sh: it only ran while someone was logged in, and then it
# took over ALSA's default device.
AUDIO_CARD = "ZD3"        # ALSA card id of the Fosi Audio ZD3 on USB
VOLUME_CONTROL = "Alarm"  # softvol control defined in audio/asound.conf
MIN_VOLUME = 10           # Volume ramp start (%)
MAX_VOLUME = 35           # Volume ramp end (%)
VOLUME_RAMP_SECONDS = 10
DEFAULT_MP3 = "THE_HIT.mp3"  # MP3 mode with no track chosen, and the fallback when Pandora fails
PANDORA_START_SECONDS = 20   # Fall back to the MP3 if Pandora hasn't started a song by then

# Alarm timing
CHECK_INTERVAL = 1           # Seconds between schedule checks
LATE_GRACE_MINUTES = 15      # Still ring if the Pi was down at alarm time and is back within this
SNOOZE_MINUTES = 9
ALARM_DURATION_MINUTES = 60  # Auto-stop after this long
