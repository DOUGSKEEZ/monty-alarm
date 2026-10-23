#!/bin/bash
# Back up what a new SD card can't get from GitHub, to a Borg repository on
# the backup server: the Pandora login, Wi-Fi, SSH host keys, wakeup_config.json,
# songs.log, any unpushed commits, and lists of the packages to reinstall.
#
#   sudo scripts/backup.sh               # make an archive
#   sudo scripts/backup.sh list          # anything else is passed to borg:
#   sudo scripts/backup.sh extract ::monty-alarm-2026-10-23T10:00 home/pi/.config/pianobar/config
#
# It runs as root because the Wi-Fi passwords and SSH host keys are root-only.
# The repository isn't encrypted (borg init --encryption none). Its address
# stays out of this public repo, in a root-only file on the Pi:
#   /root/.config/borg/repo         one line, e.g. ssh://user@host/path/to/borg
# It connects with its own key, /root/.ssh/monty-alarm-borg, which the server
# should only let run "borg serve" for that one repository. The first run needs
# the repository made: sudo scripts/backup.sh init --encryption none --make-parent-dirs
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 $*"
    exit 1
fi

BORG_CONFIG=/root/.config/borg
export BORG_REPO=${BORG_REPO:-$(cat "$BORG_CONFIG/repo" 2>/dev/null || true)}
if [ -z "$BORG_REPO" ]; then
    echo "No repository: put its address in $BORG_CONFIG/repo (or set BORG_REPO)"
    exit 1
fi
# A rebuilt Pi hasn't seen the repository before; don't stop to ask about it
export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
export BORG_RSH=${BORG_RSH:-"ssh -i /root/.ssh/monty-alarm-borg -o IdentitiesOnly=yes -o BatchMode=yes"}

if [ "${1:-create}" != "create" ]; then
    exec borg "$@"
fi

# Lists for rebuilding: what to apt install, what's in the venv, what was unpushed
MANIFESTS=/var/backups/monty-alarm
REPO_DIR=/home/pi/monty-alarm
mkdir -p "$MANIFESTS"
apt-mark showmanual > "$MANIFESTS/apt-manual.txt"
dpkg --get-selections > "$MANIFESTS/dpkg-selections.txt"
sudo -u pi "$REPO_DIR/venv/bin/pip" freeze > "$MANIFESTS/pip-freeze.txt"
systemctl list-unit-files --state=enabled --no-pager > "$MANIFESTS/enabled-units.txt"
{
    cat /proc/device-tree/model; echo
    grep PRETTY_NAME /etc/os-release
    uname -a
    sudo -u pi git -C "$REPO_DIR" status -sb | head -1
    sudo -u pi git -C "$REPO_DIR" log --oneline -10
} > "$MANIFESTS/system.txt"

# Low priority: the alarm comes first
nice -n 19 ionice -c 3 borg create --stats --show-rc --compression zstd --exclude-caches \
    --exclude /home/pi/.cursor-server \
    --exclude /home/pi/.cache \
    --exclude "$REPO_DIR/venv" \
    --exclude "$REPO_DIR/music/from-monty" \
    --exclude "$REPO_DIR/signals" \
    --exclude 'sh:**/__pycache__' \
    "::monty-alarm-{now:%Y-%m-%dT%H:%M}" \
    /home/pi /etc /boot/firmware/config.txt /boot/firmware/cmdline.txt "$MANIFESTS"
