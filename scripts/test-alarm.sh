#!/bin/bash
# Ring the alarm N minutes from now (default 1) by sending this Pi the same
# push Monty would. Monty's own schedule is not touched.
#
#   scripts/test-alarm.sh [minutes]   # set a test alarm
#   scripts/test-alarm.sh 2 --mode mp3 --track Beethoven.mp3 --snooze 3
#                                     # ...with the settings Monty's alarm popup sends
#   scripts/test-alarm.sh --restore   # ask Monty to push its real schedule again
#
# The hourly sync with Monty also replaces a test alarm, so keep tests short.
cd "$(dirname "$0")/.."
MONTY_URL=$(python3 -c "import sys; sys.path.insert(0, 'core'); import settings; print(settings.MONTY_URL)")

if [ "$1" = "--restore" ]; then
    curl -s -m 15 -X POST "$MONTY_URL/api/scheduler/alarm-device/sync" && echo
    echo "Asked Monty to re-push its schedule."
    exit 0
fi

MINUTES=1
EXTRA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --mode)   EXTRA="$EXTRA,\"wakeMode\":\"$2\""; shift 2 ;;
        --track)  EXTRA="$EXTRA,\"mp3Track\":\"$2\""; shift 2 ;;
        --snooze) EXTRA="$EXTRA,\"snoozeMinutes\":$2"; shift 2 ;;
        *)        MINUTES=$1; shift ;;
    esac
done
NOW=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
AT=$(date -u -d "+${MINUTES} min" +%Y-%m-%dT%H:%M:%S.000Z)
LOCAL=$(date -d "+${MINUTES} min" +%H:%M)

curl -s -m 5 -X POST http://localhost:5000/api/schedule/update \
    -H 'Content-Type: application/json' \
    -d "{\"timestamp\":\"$NOW\",\"action\":\"schedule_set\",\"schedule\":{\"hasAlarm\":true,\"wakeUpTime\":\"$LOCAL\",\"nextAlarm\":\"$AT\",\"scheduledAt\":\"$NOW\",\"daysUntilAlarm\":0$EXTRA}}" \
    > /dev/null && echo "⏰ Test alarm set for $(date -d "+${MINUTES} min" +%H:%M:%S)" || { echo "❌ Local API not answering"; exit 1; }
echo "   Watch it:  sudo journalctl -u alarm-trigger -u alarm-buttons -f"
echo "   Afterwards: scripts/test-alarm.sh --restore"
