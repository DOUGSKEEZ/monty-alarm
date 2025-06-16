#!/usr/bin/env python3
"""
Set a persistent test alarm that survives reboot
Writes alarm time to a file and serves it
FIXED: Keeps alarm active for 2 minutes after alarm time to ensure trigger window
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime, timedelta
import sys
import os
from pathlib import Path

# File to store alarm time
ALARM_FILE = Path("/home/pi/monty-alarm/test_alarm_time.json")

class PersistentAlarmHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/scheduler/wake-up/status':
            # Read alarm time from file
            try:
                if ALARM_FILE.exists():
                    with open(ALARM_FILE, 'r') as f:
                        data = json.load(f)
                        alarm_time = datetime.fromisoformat(data['alarm_time'])
                        
                    # Check if alarm is still valid (within 2 minutes after alarm time)
                    now = datetime.now()
                    time_since_alarm = (now - alarm_time).total_seconds()
                    
                    # Keep alarm active for 2 minutes after alarm time
                    if -86400 < time_since_alarm < 120:  # -1 day to +2 minutes
                        response = {
                            "success": True,
                            "data": {
                                "enabled": True,
                                "time": alarm_time.strftime("%H:%M:%S"),
                                "nextWakeUp": alarm_time.isoformat() + 'Z',
                                "nextWakeUpDateTime": alarm_time.strftime("%a, %b %d, %-I:%M %p"),
                            }
                        }
                        if time_since_alarm > 0:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Alarm time has passed by {int(time_since_alarm)}s but still returning as active")
                    else:
                        # Alarm has expired
                        response = {
                            "success": True,
                            "data": {
                                "enabled": False,
                                "message": "Test alarm has expired (>2 min past alarm time)"
                            }
                        }
                else:
                    response = {
                        "success": False,
                        "message": "No alarm time set"
                    }
            except Exception as e:
                response = {
                    "success": False,
                    "message": f"Error reading alarm: {e}"
                }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
    def log_message(self, format, *args):
        # Show request logs with timestamp
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] {format % args}")

def set_alarm_time(minutes_from_now):
    """Set alarm time and save to file"""
    alarm_time = datetime.now() + timedelta(minutes=minutes_from_now)
    
    data = {
        "alarm_time": alarm_time.isoformat(),
        "created_at": datetime.now().isoformat(),
        "minutes_ahead": minutes_from_now
    }
    
    with open(ALARM_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    return alarm_time

# Handle command line arguments
if len(sys.argv) > 1:
    if sys.argv[1] == "set":
        # Set mode: just set the alarm and exit
        minutes = 5
        if len(sys.argv) > 2:
            try:
                minutes = int(sys.argv[2])
            except:
                pass
        
        alarm_time = set_alarm_time(minutes)
        print(f"⏰ Persistent alarm set for: {alarm_time.strftime('%H:%M:%S')}")
        print(f"   This alarm will survive reboots!")
        print(f"   Alarm will remain active for 2 minutes after trigger time")
        print(f"   Run 'python3 {sys.argv[0]}' to start the server")
        sys.exit(0)
        
    elif sys.argv[1] == "clear":
        # Clear the alarm
        if ALARM_FILE.exists():
            os.remove(ALARM_FILE)
            print("🗑️ Alarm cleared")
        else:
            print("No alarm to clear")
        sys.exit(0)

# Server mode
print("🎯 Persistent Test Alarm Server (Fixed)")
print("=" * 40)

# Check if alarm is set
if ALARM_FILE.exists():
    with open(ALARM_FILE, 'r') as f:
        data = json.load(f)
        alarm_time = datetime.fromisoformat(data['alarm_time'])
        now = datetime.now()
        time_diff = (alarm_time - now).total_seconds()
        
        if time_diff > 0:
            delta = time_diff
            print(f"⏰ Alarm set for: {alarm_time.strftime('%H:%M:%S')}")
            print(f"   Time remaining: {int(delta/60)}m {int(delta%60)}s")
        elif -120 < time_diff <= 0:
            print(f"🔔 Alarm time reached: {alarm_time.strftime('%H:%M:%S')}")
            print(f"   ({int(-time_diff)}s ago - still active for trigger)")
        else:
            print(f"⏰ Alarm has expired: {alarm_time.strftime('%H:%M:%S')}")
            print(f"   (expired {int(-time_diff/60)} minutes ago)")
else:
    print("❌ No alarm set!")
    print(f"   Run: python3 {sys.argv[0]} set 1")
    print(f"   to set an alarm for 1 minute from now")

print("\n✨ Fixed: Alarm stays active for 2 min after trigger time")
print("Press Ctrl+C to stop (alarm time is saved)\n")

server = HTTPServer(('0.0.0.0', 3001), PersistentAlarmHandler)

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\n👋 Server stopped (alarm time still saved)")
