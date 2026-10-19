# Monty Alarm Clock 🏠⏰

A bedside Raspberry Pi that plays wake-up music at the time set in the Monty home automation platform. Monty decides when; the Pi makes the sound and handles the buttons.

## Features
- Monty pushes every schedule change to the Pi; the Pi re-syncs at boot and hourly
- Physical Snooze and Stop buttons (two single-key USB keyboards)
- Wake-up music from Pandora (pianobar) or a looping MP3, with an automatic MP3 fallback if Pandora doesn't start
- Gradual volume ramp on the Fosi Audio ZD3
- 9-minute snooze, auto-stop after 60 minutes, still rings up to 15 minutes late after a reboot
- Planned: 12V trigger for amp power-on, a display, FM radio

## How it fits together

```
Monty (192.168.10.15:3001)
   │  POST /api/schedule/update        ▲ POST /api/scheduler/alarm-device/sync
   ▼                                   │   (at boot and hourly)
server.py ──writes──► alarm_state.json ──read every 1 s──► core/alarm_trigger.py ──► pianobar / mpg123
 (port 5000)                                                    ▲                     └► ALSA → ZD3
                                                                │ signals/alarm_snooze, alarm_stop
                                               core/alarm_button_handler.py ◄── USB buttons
```

| Service | Runs | Job |
| --- | --- | --- |
| `monty-alarm-api.service` | `server.py` (Flask, venv) | Receives Monty's pushes, writes `alarm_state.json`, asks Monty to sync, serves `/api/health` |
| `alarm-trigger.service` | `core/alarm_trigger.py` | Rings at the alarm time, plays music, ramps volume, handles snooze/stop |
| `alarm-buttons.service` | `core/alarm_button_handler.py` | Reads the buttons and drops signal files for the trigger |

All three run as user `pi`. Every path, address and tuning value is in [`core/settings.py`](core/settings.py).

## Buttons
- **Snooze** (USB port 1.3): press to snooze 9 minutes. Press as often as you like.
- **Check** (USB port 1.4): tap to log the next alarm to the journal; **hold 1.5 s to stop** the alarm, including during a snooze.

The buttons' LEDs are run by their own firmware: they don't respond to the keyboard lock lights, so the Pi can't switch them.

Presses while no alarm is ringing are ignored, so they never carry over to the next alarm. The buttons are found by USB port (`/dev/input/by-path`), because both are the same model and `/dev/input/by-id` can't tell them apart: **if you swap the plugs, the buttons swap**.

## How an alarm runs
1. Monty pushes `nextAlarm` (UTC). `server.py` stores it, ignoring any push older than the one it already has (Monty sends clear-then-set without waiting).
2. The trigger rings once the alarm time is reached, up to 15 minutes late. Older alarms are logged as missed. Each alarm is remembered in `trigger_state.json` by its `nextAlarm` value, so it never rings twice and several alarms a day work.
3. The music starts at 10% and ramps to 35% over 10 s (the `Alarm` control on the ZD3).
4. In Pandora mode, if no song starts within 20 s, or the player quits mid-alarm, it switches to the MP3.

Monty runs its own shade scenes at the same time; the Pi doesn't trigger them. Snooze is Pi-only.

## Audio
Everything goes straight to ALSA. PulseAudio is masked by `install.sh`: it only ran while someone was logged in, and while it ran it took over ALSA's default device, so the alarm sounded different depending on whether anyone was SSH'd in. `audio/asound.conf` sends the default device to the ZD3 by card name, through a software volume control named `Alarm`. **The ZD3 must be on and connected by USB at alarm time**: `/api/health` reports `audio.present`, and the trigger logs a warning if it's missing.

## Commands
```bash
# Install or update the units and audio config, then restart everything
sudo ./scripts/install.sh

# Health check: services, buttons, audio, clock, schedule, Monty
./scripts/check-alarm-system.sh

# Logs
sudo journalctl -u alarm-trigger -u alarm-buttons -u monty-alarm-api -f

# Wake-up music
python3 core/wakeup_mode_manager.py                 # status and help
python3 core/wakeup_mode_manager.py mode pianobar   # or: mp3, fm (fm plays Pandora for now)
python3 core/wakeup_mode_manager.py select THE_HIT.mp3
python3 core/wakeup_mode_manager.py add ~/song.mp3
python3 core/wakeup_mode_manager.py test 20         # play 20 s through the alarm's audio path

# Ring a test alarm 2 minutes from now (doesn't touch Monty), then restore Monty's schedule
./scripts/test-alarm.sh 2
./scripts/test-alarm.sh --restore

# Unit tests
venv/bin/python -m unittest discover -s tests -v

# See which button is which (stop the button service first)
sudo systemctl stop alarm-buttons && python3 scripts/test_button_keys.py; sudo systemctl start alarm-buttons
```

## Files
| Path | Holds |
| --- | --- |
| `alarm_state.json` | The schedule Monty pushed (written only by `server.py`) |
| `trigger_state.json` | The last alarm rung or missed (written only by the trigger) |
| `wakeup_config.json` | Wake-up mode and MP3 track |
| `signals/alarm_snooze`, `signals/alarm_stop` | One-shot button signals |
| `signals/alarm_display.txt` | `WAKE!`, `SNZ HH:MM` or empty: a stand-in until there's a display |
| `music/` | MP3s |

## Requirements
Raspberry Pi OS (Debian 12), `python3-evdev`, `pianobar` (logged in via `~/.config/pianobar/config` with `autostart_station`), `mpg123`, `alsa-utils`, and a venv with Flask for `server.py`. User `pi` must be in the `audio` and `input` groups.
