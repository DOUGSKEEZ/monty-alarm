#!/bin/bash
# Check if alarm system is ready after boot

echo "🏥 Monty Alarm System Health Check"
echo "===================================="
echo "Time: $(date)"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check services
echo "1. Checking Services..."

check_service() {
    local service=$1
    if systemctl is-active --quiet $service; then
        echo -e "   ${GREEN}✓${NC} $service is running"
        return 0
    else
        echo -e "   ${RED}✗${NC} $service is not running"
        systemctl status $service --no-pager | grep -E "(Active:|Main PID:)" | sed 's/^/      /'
        return 1
    fi
}

SERVICES_OK=true
check_service alarm-trigger.service || SERVICES_OK=false
check_service alarm-buttons.service || SERVICES_OK=false

# Check button devices
echo ""
echo "2. Checking Button Devices..."

check_device() {
    local device=$1
    local name=$2
    if [ -e "$device" ]; then
        echo -e "   ${GREEN}✓${NC} $name exists at $device"
        return 0
    else
        echo -e "   ${RED}✗${NC} $name missing at $device"
        return 1
    fi
}

# Get current device paths from the button handler
SNOOZE_DEV=$(grep "SNOOZE_DEVICE_PATH =" /home/pi/monty-alarm/alarm_button_handler.py | cut -d'"' -f2)
ALARM_DEV=$(grep "ALARM_DEVICE_PATH =" /home/pi/monty-alarm/alarm_button_handler.py | cut -d'"' -f2)

DEVICES_OK=true
check_device "$SNOOZE_DEV" "SNOOZE button" || DEVICES_OK=false
check_device "$ALARM_DEV" "ALARM button" || DEVICES_OK=false

# Check if devices might have changed
echo ""
echo "   Current HID devices:"
for device in /dev/input/event*; do
    if [ -e "$device" ]; then
        # Check if it's a HID 8808:6600 device
        info=$(udevadm info --query=all --name=$device 2>/dev/null | grep -E "(ID_VENDOR_ID=8808|HID 8808:6600)" || true)
        if [ -n "$info" ]; then
            # Check if it has KEY_A capability
            if python3 -c "import evdev; d=evdev.InputDevice('$device'); import sys; sys.exit(0 if 30 in d.capabilities().get(1,[]) else 1)" 2>/dev/null; then
                echo -e "      ${GREEN}$device${NC} - HID button device (has KEY_A)"
            else
                echo "      $device - HID device (no KEY_A)"
            fi
        fi
    fi
done

# Check audio
echo ""
echo "3. Checking Audio..."

if pactl info >/dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} PulseAudio is running"
    
    # Check for Fosi Audio
    if pactl list sinks | grep -q "Fosi Audio"; then
        echo -e "   ${GREEN}✓${NC} Fosi Audio ZD3 detected"
    else
        echo -e "   ${YELLOW}!${NC} Fosi Audio ZD3 not detected"
    fi
else
    echo -e "   ${RED}✗${NC} PulseAudio not running"
fi

# Check Pianobar
if command -v pianobar >/dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} Pianobar installed"
else
    echo -e "   ${RED}✗${NC} Pianobar not installed"
fi

# Check alarm state
echo ""
echo "4. Checking Alarm State..."

if [ -f /home/pi/monty-alarm/alarm_state.json ]; then
    echo -e "   ${GREEN}✓${NC} Alarm state file exists"
    echo "      Content: $(cat /home/pi/monty-alarm/alarm_state.json)"
else
    echo -e "   ${YELLOW}!${NC} No alarm state file (normal for first run)"
fi

# Check network (for Monty server)
echo ""
echo "5. Checking Network..."

if ping -c 1 -W 2 192.168.0.15 >/dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} Can reach Monty server (192.168.0.15)"
else
    echo -e "   ${YELLOW}!${NC} Cannot reach Monty server (will use mock)"
fi

# Summary
echo ""
echo "===================================="
if [ "$SERVICES_OK" = true ] && [ "$DEVICES_OK" = true ]; then
    echo -e "${GREEN}✅ System is READY${NC}"
    echo "   Alarm system should work after reboot"
else
    echo -e "${RED}❌ System has ISSUES${NC}"
    echo "   Check the errors above"
fi

echo ""
echo "Quick Actions:"
echo "  • View alarm trigger logs: sudo journalctl -u alarm-trigger.service -f"
echo "  • View button logs: sudo journalctl -u alarm-buttons.service -f"
echo "  • Test alarm: python3 /home/pi/monty-alarm/test_alarm_immediate.py 30"
echo "  • Find button devices: sudo python3 /home/pi/monty-alarm/find_button_devices.py"
