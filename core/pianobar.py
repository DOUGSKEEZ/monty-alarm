#!/usr/bin/env python3
"""
Commands for whichever pianobar is running on this Pi, through its control
FIFO (~/.config/pianobar/ctl): the alarm's, or one started by hand over SSH.
pianobar opens the FIFO when it starts and reads it like its keyboard, so
each character is a key: "-" is thumbs down (and skips), "+" thumbs up,
"n" next song, "p" pause/play.

  python3 core/pianobar.py setup        # create the FIFO (install.sh does this)
  python3 core/pianobar.py send -       # thumbs down the current song
"""

import errno
import os
import stat
import sys

import settings


def ensure_fifo(path=None):
    """Create the control FIFO if it's missing. pianobar only opens it at start,
    so this runs before the alarm starts pianobar too. Something written to the
    path while no FIFO existed leaves a plain file, which is replaced."""
    path = path or settings.PIANOBAR_CTL
    try:
        if stat.S_ISFIFO(os.stat(path).st_mode):
            return
        os.remove(path)
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path, 0o600)


def send(keys, path=None):
    """Send keys to the running pianobar. True if one was listening, False if
    pianobar isn't running (or the FIFO is missing). Never blocks."""
    path = path or settings.PIANOBAR_CTL
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ENXIO, errno.ENOENT):  # No reader / no FIFO
            return False
        raise
    try:
        os.write(fd, keys.encode())
        return True
    finally:
        os.close(fd)


def main(argv):
    if len(argv) == 2 and argv[1] == 'setup':
        ensure_fifo()
        print(f"FIFO ready: {settings.PIANOBAR_CTL}")
        return 0
    if len(argv) == 3 and argv[1] == 'send':
        if send(argv[2]):
            return 0
        print("pianobar isn't running")
        return 1
    print(__doc__.strip())
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
