# Monty Alarm Clock 🏠⏰

A bedside Raspberry Pi that plays wake-up music at the time set in the Monty home automation platform. Monty decides when; the Pi makes the sound and handles the buttons.

## Features
- Monty pushes every schedule change to the Pi; the Pi re-syncs at boot and hourly
- Physical Snooze and Check/Stop buttons (two single-key USB keypads) whose lights follow the alarm and stay dark at night
- Wake-up music from Pandora (pianobar) or a looping MP3, with an automatic MP3 fallback if Pandora doesn't start
- Gradual volume ramp on the Fosi Audio ZD3
- Wake-up sound (Pandora or an MP3) and snooze length set in Monty's alarm popup; 9-minute snooze by default, auto-stop after 60 minutes, still rings up to 15 minutes late after a reboot
- Speaker power: at alarm time a relay wakes the ZD3 and ZA3 through their 12 V trigger, and they go back to standby after
- Planned: a display, FM radio

## How it fits together

```
Monty (192.168.10.15:3001)
   │  POST /api/schedule/update        ▲ POST /api/scheduler/alarm-device/sync
   ▼                                   │   (at boot and hourly)
server.py ──writes──► alarm_state.json ──read every 1 s──► core/alarm_trigger.py ──► pianobar / mpg123
 (port 5000)                                                    ▲         │           └► ALSA → ZD3 → ZA3
                                                                │         └► core/speakers.py → relay → 12 V trigger
                                                                │ signals/alarm_snooze, alarm_stop
                                               core/alarm_button_handler.py ◄── USB buttons
                                               core/button_leds.py ──► button lights (follows signals/alarm_display.txt)
```

| Service | Runs | Job |
| --- | --- | --- |
| `monty-alarm-api.service` | `server.py` (Flask, venv) | Receives Monty's pushes, writes `alarm_state.json`, asks Monty to sync, downloads alarm songs from Monty, serves `/api/health` and `/api/wakeup/options` |
| `alarm-trigger.service` | `core/alarm_trigger.py` | Rings at the alarm time, wakes the speakers, plays music, ramps volume, handles snooze/stop |
| `alarm-buttons.service` | `core/alarm_button_handler.py` | Reads the buttons and drops signal files for the trigger |
| `button-leds.service` | `core/button_leds.py watch` | Sets the button lights from the alarm's state. Separate, so a light problem can't stop the alarm |

All four run as user `pi`. Every path, address and tuning value is in [`core/settings.py`](core/settings.py).

## Buttons
- **Snooze** (USB port 1.4): press to snooze (9 minutes, or the length set in Monty). Press as often as you like. It snoozes when you let go. **Hold it 1.1 s while pianobar plays to skip to the next song** without a thumbs down; the Snooze light flickers blue. With no pianobar playing, a hold snoozes too.
- **Check** (USB port 1.3): **hold 1.1 s to stop** the alarm, including during a snooze. **Tap while pianobar is playing for a thumbs down** on the Pandora song: Pandora won't play it on that station again, and pianobar skips to the next song. It works for the alarm's music and for a pianobar started by hand over SSH, because it goes through pianobar's control FIFO (`~/.config/pianobar/ctl`, see `core/pianobar.py`). The Check light flickers blue to confirm. A tap when pianobar isn't running logs the next alarm to the journal.

Both buttons run our own firmware ([`firmware/button/`](firmware/button/README.md)): a plain keyboard that sends `a`, with an RGB light the Pi controls over USB. The lights follow the alarm (colours in `settings.BUTTON_LIGHTS`):

| | Idle (day and night) | Ringing | Snoozing | Alarm ended |
| --- | --- | --- | --- | --- |
| Snooze | off | green, breathing | amber | pink/purple fast blink for 3 s, then off |
| Check | off | red | red | pink/purple fast blink for 3 s, then off |

A button that's unplugged and plugged back in starts dark and gets its light back within a second. The firmware can be updated from the Pi without opening the button (see the firmware README).

Presses while no alarm is ringing are ignored, so they never carry over to the next alarm. The buttons are found by USB port (`/dev/input/by-path`), because both are the same model and `/dev/input/by-id` can't tell them apart: **if you swap the plugs, the buttons swap**.

