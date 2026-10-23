#!/bin/bash
# Turn a freshly flashed Raspberry Pi OS Lite card into the Monty alarm: the code
# comes from GitHub, everything else from the Borg backup (scripts/backup.sh).
# The steps before this one are in the README (Rebuilding on a new SD card):
#
#   sudo apt update && sudo apt install -y git
#   git clone https://github.com/DOUGSKEEZ/monty-alarm.git ~/monty-alarm
#   sudo ~/monty-alarm/scripts/rebuild.sh ssh://user@host/path/to/borg
#
# What it does:
#   1. Makes the Pi a new key for the backup server and shows the line to put in
#      the server's authorized_keys (the old Pi's key went with the old card)
#   2. Installs the packages, turns on I2C and SPI, sets pi's groups and shell
#   3. Restores from the newest archive: /home/pi (Pandora login, GitHub key,
#      shell setup, tools), the repo's files git doesn't track (wakeup_config.json,
#      songs.log...), the SSH host keys and the Wi-Fi networks
#   4. Builds the venv from requirements.txt and runs install.sh
# It never restores the rest of /etc, or cmdline.txt: they belong to the old card
# and its OS. It can be run again; each run restores the newest archive.
# NOT YET TESTED ON A BLANK CARD.
set -euo pipefail

REPO_DIR=/home/pi/monty-alarm
BACKUP="$REPO_DIR/scripts/backup.sh"
BORG_CONFIG=/root/.config/borg
KEY=/root/.ssh/monty-alarm-borg

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 $*"
    exit 1
fi
if [ "$(cd "$(dirname "$0")/.." && pwd)" != "$REPO_DIR" ]; then
    echo "Clone the repo to $REPO_DIR first: the services expect it there"
    exit 1
fi
cd "$REPO_DIR"

step() { echo; echo "=== $*"; }
as_pi() { sudo -u pi -H "$@"; }

# Restored files wait here; it holds secrets, so it goes when the script ends
STAGE=$(mktemp -d /var/tmp/monty-restore.XXXXXX)
chmod 755 "$STAGE"   # pi runs git in the restored repo (home/pi inside stays 700)
trap 'rm -rf "$STAGE"' EXIT

# 1. The backup server
step "Backup server"
mkdir -p -m 700 "$BORG_CONFIG" /root/.ssh
REPO=${1:-$(cat "$BORG_CONFIG/repo" 2>/dev/null || true)}
if [ -z "$REPO" ]; then
    echo "The repository's address isn't in git; it's in the Monty Alarm handoff doc."
    echo "Leave it empty to set the Pi up without restoring anything."
    read -rp "Repository (ssh://user@host/path/to/borg): " REPO
