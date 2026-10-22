#!/home/pi/monty-alarm/venv/bin/python3
"""
Monty Alarm API Server
Receives push notifications from the main Monty system about wake-up schedules.
This is the only process that writes alarm_state.json; alarm_trigger.py reads it.
"""

from flask import Flask, request, jsonify
from datetime import datetime
from pathlib import Path
import logging
import signal
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent / 'core'))
import settings
import speakers
from statefiles import read_json, write_json, parse_iso, clean_wakeup_settings, load_wakeup_config

VERSION = '2.0.0'

app = Flask(__name__)

# Log to stdout only; systemd keeps it in the journal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
# Monty pings /api/health about once a minute - keep request lines out of the journal
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logger = logging.getLogger('monty-alarm-server')

# Flask serves requests on threads; Monty's clear and set can arrive together
state_lock = threading.Lock()

def signal_handler(sig, frame):
    """Handle shutdown gracefully"""
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def load_state():
    """Load saved alarm state from file"""
    state = {
        'hasAlarm': False,
        'wakeUpTime': None,
        'nextAlarm': None,
        'lastUpdate': None,
        'eventTime': None,
    }
    state.update(read_json(settings.ALARM_STATE_FILE, {}) or {})
    return state

def save_state(state):
    """Save alarm state to file"""
    state['lastSaved'] = datetime.now().isoformat()
    write_json(settings.ALARM_STATE_FILE, state)
    logger.info(f"State saved: hasAlarm={state.get('hasAlarm')}, nextAlarm={state.get('nextAlarm')}")

def event_time(data):
    """When Monty made this change. scheduledAt/clearedAt are set once per change,
    while the top-level timestamp is re-stamped on every retry."""
    schedule = data.get('schedule') or {}
    return schedule.get('scheduledAt') or schedule.get('clearedAt') or data.get('timestamp')

def is_older(event, applied):
    """True if this update was made before the one already applied"""
    if not event or not applied:
        return False
    try:
        return parse_iso(event) < parse_iso(applied)
    except ValueError:
        return False

def update_alarm_display(state):
    """Update physical alarm display"""
    try:
        if state.get('hasAlarm'):
            wake_time = state.get('wakeUpTime')

            # YOUR HARDWARE INTEGRATION HERE:
            # - Update LCD display
            # - Turn on LED indicator
            # - Set e-ink display
            # - Send to Arduino
            # - Update any other alarm hardware

        else:
            # Clear displays, turn off indicators
            pass

    except Exception as e:
        logger.error(f"Error updating display: {e}")

def request_sync():
    """Ask Monty to push its current schedule to us"""
    url = f"{settings.MONTY_URL}/api/scheduler/alarm-device/sync"
    try:
        req = urllib.request.Request(url, data=b'', method='POST',
                                     headers={'User-Agent': f'monty-alarm/{VERSION}'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info(f"🔄 Asked Monty to sync: HTTP {resp.status}")
            return True
    except Exception as e:
        logger.warning(f"⚠️ Could not ask Monty to sync ({url}): {e}")
        return False

def sync_loop():
    """Sync at startup, then hourly, so a missed push never leaves us on stale state"""
    time.sleep(5)  # Let the server start listening first - Monty pushes back to us
    while True:
        ok = request_sync()
        time.sleep(settings.SYNC_INTERVAL_SECONDS if ok else settings.SYNC_RETRY_SECONDS)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    state = load_state()
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'device': 'monty-alarm',
        'version': VERSION,
        'uptime': 'available',  # Could calculate actual uptime if needed
        'currentAlarm': {
            'hasAlarm': state.get('hasAlarm', False),
            'wakeUpTime': state.get('wakeUpTime'),
            'nextAlarm': state.get('nextAlarm'),
            'wakeMode': state.get('wakeMode'),
            'mp3Track': state.get('mp3Track'),
            'snoozeMinutes': state.get('snoozeMinutes')
        },
        # The alarm is silent without the amp, so say whether it's there. The ZD3
        # is off USB in standby until the speaker relay wakes it at alarm time.
        'audio': {
            'card': settings.AUDIO_CARD,
            'present': Path(f'/proc/asound/{settings.AUDIO_CARD}').exists(),
            'speakersOn': speakers.is_on()
        }
    })

