#!/usr/bin/env python3
"""
Alarm Clock Button Handler using USB single-key keyboards
Maps KEY_A events to SNOOZE and CHECK ALARM functions
"""

import evdev
from evdev import InputDevice, categorize, ecodes
import asyncio
import subprocess
from datetime import datetime
import sys
import signal
import time
import os
from pathlib import Path

# Device paths we identified
SNOOZE_DEVICE_PATH = "/dev/input/event7"
ALARM_DEVICE_PATH = "/dev/input/event2"

# Long press threshold (seconds)
LONG_PRESS_THRESHOLD = 1.5

class AlarmButtonHandler:
    def __init__(self):
        self.snooze_device = None
        self.alarm_device = None
        self.running = True
        
        # Button press tracking
        self.alarm_button_pressed_at = None
        
    def setup_devices(self):
        """Initialize the input devices"""
        try:
            self.snooze_device = InputDevice(SNOOZE_DEVICE_PATH)
            print(f"✅ SNOOZE button connected: {self.snooze_device.name}")
        except Exception as e:
            print(f"❌ Could not connect SNOOZE button: {e}")
            
        try:
            self.alarm_device = InputDevice(ALARM_DEVICE_PATH)
            print(f"✅ ALARM CHECK button connected: {self.alarm_device.name}")
        except Exception as e:
            print(f"❌ Could not connect ALARM CHECK button: {e}")
            
        if not self.snooze_device and not self.alarm_device:
            print("❌ No buttons connected! Exiting...")
            return False
            
        return True
        
    async def handle_snooze(self):
        """Handle snooze button press"""
        print(f"\n💤 SNOOZE pressed at {datetime.now().strftime('%H:%M:%S')}")
        
        # Create snooze trigger file for alarm process
        try:
            Path('/home/pi/monty-alarm/signals/alarm_snooze').touch()
            # Make it readable/writable by everyone
            Path('/home/pi/monty-alarm/signals/alarm_snooze').chmod(0o666)
            print("   ⏰ Snooze signal sent to alarm")
        except Exception as e:
            print(f"   ❌ Error setting snooze: {e}")
        
    async def handle_check_alarm_press(self):
        """Handle check alarm button press (start of press)"""
        self.alarm_button_pressed_at = time.time()
        print(f"\n🔍 CHECK ALARM pressed at {datetime.now().strftime('%H:%M:%S')}")
        
    async def handle_check_alarm_release(self):
        """Handle check alarm button release"""
        if self.alarm_button_pressed_at is None:
            return
            
        press_duration = time.time() - self.alarm_button_pressed_at
        self.alarm_button_pressed_at = None
        
        if press_duration >= LONG_PRESS_THRESHOLD:
            # Long press - stop alarm
            print(f"   🛑 LONG PRESS ({press_duration:.1f}s) - Stopping alarm")
            try:
                Path('/home/pi/monty-alarm/signals/alarm_stop').touch()
                Path('/home/pi/monty-alarm/signals/alarm_stop').chmod(0o666)
                print("   ✅ Stop signal sent to alarm")
            except Exception as e:
                print(f"   ❌ Error stopping alarm: {e}")
        else:
            # Short press - check alarm time
            print(f"   ⏱️ Short press ({press_duration:.1f}s) - Checking alarm")
            await self.check_alarm_time()
            
    async def check_alarm_time(self):
        """Check and display alarm time"""
        try:
            result = subprocess.run(
                ['python3', '/home/pi/monty-alarm/monty-alarm-test.py'],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            
            output = result.stdout.strip()
            print(f"   📅 {output}")
            
            # Also check if alarm is currently active
            if Path('/home/pi/monty-alarm/signals/alarm_display.txt').exists():
                with open('/home/pi/monty-alarm/signals/alarm_display.txt', 'r') as f:
                    display = f.read().strip()
                    if display == "WAKE!":
                        print("   🔔 ALARM IS CURRENTLY ACTIVE!")
                    elif display.startswith("SNZ"):
                        print(f"   😴 Currently snoozing: {display}")
                        
        except subprocess.TimeoutExpired:
            print("   ⚠️ Timeout checking alarm")
            with open('/home/pi/monty-alarm/signals/alarm_display.txt', 'w') as f:
                f.write("ERR")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            with open('/home/pi/monty-alarm/signals/alarm_display.txt', 'w') as f:
                f.write("ERR")
                
    async def monitor_device(self, device, button_type):
        """Monitor a device for button presses"""
        if not device:
            return
            
        print(f"📟 Monitoring {button_type} button...")
        
        try:
            async for event in device.async_read_loop():
                # Only respond to KEY_A events
                if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_A:
                    if button_type == "SNOOZE":
                        # Snooze only responds to press, not release
                        if event.value == 1:  # Press
                            await self.handle_snooze()
                    elif button_type == "ALARM":
                        # Alarm button tracks press and release for long press
                        if event.value == 1:  # Press
                            await self.handle_check_alarm_press()
                        elif event.value == 0:  # Release
                            await self.handle_check_alarm_release()
                        
        except Exception as e:
            print(f"❌ Error monitoring {button_type}: {e}")
            
    async def run(self):
        """Main event loop"""
        print("\n🎯 Alarm Clock Button Handler Started")
        print("=" * 50)
        print("SNOOZE button (left):")
        print("  • Press to snooze alarm for 9 minutes")
        print("\nCHECK button (right):")
        print("  • Short press to check alarm time")
        print("  • Hold 2+ seconds to stop alarm")
        print("\nPress Ctrl+C to exit\n")
        
        # Create monitoring tasks
        tasks = []
        
        if self.snooze_device:
            tasks.append(asyncio.create_task(
                self.monitor_device(self.snooze_device, "SNOOZE")
            ))
            
        if self.alarm_device:
            tasks.append(asyncio.create_task(
                self.monitor_device(self.alarm_device, "ALARM")
            ))
            
        # Run until interrupted
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            print("\n👋 Shutting down...")
            
    def cleanup(self):
        """Clean up resources"""
        if self.snooze_device:
            self.snooze_device.close()
        if self.alarm_device:
            self.alarm_device.close()
            
        # Clean up any trigger files
        for f in ['/home/pi/monty-alarm/signals/alarm_snooze', '/home/pi/monty-alarm/signals/alarm_stop']:
            try:
                if Path(f).exists():
                    Path(f).unlink()
            except:
                pass

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print("\n🛑 Received shutdown signal")
    handler.cleanup()
    sys.exit(0)

async def main():
    global handler
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create handler
    handler = AlarmButtonHandler()
    
    # Setup devices
    if not handler.setup_devices():
        return
        
    try:
        # Run the handler
        await handler.run()
    finally:
        handler.cleanup()

if __name__ == "__main__":
    # Check if running as root
    import os
    if os.geteuid() != 0:
        print("⚠️  This script needs root access to read keyboard events")
        print("   Run with: sudo python3 alarm_button_handler.py")
        sys.exit(1)
        
    # Run the async main
    asyncio.run(main())
