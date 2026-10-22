#!/usr/bin/env python3
"""
Wake-Up Mode Manager for Monty Alarm Clock
Chooses what the alarm plays and manages the MP3 library.
Everything is kept in wakeup_config.json, which alarm_trigger.py reads at alarm time.
These are the Pi's defaults: whatever Monty sends with an alarm (its alarm popup) wins.

  python3 core/wakeup_mode_manager.py                  # status
  python3 core/wakeup_mode_manager.py mode <pianobar|mp3|fm>
  python3 core/wakeup_mode_manager.py list
  python3 core/wakeup_mode_manager.py select <file.mp3>
  python3 core/wakeup_mode_manager.py add <path/to/file.mp3>
  python3 core/wakeup_mode_manager.py test [seconds]   # play it through the alarm's audio path
"""

import shutil
import subprocess
import sys
from pathlib import Path

import settings
from statefiles import read_json, write_json, load_wakeup_config, pushed_wakeup_settings

MODES = {
    "pianobar": "Pandora internet radio (falls back to the MP3 if no song starts)",
    "mp3": "Local MP3 file, looped",
    "fm": "FM radio (not built yet - plays Pandora)",
}


def save_config(**changes):
    config = read_json(settings.WAKEUP_CONFIG_FILE, {}) or {}
    config.update(changes)
    write_json(settings.WAKEUP_CONFIG_FILE, config)


def list_tracks():
    return sorted(p.name for p in settings.MUSIC_DIR.glob("*.mp3"))


def show_status():
    config = load_wakeup_config()
    track = settings.MUSIC_DIR / config['mp3_track']
    print("🎵 Wake-Up Mode Manager")
    print("=" * 40)
    print(f"Mode:      {config['mode']} - {MODES.get(config['mode'], 'unknown')}")
    print(f"MP3 track: {config['mp3_track']}{'' if track.exists() else '  ❌ FILE NOT FOUND'}")
    from_monty = {k: v for k, v in pushed_wakeup_settings().items() if v is not None}
    if from_monty:
        print(f"From Monty for the next alarm (wins over the above): {from_monty}")
    print(__doc__.split("\n\n", 1)[1].rstrip())


def set_mode(mode):
    if mode not in MODES:
        print(f"Invalid mode '{mode}'. Valid modes: {', '.join(MODES)}")
        return 1
    save_config(mode=mode)
    print(f"Wake-up mode set to '{mode}': {MODES[mode]}")
    return 0


def select_track(filename):
    if not (settings.MUSIC_DIR / filename).exists():
        print(f"Track '{filename}' not found. Available: {', '.join(list_tracks())}")
        return 1
    save_config(mp3_track=filename)
    print(f"Selected '{filename}' as the MP3 track")
    return 0


def add_track(source):
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != '.mp3':
        print(f"Not an MP3 file: {source}")
        return 1
    dest = settings.MUSIC_DIR / source.name
    if dest.exists():
        print(f"'{source.name}' is already in the music library")
        return 1
    shutil.copy2(source, dest)
    print(f"Added '{source.name}' to the music library")
    return 0


def test(seconds):
    trigger = Path(__file__).resolve().parent / 'alarm_trigger.py'
    return subprocess.run([sys.executable, str(trigger), '--test-music', str(seconds)]).returncode


if __name__ == "__main__":
    args = sys.argv[1:]
    command = args[0] if args else "status"

    if command == "status":
        show_status()
    elif command == "mode" and len(args) > 1:
        sys.exit(set_mode(args[1]))
    elif command == "list":
        current = load_wakeup_config()['mp3_track']
        for name in list_tracks():
            print(f"{'→' if name == current else ' '} {name}")
    elif command == "select" and len(args) > 1:
        sys.exit(select_track(args[1]))
    elif command == "add" and len(args) > 1:
        sys.exit(add_track(args[1]))
    elif command == "test":
        sys.exit(test(int(args[1]) if len(args) > 1 else 20))
    else:
        print("Invalid command. Run without arguments for help.")
        sys.exit(1)
