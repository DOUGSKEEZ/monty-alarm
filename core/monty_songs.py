#!/usr/bin/env python3
"""
Alarm songs from Monty's Jukebox library
Monty serves each song at GET {MONTY_URL}/api/jukebox/library/{name}/file.
When a push names a song the Pi doesn't have, server.py downloads it in the
background. The alarm never waits on Monty: at ring time it plays what's on
the SD card, or the default track, because the MP3 is also what plays when
Pandora fails, and a network outage at 7am mustn't take that out too.

A download goes to "<name>.part" and is renamed into place only once all of
it has arrived, so a half-downloaded song is never played. Songs from Monty
live in music/from-monty/ (settings.MONTY_SONGS_DIR), apart from the Pi's own
tracks, and the least recently chosen are deleted past MONTY_SONGS_MAX_MB.
"""

import http.client
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

import settings
from statefiles import plain_mp3_name

MB = 2 ** 20
CHUNK = 256 * 1024
STALE_PART_SECONDS = 3600  # A .part this old is from a download that died


def track_path(name):
    """Where a track is on the Pi: its own music/ first, then songs from Monty. None if neither."""
    if not plain_mp3_name(name):
        return None
    for folder in (settings.MUSIC_DIR, settings.MONTY_SONGS_DIR):
        path = folder / name
        if path.is_file():
            return path
    return None


def mp3_to_play(track):
    """The file for an alarm's track: (path, None), or the default track and why
    the chosen one isn't playing"""
    path = track_path(track)
    if path is not None:
        return path, None
    return settings.MUSIC_DIR / settings.DEFAULT_MP3, f"{track} isn't on the Pi"


def all_tracks():
    """Every MP3 the alarm can play, by bare file name (as Monty names them)"""
    names = set()
    for folder in (settings.MUSIC_DIR, settings.MONTY_SONGS_DIR):
        names.update(p.name for p in folder.glob('*.mp3'))
    return sorted(names, key=str.casefold)


def mark_chosen(name):
    """A push named a song we already have: make it the newest, so cleanup keeps it longest"""
    try:
        os.utime(settings.MONTY_SONGS_DIR / name)
    except OSError:
        pass  # One of the Pi's own tracks


def song_url(name):
    # Names have spaces, apostrophes, & and emoji, so encode all of it
    return f"{settings.MONTY_URL}/api/jukebox/library/{urllib.parse.quote(name, safe='')}/file"


def download(name, timeout=30):
    """Copy one song from Monty's library into MONTY_SONGS_DIR.
    Returns (True, "7.2 MB in 3 s") or (False, why)."""
    if not plain_mp3_name(name):
        return False, f"not a plain .mp3 file name: {name!r}"
    folder = settings.MONTY_SONGS_DIR
    url = song_url(name)
    part = folder / (name + '.part')
    started = time.monotonic()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={'User-Agent': 'monty-alarm'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get('Content-Length', '')
            expected = int(length) if length.isdigit() else None
            free = shutil.disk_usage(folder).free
            if expected is not None and free - expected < settings.MIN_FREE_MB * MB:
                return False, (f"not enough room on the SD card ({free // MB} MB free, "
                               f"the song is {expected // MB} MB)")
            received = 0
            with open(part, 'wb') as f:
                while chunk := response.read(CHUNK):
                    f.write(chunk)
                    received += len(chunk)
                f.flush()
                os.fsync(f.fileno())  # On the card before the rename, in case the power goes
        if received == 0 or (expected is not None and received != expected):
            return False, f"the download stopped at {received} of {expected or '?'} bytes"
        os.replace(part, folder / name)
        return True, f"{received / MB:.1f} MB in {time.monotonic() - started:.0f} s"
    except urllib.error.HTTPError as e:
        return False, f"Monty answered HTTP {e.code} ({url})"
    except (OSError, ValueError, http.client.HTTPException) as e:
        return False, f"{e} ({url})"
    finally:
        part.unlink(missing_ok=True)


def clean_up(keep=()):
    """Delete songs from Monty, least recently chosen first, until they fit in
    MONTY_SONGS_MAX_MB. Never deletes a song in keep, or the Pi's own tracks.
    Returns the names deleted."""
    folder = settings.MONTY_SONGS_DIR
    now = time.time()
    songs = []
    for path in folder.glob('*'):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if path.name.endswith('.part'):
            if now - stat.st_mtime > STALE_PART_SECONDS:
                path.unlink(missing_ok=True)
        elif path.name.endswith('.mp3'):
            songs.append((stat.st_mtime, stat.st_size, path))

    used = sum(size for _, size, path in songs if path.name in keep)
    deleted = []
    for _, size, path in sorted(songs, reverse=True):  # Newest first
        if path.name in keep:
            continue
        used += size
        if used > settings.MONTY_SONGS_MAX_MB * MB:
            path.unlink(missing_ok=True)
            deleted.append(path.name)
    return deleted


def usage():
    """(number of songs from Monty, their total MB)"""
    sizes = [p.stat().st_size for p in settings.MONTY_SONGS_DIR.glob('*.mp3')]
    return len(sizes), sum(sizes) / MB
