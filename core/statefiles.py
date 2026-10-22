#!/usr/bin/env python3
"""
Reading and writing the files the alarm processes share
Writes are atomic (temp file + rename) because the trigger reads
alarm_state.json every second while server.py may be writing it.
"""

import json
import os
from datetime import datetime

import settings


def read_json(path, default=None):
    """Load a JSON file, or return default if it's missing or unreadable"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        print(f"⚠️ Could not read {path}: {e}")
        return default


def write_json(path, data):
    """Replace a JSON file in one step so readers never see half of it"""
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def parse_iso(value):
    """Parse an ISO time from Monty ("2026-10-18T14:08:00.000Z")"""
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def to_local(value):
    """ISO time string -> naive local datetime, to compare with datetime.now()"""
    dt = parse_iso(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def pushed_alarm():
    """The alarm Monty last pushed, as (nextAlarm string, local datetime), or (None, None)"""
    state = read_json(settings.ALARM_STATE_FILE, {}) or {}
    next_alarm = state.get('nextAlarm')
    if not state.get('hasAlarm') or not next_alarm:
        return None, None
    try:
        return next_alarm, to_local(next_alarm)
    except ValueError:
        print(f"⚠️ Could not parse nextAlarm: {next_alarm!r}")
        return None, None


def clean_wakeup_settings(schedule):
    """The wake-up settings in a Monty push, checked. Returns (settings, warnings):
    wakeMode, mp3Track and snoozeMinutes, each None when missing or invalid.
    A null mp3Track is Monty's "Pi's default", so it isn't a warning."""
    clean, warnings = {}, []

    mode = schedule.get('wakeMode')
    if mode is not None and mode not in settings.WAKE_MODES:
        warnings.append(f"unknown wakeMode {mode!r}")
        mode = None
    clean['wakeMode'] = mode

    # It becomes MUSIC_DIR / name, so only a plain file name will do
    track = schedule.get('mp3Track')
    if track is not None and not (isinstance(track, str) and track.lower().endswith('.mp3')
                                  and '/' not in track and '\\' not in track and not track.startswith('.')):
        warnings.append(f"bad mp3Track {track!r}")
        track = None
    clean['mp3Track'] = track

    snooze = schedule.get('snoozeMinutes')
    low, high = settings.SNOOZE_MINUTES_RANGE
    if snooze is not None and not (type(snooze) is int and low <= snooze <= high):
        warnings.append(f"snoozeMinutes {snooze!r} isn't a whole number from {low} to {high}")
        snooze = None
    clean['snoozeMinutes'] = snooze
    return clean, warnings


def pushed_wakeup_settings():
    """The wake-up settings Monty sent with the pushed alarm (None for each it didn't)"""
    return clean_wakeup_settings(read_json(settings.ALARM_STATE_FILE, {}) or {})[0]


def resolve_wakeup(pushed, local):
    """What an alarm plays and how long it snoozes: Monty's push first, then the
    Pi's own wakeup_config.json (local, from load_wakeup_config), then settings.
    'from' says where each came from, for the log."""
    resolved = {'from': {}}
    for key, pushed_key, fallback in (('mode', 'wakeMode', local['mode']),
                                      ('mp3_track', 'mp3Track', local['mp3_track']),
                                      ('snooze_minutes', 'snoozeMinutes', settings.SNOOZE_MINUTES)):
        value = pushed.get(pushed_key)
        resolved[key] = value if value is not None else fallback
        resolved['from'][key] = 'set in Monty' if value is not None else 'Pi default'
    return resolved


def describe_wakeup(wake):
    """'Pandora, snooze 9 min' style summary of resolve_wakeup()'s result"""
    sound = {'pianobar': 'Pandora', 'mp3': f"MP3 {wake['mp3_track']}", 'fm': 'FM radio'}.get(wake['mode'], wake['mode'])
    return (f"{sound} ({wake['from']['mode']}), "
            f"snooze {wake['snooze_minutes']} min ({wake['from']['snooze_minutes']})")


def load_wakeup_config():
    """Wake-up mode ("pianobar", "mp3" or "fm") and the MP3 track to play"""
    config = read_json(settings.WAKEUP_CONFIG_FILE, {}) or {}
    return {
        'mode': config.get('mode') or 'pianobar',
        'mp3_track': config.get('mp3_track') or settings.DEFAULT_MP3,
    }


def describe_alarm(alarm_at, now=None):
    """'Mon 08:08 (in 7h 12m)' for logs"""
    now = now or datetime.now()
    seconds = int((alarm_at - now).total_seconds())
    if seconds < 0:
        return f"{alarm_at:%a %H:%M} ({-seconds // 60}m ago)"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    until = f"{hours}h {minutes}m" if hours else f"{minutes}m {rest % 60}s"
    return f"{alarm_at:%a %H:%M} (in {until})"


def take_signal(path):
    """Consume a one-shot signal file from the buttons. True if it was there."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def send_signal(path):
    """Drop a one-shot signal file for the trigger"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def write_display(text):
    """Stand-in for a real display: WAKE!, SNZ HH:MM or empty"""
    try:
        settings.DISPLAY_FILE.write_text(text)
    except OSError:
        pass


def read_display():
    try:
        return settings.DISPLAY_FILE.read_text().strip()
    except OSError:
        return ""
