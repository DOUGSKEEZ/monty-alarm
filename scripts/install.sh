#!/bin/bash
# Install or update the Monty alarm's system files and restart its services.
# Run from anywhere with: sudo /home/pi/monty-alarm/scripts/install.sh
#
# What it changes outside the repo:
#   /etc/asound.conf      <- audio/asound.conf  (old one backed up next to it)
#   /etc/libao.conf       <- audio/libao.conf   (old one backed up next to it)
#   /etc/systemd/system/  <- services/*.service
#   /etc/udev/rules.d/99-monty-buttons.rules <- firmware/button/99-monty-buttons.rules
#   PulseAudio masked for all users (undo: systemctl --global unmask pulseaudio.service pulseaudio.socket)
# alarm-trigger.service runs with the gpio group (SupplementaryGroups) to click the speaker relay.
#   ~pi/.config/pianobar/ctl  <- a FIFO for pianobar commands (core/pianobar.py), created if missing
set -e
cd "$(dirname "$0")/.."

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0"
    exit 1
fi

install_config() {
    local src=$1 dest=$2
    if [ -f "$dest" ] && ! cmp -s "$src" "$dest"; then
        cp "$dest" "$dest.bak.$(date +%Y%m%d-%H%M%S)"
        echo "Backed up $dest"
    fi
    install -m 644 "$src" "$dest"
    echo "Installed $dest"
}

install_config audio/asound.conf /etc/asound.conf
install_config audio/libao.conf /etc/libao.conf

# Lets pi (plugdev) set the button lights and reflash the buttons
install_config firmware/button/99-monty-buttons.rules /etc/udev/rules.d/99-monty-buttons.rules
udevadm control --reload
udevadm trigger --subsystem-match=usb --action=change

# While PulseAudio runs (it starts with any login), /etc/alsa/conf.d/99-pulse.conf
# points ALSA's default device at it, bypassing asound.conf and the Alarm volume.
# Nothing on this Pi needs it, so keep it off for one predictable audio route.
systemctl --global mask pulseaudio.service pulseaudio.socket
for runtime in /run/user/*; do
    uid=$(basename "$runtime")
    sudo -u "#$uid" XDG_RUNTIME_DIR="$runtime" systemctl --user stop pulseaudio.service pulseaudio.socket 2>/dev/null || true
done
echo "PulseAudio masked"

for unit in services/*.service; do
    install -m 644 "$unit" /etc/systemd/system/
    echo "Installed /etc/systemd/system/$(basename "$unit")"
done

# pianobar's control FIFO, so the buttons can send it commands (thumbs down)
sudo -u pi -H python3 core/pianobar.py setup

# Runtime files the services share (all run as pi)
mkdir -p signals
chown -R pi:pi signals
for f in alarm_state.json trigger_state.json wakeup_config.json; do
    [ -e "$f" ] && chown pi:pi "$f"
done

systemctl daemon-reload
systemctl enable monty-alarm-api.service alarm-trigger.service alarm-buttons.service button-leds.service
systemctl restart monty-alarm-api.service alarm-trigger.service alarm-buttons.service button-leds.service
echo
systemctl --no-pager --lines=0 status monty-alarm-api.service alarm-trigger.service alarm-buttons.service button-leds.service | grep -E "●|Active:"
