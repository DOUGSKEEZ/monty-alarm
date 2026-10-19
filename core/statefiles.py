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