fi
RESTORE=no
if [ -n "$REPO" ]; then
    if [[ ! $REPO =~ ^ssh://([^@/]+@)?([^/:]+)(/.+)$ ]]; then
        echo "Use the form ssh://user@host/path/to/borg"
        exit 1
    fi
    HOST=${BASH_REMATCH[2]}
    REPO_PATH=${BASH_REMATCH[3]}
    RESTORE=yes
    echo "$REPO" > "$BORG_CONFIG/repo"
    chmod 600 "$BORG_CONFIG/repo"
    [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "monty-alarm borg backup (root@$(hostname))" -f "$KEY"
    echo "On the backup server, replace the old monty-alarm line in the backup user's"
    echo "~/.ssh/authorized_keys with this one:"
    echo
    echo "command=\"borg serve --append-only --restrict-to-repository $REPO_PATH\",restrict $(cat "$KEY.pub")"
    echo
    echo "Packages install meanwhile; the restore asks before it starts."
fi

# 2. Packages and system settings
step "Packages"
apt-get update -q
# What the alarm needs, then the button firmware tools, pi's shell and handy tools.
# Everything the old Pi had is listed in the backup's var/backups/monty-alarm/.
apt-get install -y -q git rsync pianobar mpg123 alsa-utils python3-evdev python3-venv \
    borgbackup raspi-utils \
    sdcc uhubctl \
    zsh zsh-autosuggestions zsh-syntax-highlighting \
    evtest i2c-tools htop ncdu tree
raspi-config nonint do_i2c 0   # 0 = on: for the display, as on the old Pi
raspi-config nonint do_spi 0
usermod -aG audio,input,plugdev,gpio,i2c,spi pi
chsh -s /usr/bin/zsh pi

# 3. Restore
if [ "$RESTORE" = yes ]; then
    step "Restore from the backup"
    while true; do
        read -rp "Press Enter once the line is on the server (or type skip): " answer
        if [ "$answer" = skip ]; then
            RESTORE=no
            break
        fi
        # Trust the server's host key the first time it answers
        ssh-keygen -F "$HOST" -f /root/.ssh/known_hosts >/dev/null 2>&1 \
            || ssh-keyscan -t ed25519 "$HOST" 2>/dev/null >> /root/.ssh/known_hosts || true
        if ARCHIVE=$("$BACKUP" list --short --last 1 2>"$STAGE/borg-errors") && [ -n "$ARCHIVE" ]; then
            break
        fi
        echo "Can't read the repository yet:"
        tail -3 "$STAGE/borg-errors"
    done
fi

KEPT=""
if [ "$RESTORE" = yes ]; then
    echo "Restoring $ARCHIVE"
    (cd "$STAGE" && "$BACKUP" extract "::$ARCHIVE" home/pi etc/ssh etc/NetworkManager/system-connections)
    chmod 755 "$STAGE/home"   # borg makes it root-only; pi has to reach its repo inside
    OLD_HOME="$STAGE/home/pi"
    OLD_REPO="$OLD_HOME/monty-alarm"

    # /home/pi, except the repo: its code is the clone from GitHub
    rsync -a --exclude=/monty-alarm/ "$OLD_HOME/" /home/pi/
    # The repo's files git doesn't track: wakeup_config.json, songs.log, config/...
    as_pi git -C "$OLD_REPO" ls-files -z --others \
        | rsync -a --from0 --files-from=- "$OLD_REPO/" "$REPO_DIR/"

    # Commits that never reached GitHub, or uncommitted changes: keep the old copy
    # for a person to sort out. (--diff-filter=d: the backup leaves out signals/,
    # so signals/.gitkeep looks deleted.)
    OLD_HEAD=$(as_pi git -C "$OLD_REPO" rev-parse HEAD)
    as_pi git -C "$REPO_DIR" fetch -q "$OLD_REPO" HEAD
    if ! as_pi git -C "$REPO_DIR" merge-base --is-ancestor "$OLD_HEAD" HEAD \
        || [ -n "$(as_pi git -C "$OLD_REPO" diff --name-only --diff-filter=d HEAD)" ]; then
        rsync -a "$OLD_REPO/" /home/pi/monty-alarm-from-backup/
        KEPT=yes
    fi
    # Push the way the old Pi did (its GitHub key came back with /home/pi)
    OLD_ORIGIN=$(as_pi git -C "$OLD_REPO" remote get-url origin 2>/dev/null || true)
    [ -z "$OLD_ORIGIN" ] || as_pi git -C "$REPO_DIR" remote set-url origin "$OLD_ORIGIN"

    # The old Pi's SSH identity, so the laptop's known_hosts still matches
    cp -p "$STAGE"/etc/ssh/ssh_host_* /etc/ssh/
    systemctl restart ssh
    # Its Wi-Fi networks (the one Imager set up stays too)
    for f in "$STAGE"/etc/NetworkManager/system-connections/*.nmconnection; do
        if [ -e "$f" ]; then
            install -m 600 "$f" /etc/NetworkManager/system-connections/
        fi
    done
    nmcli connection reload
fi

# 4. The venv and the alarm's system files
step "Python venv"
[ -x venv/bin/python3 ] || as_pi python3 -m venv venv
as_pi venv/bin/pip install -q -r requirements.txt

step "System files and services"
scripts/install.sh

step "Done"
if [ "$RESTORE" = yes ]; then
    echo "Restored from $ARCHIVE"
else
    echo "Nothing restored: log pianobar in (~/.config/pianobar/config) and choose the wake-up mode by hand"
fi
if [ -n "$KEPT" ]; then
    echo "The backup had work that isn't on GitHub. It's in /home/pi/monty-alarm-from-backup:"
    echo "push it from there, then delete that folder."
fi
cat <<'EOF'
Next:
  sudo reboot     (turns on I2C and SPI, pi's new groups and zsh)
  then run scripts/check-alarm-system.sh, and check the Pi's IP is still
  192.168.10.109: Monty sends the alarms there.
EOF
