#!/bin/bash
# Cleanup script for alarm test environment

echo "🧹 Cleaning up alarm test environment..."

# Stop test server
echo "Stopping test alarm server..."
pkill -f test-alarm-persistent

# Stop alarm trigger service
echo "Stopping alarm trigger service..."
sudo systemctl stop alarm-trigger.service

# Kill any music players
echo "Stopping any music players..."
pkill -9 pianobar
pkill -9 mpg123

# Wait a moment
sleep 1

# Clean up files
echo "Removing test files..."
rm -f /home/pi/monty-alarm/test_alarm_time.json
rm -f /home/pi/monty-alarm/alarm_state.json
rm -rf /home/pi/monty-alarm/signals/*

# Reset audio volume
echo "Resetting audio volume..."
pactl set-sink-volume @DEFAULT_SINK@ 80% 2>/dev/null || true

echo "✅ Cleanup complete!"
echo ""
echo "To run tests again:"
echo "  sudo systemctl start alarm-trigger.service"
echo "  python3 test-alarm-persistent-fixed.py set 1"
echo "  python3 test-alarm-persistent-fixed.py &"
