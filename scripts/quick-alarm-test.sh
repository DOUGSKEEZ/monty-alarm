#!/bin/bash
# Quick alarm test script

echo "🧪 Quick Alarm Test"
echo "=================="

# Kill any existing test server
pkill -f test-alarm-persistent

# Check if alarm trigger service is running
if ! systemctl is-active --quiet alarm-trigger.service; then
    echo "⚠️  Starting alarm-trigger service..."
    sudo systemctl start alarm-trigger.service
    sleep 2
fi

# Set alarm time
MINUTES=${1:-1}  # Default to 1 minute if not specified
echo "⏰ Setting alarm for $MINUTES minute(s) from now..."
cd /home/pi/monty-alarm/tests
python3 test-alarm-persistent-fixed.py set $MINUTES

# Start the test server
echo "🚀 Starting test server..."
python3 test-alarm-persistent-fixed.py &
SERVER_PID=$!
echo "   Server PID: $SERVER_PID"

# Give it a moment to start
sleep 1

# Check if server is running
if ps -p $SERVER_PID > /dev/null; then
    echo "✅ Test server running on port 3001"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Watch logs: sudo journalctl -u alarm-trigger.service -f"
    echo "   2. Stop test: kill $SERVER_PID"
    echo "   3. Or run: pkill -f test-alarm-persistent"
else
    echo "❌ Test server failed to start!"
fi
