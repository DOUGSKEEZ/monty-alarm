#!/bin/bash
# Test alarm system using the systemd service

echo "🧪 Testing Alarm System with Service"
echo "===================================="

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to cleanup
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    pkill -f test_alarm
    pkill -f mock_monty
    sudo systemctl start alarm-trigger.service
    exit
}

# Set trap for cleanup on exit
trap cleanup EXIT INT TERM

# 1. Stop the service temporarily
echo "1. Checking service status..."
if systemctl is-active --quiet alarm-trigger.service; then
    echo -e "   ${GREEN}✓${NC} Service is running"
else
    echo -e "   ${RED}✗${NC} Service is not running"
    echo "   Starting service..."
    sudo systemctl start alarm-trigger.service
    sleep 2
fi

# 2. Test service connection
echo ""
echo "2. Testing service connection to API..."

# Start test server for 2 minutes ahead
echo "   Starting test server (alarm in 2 minutes)..."
python3 test-alarm-persistent.py set 2

# Start the server
python3 test-alarm-persistent.py > /tmp/test_server.log 2>&1 &
TEST_SERVER_PID=$!
sleep 2

# Check if server started
if kill -0 $TEST_SERVER_PID 2>/dev/null; then
    echo -e "   ${GREEN}✓${NC} Test server running (PID: $TEST_SERVER_PID)"
else
    echo -e "   ${RED}✗${NC} Test server failed to start"
    exit 1
fi

# 3. Check if service can reach the server
echo ""
echo "3. Testing API endpoint..."
if curl -s http://localhost:3001/api/scheduler/wake-up/status | grep -q "success"; then
    echo -e "   ${GREEN}✓${NC} API endpoint responding"
else
    echo -e "   ${RED}✗${NC} API endpoint not responding"
fi

# 4. Monitor service logs
echo ""
echo "4. Monitoring service logs..."
echo "   Alarm should trigger in ~2 minutes"
echo "   Press Ctrl+C to stop monitoring"
echo ""
echo "Service logs:"
echo "-------------"

# Show last few lines then follow
sudo journalctl -u alarm-trigger.service -n 20 -f
