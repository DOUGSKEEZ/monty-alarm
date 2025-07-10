#!/usr/bin/env python3
"""
Test script to capture all key events from button devices
"""

import evdev
from evdev import InputDevice, categorize, ecodes
import asyncio
import sys

# Device paths
SNOOZE_DEVICE_PATH = "/dev/input/event7"
ALARM_DEVICE_PATH = "/dev/input/event2"

async def monitor_device(device_path, device_name):
    """Monitor a device for all key events"""
    try:
        device = InputDevice(device_path)
        print(f"📟 Monitoring {device_name} at {device_path}")
        print(f"   Device name: {device.name}")
        
        async for event in device.async_read_loop():
            if event.type == ecodes.EV_KEY:
                key_name = ecodes.KEY[event.code] if event.code in ecodes.KEY else f"UNKNOWN({event.code})"
                value_name = "PRESS" if event.value == 1 else "RELEASE" if event.value == 0 else "REPEAT"
                print(f"   {device_name}: {key_name} {value_name} (code={event.code}, value={event.value})")
                
    except Exception as e:
        print(f"❌ Error monitoring {device_name}: {e}")

async def main():
    print("🔍 Testing button key codes...")
    print("Press your buttons and watch for the key codes!")
    print("=" * 50)
    
    # Create monitoring tasks
    tasks = []
    
    try:
        tasks.append(asyncio.create_task(
            monitor_device(SNOOZE_DEVICE_PATH, "SNOOZE")
        ))
    except Exception as e:
        print(f"❌ Could not connect SNOOZE device: {e}")
        
    try:
        tasks.append(asyncio.create_task(
            monitor_device(ALARM_DEVICE_PATH, "ALARM")
        ))
    except Exception as e:
        print(f"❌ Could not connect ALARM device: {e}")
    
    if not tasks:
        print("❌ No devices could be connected!")
        return
        
    # Run until interrupted
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("\n👋 Shutting down...")

if __name__ == "__main__":
    # Check if running as root
    import os
    if os.geteuid() != 0:
        print("⚠️  This script needs root access to read keyboard events")
        print("   Run with: sudo python3 test_button_keys.py")
        sys.exit(1)
        
    # Run the async main
    asyncio.run(main()) 