@app.route('/api/schedule/update', methods=['POST'])
def update_schedule():
    """Receive schedule updates from main Monty system"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data received'}), 400

        logger.info(f"📨 Received schedule update from Monty: {data}")

        # Extract schedule information
        action = data.get('action', 'unknown')
        schedule = data.get('schedule') or {}
        event = event_time(data)
        # wakeMode, mp3Track, snoozeMinutes from Monty's alarm popup. Bad values
        # are dropped (the Pi's defaults apply) rather than refusing the alarm.
        wakeup, problems = clean_wakeup_settings(schedule)
        for problem in problems:
            logger.warning(f"⚠️ Ignoring {problem} from Monty - the Pi's default applies")

        with state_lock:
            current_state = load_state()

            # Monty sends schedule_cleared then schedule_set without waiting, so a
            # retried clear can land after the set. Drop anything older than what we have.
            if is_older(event, current_state.get('eventTime')):
                logger.warning(f"⏪ Ignoring {action} from {event}: already applied {current_state.get('eventTime')}")
                return jsonify({
                    'success': True,
                    'ignored': True,
                    'message': 'Update is older than the current schedule',
                    'currentState': current_state,
                    'receivedAt': datetime.now().isoformat()
                })

            # Update state with new schedule
            current_state.update({
                'hasAlarm': schedule.get('hasAlarm', False),
                'wakeUpTime': schedule.get('wakeUpTime'),
                'nextAlarm': schedule.get('nextAlarm'),
                'lastUpdate': data.get('timestamp', datetime.now().isoformat()),
                'eventTime': event,
                'action': action,
                'daysUntilAlarm': schedule.get('daysUntilAlarm'),
                **wakeup
            })
            save_state(current_state)

        # Update physical display
        update_alarm_display(current_state)

        return jsonify({
            'success': True,
            'message': 'Schedule updated successfully',
            'currentState': current_state,
            'receivedAt': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"❌ Error updating schedule: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'receivedAt': datetime.now().isoformat()
        }), 500

@app.route('/api/wakeup/options', methods=['GET'])
def wakeup_options():
    """What the Pi can play, for Monty's alarm popup"""
    tracks = sorted(p.name for p in settings.MUSIC_DIR.glob('*.mp3'))
    local = load_wakeup_config()
    low, high = settings.SNOOZE_MINUTES_RANGE

    def option(label, available, reason):
        return {'available': available, 'label': label, **({} if available else {'reason': reason})}

    return jsonify({
        'modes': {
            'pianobar': option('Pandora', True, None),
            'mp3': option('MP3', bool(tracks), 'No MP3s on the Pi'),
            'fm': option('FM radio', settings.FM_AVAILABLE, "FM radio isn't built yet"),
        },
        'mp3Tracks': tracks,
        'defaults': {'wakeMode': local['mode'], 'mp3Track': local['mp3_track'],
                     'snoozeMinutes': settings.SNOOZE_MINUTES},
        'snoozeMinutes': {'min': low, 'max': high},
    })

@app.route('/api/schedule/current', methods=['GET'])
def get_current_schedule():
    """Get current alarm schedule"""
    try:
        state = load_state()
        return jsonify({
            'success': True,
            'schedule': state,
            'retrievedAt': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting current schedule: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/test', methods=['POST'])
def test_endpoint():
    """Test endpoint for debugging"""
    try:
        data = request.json or {}
        logger.info(f"🧪 Test endpoint called with data: {data}")

        return jsonify({
            'success': True,
            'message': 'Test endpoint working',
            'receivedData': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error in test endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    logger.info("🚀 Starting Monty Alarm API Server...")
    logger.info(f"📁 State file location: {settings.ALARM_STATE_FILE}")
    logger.info(f"🏠 Monty: {settings.MONTY_URL}")

    # Load and display current state on startup
    initial_state = load_state()
    logger.info(f"📊 Current state: hasAlarm={initial_state.get('hasAlarm')}, nextAlarm={initial_state.get('nextAlarm')}")

    # Update display with current state
    update_alarm_display(initial_state)

    threading.Thread(target=sync_loop, name='monty-sync', daemon=True).start()

    try:
        # Run on all interfaces so it's accessible from your network
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)