## How an alarm runs
1. Monty pushes `nextAlarm` (UTC), with the alarm popup's `wakeMode` (`pianobar`, `mp3` or `fm`), `mp3Track` and `snoozeMinutes`. `server.py` stores them, ignoring any push older than the one it already has (Monty sends clear-then-set without waiting). An invalid setting is dropped with a warning and the Pi's default applies: `wakeup_config.json`, then `settings.py`. Monty's "Shades only" arrives as no alarm at all. A song from Monty's library is downloaded straight away (see Alarm songs).
2. The trigger rings once the alarm time is reached, up to 15 minutes late. Older alarms are logged as missed. Each alarm is remembered in `trigger_state.json` by its `nextAlarm` value, so it never rings twice and several alarms a day work.
3. The settings are fixed for this alarm when it starts ringing (Monty clears its one-shot wake-up afterwards). The speaker relay clicks on (see Speaker power), and the music starts about 8 s later. FM isn't built yet, so `fm` plays Pandora.
4. The music starts at 10% and ramps to 35% over 10 s (the `Alarm` control on the ZD3).
5. In Pandora mode, if no song starts within 20 s, or the player quits mid-alarm, it switches to the MP3.
6. The speakers stay on through snoozes and go back to standby 5 minutes after the alarm ends.

Monty runs its own shade scenes at the same time; the Pi doesn't trigger them. Snooze is Pi-only.

## Alarm songs
The alarm's MP3 can be one of the Pi's own tracks in `music/` (`Beethoven.mp3`, and `THE_HIT.mp3`, the default) or any song in Monty's Jukebox library. `/api/wakeup/options` says `fetchesFromMonty: true`, so Monty's popup offers its whole library.

- **Downloaded ahead, never at ring time.** When a push names a song the Pi doesn't have, `server.py` downloads it from Monty (`GET /api/jukebox/library/{name}/file`) in the background, into `music/from-monty/`. A failed download is retried at the next sync (at boot and hourly), with a warning in the journal each time. The MP3 is also what plays when Pandora fails, so it must not depend on the network at 7am.
- **Never half a song.** A download goes to `<name>.part` and is renamed only once every byte Monty promised has arrived.
- **At ring time** the alarm plays the song if it's on the SD card, and otherwise `THE_HIT.mp3`, saying why in the journal and in `songs.log`.
- **Room on the SD card.** Songs from Monty are kept up to 2 GB (`settings.MONTY_SONGS_MAX_MB`); past that, the least recently chosen are deleted. The next alarm's song and the Pi's own tracks never are. Nothing downloads into the card's last GB (`MIN_FREE_MB`).
- **File names** are Monty's, as they are: spaces, apostrophes, `&`, accents and emoji all work. Only a bare `.mp3` name is accepted, never a folder or a hidden file (`statefiles.plain_mp3_name`).
- `music/from-monty/` is in `.gitignore`: it's Doug's music, not the repo's. All of this is in `core/monty_songs.py`.

## Speaker power
The ZD3 and ZA3 sit in standby until an alarm. Relay 1 of an HL-52S module (IN1 on GPIO 4, header pin 7, active-low) switches 12 V from an MT3608 boost module (powered from a Pi USB port, set to 12.0 V) into the ZD3's 12 V Trigger In; the ZD3's Trigger Out wakes the ZA3. The ZD3 ignores 5 V. Wiring: relay VCC to pin 4, GND to pin 6, IN1 to pin 7; MT3608 OUT+ to the relay's COM; the bottom screw (NO) to the 3.5 mm plug's tip, Pi pin 14 to its sleeve. Leave the top screw (NC) empty: it carries 12 V while the relay is off.

At alarm time the trigger:
1. Clicks the relay on, together with Monty's shades.
2. Waits for the ZD3 to appear on USB (about 4 s, up to 20 s).
3. Plays a second of 44.1 kHz silence to it, retrying until it works. The ZD3 is listed a moment before it can play, and its first stream after waking snaps while it switches clock; this way the snap happens while the ZA3 is still muted.
4. Waits until 3 s after the ZD3 appeared, so the ZA3 has unmuted (about 6 s after the click), then starts the music.

