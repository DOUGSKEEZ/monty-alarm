#!/usr/bin/env python3
"""
Speaker power for the Monty alarm
Relay 1 on the HL-52S module (IN1 on GPIO 4, active-low) switches 12 V from
an MT3608 boost module into the Fosi ZD3's Trigger In. The ZD3 wakes, appears
on USB about 4 s later and passes the trigger on to the ZA3 amp.

  python3 core/speakers.py on
  python3 core/speakers.py off
  python3 core/speakers.py status

On drives the pin low; off lets go of it (input with pull-up), which releases
the relay fully even though the module's inputs sit at 5 V. Uses pinctrl, so
the state stays put after this exits. Needs the gpio group (user pi has it).
"""

import re
import subprocess
import sys

import settings

# pinctrl get 4 -> " 4: op -- pu | lo // GPIO4 = output"
PINCTRL_LINE = re.compile(r'^\s*\d+:\s+(\w+)\b.*\|\s*(hi|lo)\b')


def relay_on_from_pinctrl(line):
    """True if pinctrl's line shows the pin driven low (relay on)"""
    match = PINCTRL_LINE.match(line)
    return bool(match) and match.group(1) == 'op' and match.group(2) == 'lo'


def pinctrl(*args):
    result = subprocess.run(['pinctrl', *args], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"pinctrl exited {result.returncode}")
    return result.stdout


def switch(on):
    """Click the relay on or off. Returns False (and says why) instead of raising."""
    pin = str(settings.SPEAKER_TRIGGER_GPIO)
    try:
        pinctrl('set', pin, 'op', 'dl') if on else pinctrl('set', pin, 'ip', 'pu')
        return True
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠️ Could not switch the speakers {'on' if on else 'off'}: {e}")
        return False


def is_on():
    """True if the relay is on, False if off, None if pinctrl can't tell"""
    try:
        return relay_on_from_pinctrl(pinctrl('get', str(settings.SPEAKER_TRIGGER_GPIO)))
    except (OSError, subprocess.SubprocessError):
        return None


def zd3_playing():
    """True while something on the Pi has the ZD3 open (pianobar, mpg123, aplay)"""
    try:
        status = open(f'/proc/asound/{settings.AUDIO_CARD}/pcm0p/sub0/status').read()
    except OSError:
        return False
    return status.strip() != 'closed'


def main(argv):
    if len(argv) != 2 or argv[1] not in ('on', 'off', 'status'):
        print(__doc__.strip())
        return 2
    if argv[1] == 'status':
        state = is_on()
        print({True: 'on', False: 'off', None: 'unknown (pinctrl failed)'}[state])
        return 0 if state is not None else 1
    return 0 if switch(argv[1] == 'on') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
