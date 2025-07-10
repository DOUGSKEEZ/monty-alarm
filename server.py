#!/home/pi/monty-alarm/venv/bin/python3
"""
Monty Alarm API Server
Receives push notifications from the main Monty system about wake-up schedules
"""

from flask import Flask, request, jsonify
from datetime import datetime
import json
import os
import logging
import signal
import sys

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/pi/monty-alarm/alarm-api.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('monty-alarm-server')

# State file to persist alarm schedule
STATE_FILE = '/home/pi/monty-alarm/alarm_state.json'

def signal_handler(sig, frame):
    """Handle shutdown gracefully"""
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def load_state():
    """Load saved alarm state from file"""
    default_state = {
        'hasAlarm': False,
        'wakeUpTime': None,
        'nextAlarm': None,
        'lastUpdate': None,
        'serverStarted': datetime.now().isoformat()
    }
    
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                loaded_state = json.load(f)
                # Merge with defaults to ensure all keys exist
                default_state.update(loaded_state)
                return default_state
        except Exception as e:
            logger.error(f"Error loading state: {e}")
    
    logger.info("Using default state (no saved state found)")
    return default_state

def save_state(state):
    """Save alarm state to file"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        
        # Add timestamp
        state['lastSaved'] = datetime.now().isoformat()
        
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"State saved: hasAlarm={state.get('hasAlarm')}, wakeUpTime={state.get('wakeUpTime')}")
    except Exception as e:
        logger.error(f"Error saving state: {e}")

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

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    state = load_state()
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'device': 'monty-alarm',
        'version': '1.0.0',
        'uptime': 'available',  # Could calculate actual uptime if needed
        'currentAlarm': {
            'hasAlarm': state.get('hasAlarm', False),
            'wakeUpTime': state.get('wakeUpTime'),
            'nextAlarm': state.get('nextAlarm')
        }
    })

@app.route('/api/schedule/update', methods=['POST'])
def update_schedule():
    """Receive schedule updates from main Monty system"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data received'}), 400
            
        logger.info(f"📨 Received schedule update from Monty: {data}")

        # Extract schedule information
        action = data.get('action', 'unknown')
        schedule = data.get('schedule', {})

        # Load current state and update it
        current_state = load_state()
        
        # Update state with new schedule
        current_state.update({
            'hasAlarm': schedule.get('hasAlarm', False),
            'wakeUpTime': schedule.get('wakeUpTime'),
            'nextAlarm': schedule.get('nextAlarm'),
            'lastUpdate': data.get('timestamp', datetime.now().isoformat()),
            'action': action,
            'daysUntilAlarm': schedule.get('daysUntilAlarm')
        })

        # Save state first
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
    logger.info(f"📁 State file location: {STATE_FILE}")
    
    # Load and display current state on startup
    initial_state = load_state()
    logger.info(f"📊 Current state: hasAlarm={initial_state.get('hasAlarm')}, wakeUpTime={initial_state.get('wakeUpTime')}")
    
    # Update display with current state
    update_alarm_display(initial_state)
    
    try:
        # Run on all interfaces so it's accessible from your network
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)