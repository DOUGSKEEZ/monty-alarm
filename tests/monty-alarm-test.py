#!/usr/bin/env python3
"""
Quick test script to check alarm status from real Monty server with proper timezone handling
"""

import requests
import json
from datetime import datetime, timezone

def check_alarm_from_push_notification():
    """Check alarm from local push notification state (fastest)"""
    try:
        with open('/home/pi/monty-alarm/alarm_state.json', 'r') as f:
            state = json.load(f)
            
        if state.get('hasAlarm'):
            wake_time = state.get('wakeUpTime', 'Unknown')
            next_alarm = state.get('nextAlarm', '')
            
            if next_alarm:
                # Parse the next alarm time with proper timezone handling
                try:
                    if next_alarm.endswith('Z'):
                        # UTC time - convert to local
                        alarm_dt = datetime.fromisoformat(next_alarm.replace('Z', '+00:00'))
                        # Convert UTC to local time
                        alarm_dt = alarm_dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                    else:
                        # Already local time
                        alarm_dt = datetime.fromisoformat(next_alarm)
                    
                    # Calculate time until alarm
                    now = datetime.now()
                    time_until = alarm_dt - now
                    
                    if time_until.days < 0:
                        return f"Alarm was set for {wake_time} (MISSED - {-time_until.days} days ago)"
                    elif time_until.total_seconds() < 0:
                        return f"Alarm was set for {wake_time} (MISSED - {int(-time_until.total_seconds())}s ago)"
                    else:
                        hours = int(time_until.total_seconds() // 3600)
                        minutes = int((time_until.total_seconds() % 3600) // 60)
                        local_time = alarm_dt.strftime('%H:%M')
                        return f"Alarm set for {wake_time} at {local_time} local (in {hours}h {minutes}m)"
                except Exception as e:
                    return f"Alarm set for {wake_time} (timezone parse error: {e})"
            else:
                return f"Alarm set for {wake_time}"
        else:
            return "No alarm set (from push notification)"
            
    except FileNotFoundError:
        return "No push notification state found"
    except Exception as e:
        return f"Error reading push state: {e}"

def check_alarm_from_server():
    """Check alarm from Monty server API (fallback)"""
    try:
        # Try the real Monty server
        response = requests.get(
            'http://192.168.0.15:3001/api/scheduler/wake-up/status',
            timeout=3
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data.get('data', {}).get('enabled'):
                wake_time = data['data'].get('time', 'Unknown')
                next_wake = data['data'].get('nextWakeUpDateTime', '')
                timezone_info = data['data'].get('timezone', 'Unknown timezone')
                return f"Alarm set for {wake_time} - {next_wake} ({timezone_info}) (from server API)"
            else:
                return "No alarm set (from server API)"
        else:
            return f"Server error: {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return "Cannot connect to Monty server"
    except requests.exceptions.Timeout:
        return "Monty server timeout"
    except Exception as e:
        return f"Error: {e}"

def main():
    print("🔍 Checking alarm status with timezone handling...")
    print(f"🕐 Pi local time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"🌍 Pi UTC time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # Try push notification first (instant)
    push_result = check_alarm_from_push_notification()
    print(f"📨 Push notification: {push_result}")
    
    # Try server API as backup
    server_result = check_alarm_from_server()
    print(f"🌐 Server API: {server_result}")
    
    # Show alarm state file for debugging
    try:
        with open('/home/pi/monty-alarm/alarm_state.json', 'r') as f:
            state = json.load(f)
            next_alarm_raw = state.get('nextAlarm', 'None')
            print(f"🔍 Raw nextAlarm from file: {next_alarm_raw}")
    except:
        print("🔍 Could not read alarm state file")

if __name__ == "__main__":
    main()