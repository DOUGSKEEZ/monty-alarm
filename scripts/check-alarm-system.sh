#!/bin/bash
# Monty alarm health check: services, buttons, audio, clock, schedule, Monty
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
ok()   { echo -e "   ${GREEN}✓${NC} $1"; }
bad()  { echo -e "   ${RED}✗${NC} $1"; PROBLEMS=true; }
warn() { echo -e "   ${YELLOW}!${NC} $1"; }
setting() { python3 -c "import sys; sys.path.insert(0, 'core'); import settings; print(settings.$1)"; }

PROBLEMS=false
MONTY_URL=$(setting MONTY_URL)
AUDIO_CARD=$(setting AUDIO_CARD)

echo "🏥 Monty Alarm System Health Check"
echo "===================================="
echo "Time: $(date)"

echo
echo "1. Services"
for service in monty-alarm-api alarm-trigger alarm-buttons button-leds; do
    if systemctl is-active --quiet $service; then ok "$service is running"; else bad "$service is not running"; fi
done

echo
echo "2. Buttons"
for name in SNOOZE CHECK; do
    found=$(setting "${name}_DEVICES" | tr -d "[]',")
    present=""
    for dev in $found; do [ -e "$dev" ] && present="$present ${dev##*usb-0:}"; done
    if [ -n "$present" ]; then ok "$name button on USB$present"; else bad "$name button missing"; fi
done
python3 - <<'PY'
import sys
sys.path.insert(0, 'core')
import settings
from button_leds import find_pads, get_info
pads = find_pads()
for name, port in (("SNOOZE", settings.SNOOZE_PORT), ("CHECK", settings.CHECK_PORT)):
    if port not in pads:
        print(f"   ! {name} light: no button with the Monty firmware on USB {port}")
        continue
    try:
        info = get_info(pads[port])
        print(f"   ✓ {name} light: firmware {info['version']}, showing {info['rgb']} {info['effect']}")
    except OSError as e:
        print(f"   ! {name} light: can't reach it ({e})")
PY

echo
echo "3. Audio"
RELAY=$(python3 core/speakers.py status)
if [ -e /proc/asound/$AUDIO_CARD ]; then
    ok "$AUDIO_CARD is awake (speaker relay $RELAY)"
    if amixer -c $AUDIO_CARD sget Alarm >/dev/null 2>&1; then
        ok "Alarm volume control: $(amixer -M -c $AUDIO_CARD sget Alarm | grep -oE '[0-9]+%' | head -1)"
    else
        warn "Alarm volume control not created yet (it appears the first time something plays)"
    fi
elif [ "$RELAY" = "off" ]; then
    ok "$AUDIO_CARD in standby - the speaker relay wakes it at alarm time"
else
    bad "$AUDIO_CARD is NOT on USB although the speaker relay is $RELAY - the alarm would be silent"
fi
command -v pianobar >/dev/null && ok "pianobar installed" || bad "pianobar not installed"
command -v mpg123 >/dev/null && ok "mpg123 installed" || bad "mpg123 not installed"
python3 core/wakeup_mode_manager.py status | sed -n '3,5p' | sed 's/^/   /'

echo
echo "4. Clock"
if [ "$(timedatectl show -p NTPSynchronized --value)" = "yes" ]; then ok "Clock is NTP-synchronized"; else bad "Clock is NOT synchronized"; fi

echo
echo "5. Schedule"
curl -s -m 3 -o /dev/null http://localhost:5000/api/health && ok "Local API answering on port 5000" || bad "Local API (port 5000) not answering"
python3 - <<'PY'
import sys
sys.path.insert(0, 'core')
import monty_songs
import settings
from statefiles import (pushed_alarm, describe_alarm, read_json, pushed_wakeup_settings,
                        resolve_wakeup, describe_wakeup, load_wakeup_config)
_, at = pushed_alarm()
pushed = read_json(settings.ALARM_STATE_FILE, {}) or {}
print(f"   Pushed by Monty: {describe_alarm(at) if at else 'no alarm'} (last update {pushed.get('lastUpdate')})")
if at:
    wake = resolve_wakeup(pushed_wakeup_settings(), load_wakeup_config())
    print(f"   Wake-up: {describe_wakeup(wake)}")
    path, problem = monty_songs.mp3_to_play(wake['mp3_track'])
    if problem:
        print(f"   ⚠️ {problem} (still downloading from Monty?): an MP3 would play {path.name}")
handled = read_json(settings.TRIGGER_STATE_FILE, {}) or {}
if handled:
    print(f"   Last alarm handled: {handled.get('handled_alarm')} ({handled.get('result')} at {handled.get('at')})")
PY

echo
echo "6. Monty ($MONTY_URL)"
if status=$(curl -s -m 5 "$MONTY_URL/api/scheduler/wake-up/status"); then
    echo "$status" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(f\"   Monty wake-up: enabled={d['enabled']} time={d['time']}\")" \
        && ok "Monty reachable" || warn "Monty answered but the reply was unexpected"
else
    bad "Cannot reach Monty"
fi

echo
echo "===================================="
if [ "$PROBLEMS" = false ]; then
    echo -e "${GREEN}✅ System is READY${NC}"
else
    echo -e "${RED}❌ System has ISSUES - see above${NC}"
fi
echo
echo "Logs: sudo journalctl -u alarm-trigger -u alarm-buttons -u button-leds -u monty-alarm-api -f"