Snooze keeps the speakers on. After the alarm they stay on for 5 minutes, longer while anything on the Pi is playing to the ZD3 (playback over Bluetooth from a phone isn't visible to the Pi, so it doesn't count). If the ZD3 is already on at alarm time, the music starts straight away. The relay can be switched by hand, and the ZD3's remote and knob still work while the relay is off. All the timings are in `settings.py` (`SPEAKER_*`).

## Audio
Everything goes straight to ALSA. PulseAudio is masked by `install.sh`: it only ran while someone was logged in, and while it ran it took over ALSA's default device, so the alarm sounded different depending on whether anyone was SSH'd in. `audio/asound.conf` sends the default device to the ZD3 by card name, through a software volume control named `Alarm`. The ZD3 must be connected by USB and to the relay: `/api/health` reports `audio.present` (false in standby) and `audio.speakersOn`, and the trigger logs a warning if the ZD3 doesn't wake.

## Commands
```bash
# Install or update the units and audio config, then restart everything
sudo ./scripts/install.sh

# Health check: services, buttons, audio, clock, schedule, Monty
./scripts/check-alarm-system.sh

# Logs
sudo journalctl -u alarm-trigger -u alarm-buttons -u button-leds -u monty-alarm-api -f

# Songs the alarm played (kept across reboots, unlike the journal)
tail -n 30 songs.log
grep Adele songs.log

# Button lights (1.4 = Snooze, 1.3 = Check). A manual set lasts until the alarm's state next changes
python3 core/button_leds.py info
python3 core/button_leds.py set 1.4 0 200 0 breathe   # solid, breathe, blink or fast

# Speakers (the relay): a manual on stays on until off, or until 5 min after the next alarm
python3 core/speakers.py status
python3 core/speakers.py on
python3 core/speakers.py off

# Commands to whichever pianobar is running (- thumbs down, + thumbs up, n next, p pause)
python3 core/pianobar.py send n

# Wake-up music
python3 core/wakeup_mode_manager.py                 # status and help
python3 core/wakeup_mode_manager.py mode pianobar   # or: mp3, fm (fm plays Pandora for now)
python3 core/wakeup_mode_manager.py list            # the Pi's own tracks, then songs downloaded from Monty
python3 core/wakeup_mode_manager.py select THE_HIT.mp3   # the Pi's own tracks only
python3 core/wakeup_mode_manager.py add ~/song.mp3
python3 core/wakeup_mode_manager.py test 20         # play 20 s through the alarm's audio path, waking the speakers first

# Ring a test alarm 2 minutes from now (doesn't touch Monty), then restore Monty's schedule
./scripts/test-alarm.sh 2
./scripts/test-alarm.sh 2 --mode mp3 --track Beethoven.mp3 --snooze 3   # with popup settings
./scripts/test-alarm.sh --restore

# What the Pi offers Monty's alarm popup (MP3 list, whether FM works, defaults)
curl -s localhost:5000/api/wakeup/options

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
| `songs.log` | Every song the alarm played, one dated line each, with the station, thumbs and snoozes (appended by the trigger) |
| `signals/alarm_snooze`, `signals/alarm_stop` | One-shot button signals |
| `signals/alarm_display.txt` | `WAKE!`, `SNZ HH:MM` or empty: a stand-in until there's a display |
| `music/` | The Pi's own MP3s |
| `music/from-monty/` | Alarm songs downloaded from Monty's library (not in git, up to 2 GB) |
| `firmware/button/` | The buttons' firmware, its udev rule and how to flash it |

## Requirements
Raspberry Pi OS (Debian 12), `python3-evdev`, `pianobar` (logged in via `~/.config/pianobar/config` with `autostart_station`), `mpg123`, `alsa-utils`, and a venv with Flask for `server.py`. User `pi` must be in the `audio`, `input`, `plugdev` and `gpio` groups; `pinctrl` (raspi-utils) switches the relay. Building and flashing the button firmware also needs `sdcc`, `uhubctl` (apt) and [wchisp](https://github.com/ch32-rs/wchisp).
