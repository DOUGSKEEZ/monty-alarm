#!/usr/bin/env python3
"""
Alarm Trigger Logic for Monty Alarm Clock
Monitors for alarm time and triggers wake-up sequence

FIXED: Separate snooze (pause music) from dismiss (reset daily flag)
"""

import asyncio
import subprocess
import json
from datetime import datetime, timedelta
import signal
import sys
import os
import time
from pathlib import Path

# Configuration
CHECK_INTERVAL = 5  # Check every 5 seconds for better accuracy
SNOOZE_MINUTES = 9
VOLUME_RAMP_SECONDS = 10
ALARM_DURATION_MINUTES = 60  # Auto-stop after 1 hour
MIN_VOLUME = 10  # Start at 10%
MAX_VOLUME = 35 # Experimenting with max volume at 30
TRIGGER_WINDOW_SECONDS = 90  # Expanded trigger window

class AlarmTrigger:
    def __init__(self):
        self.running = True
        self.alarm_active = False
        self.snooze_until = None
        self.music_process = None
        self.music_type = "pianobar"  # Default to pianobar
        self.volume_task = None
        self.last_alarm_time = None
        self.alarm_triggered_today = False
        
        # State file for persistence
        self.state_file = Path("/home/pi/monty-alarm/alarm_state.json")
        self.load_state()
        
        # Signal files directory
        self.signals_dir = Path("/home/pi/monty-alarm/signals")
        self.signals_dir.mkdir(exist_ok=True, parents=True)
        
        # Clean up any leftover signal files on startup
        self.cleanup_signal_files()
        
    def load_state(self):
        """Load persistent state"""
        try:
            # Check for reset flag
            reset_flag = Path("/home/pi/monty-alarm/reset_alarm_state")
            if reset_flag.exists():
                print("🔄 Reset flag found - clearing alarm state")
                self.alarm_triggered_today = False
                self.last_alarm_time = None
                try:
                    reset_flag.unlink()
                except:
                    pass
                return
                
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    last_alarm = state.get('last_alarm_time')
                    if last_alarm:
                        self.last_alarm_time = datetime.fromisoformat(last_alarm)
                        # Check if alarm was today
                        if self.last_alarm_time.date() == datetime.now().date():
                            self.alarm_triggered_today = True
                            print(f"📅 Alarm already triggered today at {self.last_alarm_time.strftime('%H:%M')}")
        except Exception as e:
            print(f"Could not load state: {e}")
            
    def save_state(self):
        """Save persistent state"""
        try:
            state = {
                'last_alarm_time': self.last_alarm_time.isoformat() if self.last_alarm_time else None
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"Could not save state: {e}")
    
    def cleanup_signal_files(self):
        """Remove any leftover signal files"""
        signal_files = [
            self.signals_dir / 'alarm_snooze',
            self.signals_dir / 'alarm_stop',
            Path('/tmp/alarm_snooze'),  # Legacy locations
            Path('/tmp/alarm_stop')
        ]
        
        for f in signal_files:
            try:
                if f.exists():
                    os.remove(f)
                    print(f"🧹 Cleaned up leftover file: {f}")
            except Exception as e:
                # Try with sudo if regular remove fails
                try:
                    subprocess.run(['sudo', 'rm', '-f', str(f)], capture_output=True)
                    print(f"🧹 Cleaned up leftover file with sudo: {f}")
                except:
                    print(f"⚠️ Could not clean up {f}: {e}")
            
    async def get_wake_time(self):
        """Get wake time from Monty server using new push notification system with proper timezone handling"""
        try:
            # FIRST: Try to get from local state (push notifications)
            state_file = Path("/home/pi/monty-alarm/alarm_state.json")
            if state_file.exists():
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                        if state.get('hasAlarm') and state.get('nextAlarm'):
                            # Parse the ISO format time from push notifications
                            next_alarm_str = state['nextAlarm']
                            
                            # Handle timezone conversion properly
                            if next_alarm_str.endswith('Z'):
                                # UTC time - convert to local
                                from datetime import timezone
                                wake_time = datetime.fromisoformat(next_alarm_str.replace('Z', '+00:00'))
                                # Convert UTC to local time
                                wake_time = wake_time.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                            else:
                                # Already local time
                                wake_time = datetime.fromisoformat(next_alarm_str)
                            
                            print(f"   ✓ Got alarm from push notification: {wake_time.strftime('%H:%M')} (converted from UTC)")
                            return wake_time
                        else:
                            print(f"   ✗ Push notification shows no alarm set")
                except Exception as e:
                    print(f"   ⚠️ Could not parse push notification state: {e}")
            
            # FALLBACK: Try to fetch from server directly
            for url in ["http://192.168.0.15:3001"]:  # Only try real server, not localhost
                try:
                    # Use asyncio timeout instead of curl timeout
                    proc = await asyncio.wait_for(
                        asyncio.create_subprocess_exec(
                            'curl', '-s', '--connect-timeout', '2', '--max-time', '3',
                            f'{url}/api/scheduler/wake-up/status',
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        ),
                        timeout=5.0
                    )
                    
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        print(f"   ✗ {url}: Timeout")
                        continue
                    
                    if proc.returncode == 0 and stdout:
                        data = json.loads(stdout)
                        
                        if data.get('success') and data.get('data', {}).get('enabled'):
                            # Parse the wake-up time from API response
                            time_str = data['data'].get('time', '')
                            if time_str:
                                hour, minute = map(int, time_str.split(':')[:2])
                                now = datetime.now()
                                wake_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                                
                                # If time has passed today, it's for tomorrow
                                if wake_time <= now:
                                    wake_time += timedelta(days=1)
                                
                                print(f"   ✓ Got alarm from server API: {wake_time.strftime('%H:%M')} (local time)")
                                return wake_time
                        else:
                            print(f"   ✗ {url}: No alarm enabled")
                    else:
                        print(f"   ✗ {url}: Connection failed")
                except Exception as e:
                    print(f"   ✗ {url}: {type(e).__name__}: {str(e)}")
                    continue
                    
        except Exception as e:
            print(f"Error getting wake time: {e}")
            
        return None
        
    async def check_snooze(self):
        """Check if snooze button was pressed"""
        try:
            # Check both possible locations
            snooze_files = [
                self.signals_dir / 'alarm_snooze',
                Path('/tmp/alarm_snooze')
            ]
            
            for snooze_file in snooze_files:
                if snooze_file.exists():
                    print(f"📁 Found snooze file at {datetime.now().strftime('%H:%M:%S')}: {snooze_file}")
                    
                    # Try to remove the file
                    removed = False
                    try:
                        os.remove(snooze_file)
                        removed = True
                    except:
                        # Try renaming as alternative
                        try:
                            snooze_file.rename(f'{snooze_file}_{int(time.time())}')
                            removed = True
                        except:
                            # Try with subprocess
                            try:
                                subprocess.run(['sudo', 'rm', '-f', str(snooze_file)], capture_output=True)
                                removed = True
                            except:
                                pass
                    
                    if self.alarm_active:
                        self.snooze_until = datetime.now() + timedelta(minutes=SNOOZE_MINUTES)
                        print(f"💤 Snooze activated until {self.snooze_until.strftime('%H:%M')}")
                        return True
                    else:
                        print("⚠️ Snooze pressed but alarm not active")
                        
        except Exception as e:
            print(f"❌ Error checking snooze: {e}")
        return False
        
    async def check_stop(self):
        """Check if stop button was pressed (holding check alarm)"""
        try:
            # Check both possible locations
            stop_files = [
                self.signals_dir / 'alarm_stop',
                Path('/tmp/alarm_stop')
            ]
            
            for stop_file in stop_files:
                if stop_file.exists():
                    print(f"🛑 Found stop file at {datetime.now().strftime('%H:%M:%S')}: {stop_file}")
                    
                    # Try multiple methods to remove the file
                    removed = False
                    
                    # Method 1: Direct remove
                    try:
                        os.remove(stop_file)
                        removed = True
                        print("   ✓ Removed stop file with os.remove")
                    except Exception as e1:
                        print(f"   ✗ os.remove failed: {e1}")
                        
                        # Method 2: Path unlink
                        try:
                            stop_file.unlink()
                            removed = True
                            print("   ✓ Removed stop file with unlink")
                        except Exception as e2:
                            print(f"   ✗ unlink failed: {e2}")
                            
                            # Method 3: Subprocess
                            try:
                                result = subprocess.run(['rm', '-f', str(stop_file)], 
                                                      capture_output=True, text=True)
                                if result.returncode == 0:
                                    removed = True
                                    print("   ✓ Removed stop file with rm command")
                                else:
                                    print(f"   ✗ rm failed: {result.stderr}")
                            except Exception as e3:
                                print(f"   ✗ subprocess rm failed: {e3}")
                                
                                # Method 4: sudo rm
                                try:
                                    subprocess.run(['sudo', 'rm', '-f', str(stop_file)], capture_output=True)
                                    removed = True
                                    print("   ✓ Removed stop file with sudo rm")
                                except:
                                    pass
                    
                    if self.alarm_active:
                        print("🛑 Stop button pressed - stopping alarm")
                        return True
                    else:
                        print("⚠️ Stop pressed but alarm not active")
                        
        except Exception as e:
            print(f"❌ Error checking stop: {e}")
        return False
        
    async def start_music(self):
        """Start music playbook based on wake-up mode configuration"""
        print("🎵 Starting wake-up music...")
        
        # Check if music is already playing
        mpg123_check = subprocess.run(['pgrep', 'mpg123'], capture_output=True)
        pianobar_check = subprocess.run(['pgrep', 'pianobar'], capture_output=True)
        
        if mpg123_check.returncode == 0 or pianobar_check.returncode == 0:
            print("   ⚠️ Music already playing, skipping start")
            return
        
        # Kill any existing music players first (just in case)
        subprocess.run(['pkill', '-9', 'mpg123'], capture_output=True)
        subprocess.run(['pkill', '-9', 'pianobar'], capture_output=True)
        await asyncio.sleep(0.5)  # Give time for processes to die
        
        # Update display
        display_file = self.signals_dir / 'alarm_display.txt'
        try:
            with open(display_file, 'w') as f:
                f.write("WAKE!")
        except:
            pass
            
        try:
            # Set initial volume (10% as low volume for amp)
            subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{MIN_VOLUME}%'], 
                         capture_output=True)
            
            # Load wake-up mode configuration
            wakeup_config_file = Path("/home/pi/monty-alarm/wakeup_config.json")
            wakeup_mode = "pianobar"  # Default
            
            if wakeup_config_file.exists():
                try:
                    with open(wakeup_config_file, 'r') as f:
                        wakeup_config = json.load(f)
                        wakeup_mode = wakeup_config.get("mode", "pianobar")
                except:
                    print("   ⚠️ Could not load wake-up config, using Pianobar")
            
            print(f"   Wake-up mode: {wakeup_mode.upper()}")
            
            if wakeup_mode == "mp3":
                # Check for MP3 configuration
                mp3_config_file = Path("/home/pi/monty-alarm/mp3_config.json")
                if mp3_config_file.exists():
                    try:
                        with open(mp3_config_file, 'r') as f:
                            mp3_config = json.load(f)
                            if mp3_config.get("selected_track"):
                                mp3_path = Path("/home/pi/monty-alarm/music") / mp3_config["selected_track"]
                                if mp3_path.exists():
                                    print(f"   Playing MP3: {mp3_config['selected_track']}")
                                    self.music_process = await asyncio.create_subprocess_exec(
                                        'mpg123', '--loop', '-1', str(mp3_path),
                                        stdout=asyncio.subprocess.DEVNULL,
                                        stderr=asyncio.subprocess.DEVNULL
                                    )
                                    self.music_type = "mp3"
                                else:
                                    print(f"   ❌ MP3 file not found: {mp3_config['selected_track']}")
                                    print("   Falling back to Pianobar")
                                    wakeup_mode = "pianobar"
                    except Exception as e:
                        print(f"   ❌ Error loading MP3 config: {e}")
                        print("   Falling back to Pianobar")
                        wakeup_mode = "pianobar"
                else:
                    print("   ❌ No MP3 selected, falling back to Pianobar")
                    wakeup_mode = "pianobar"
            
            elif wakeup_mode == "fm":
                # FM Radio placeholder
                print("   📻 FM Radio not yet implemented")
                print("   Falling back to Pianobar")
                wakeup_mode = "pianobar"
            
            # Default to Pianobar
            if wakeup_mode == "pianobar" or not hasattr(self, 'music_process'):
                print("   Starting Pianobar...")
                self.music_process = await asyncio.create_subprocess_exec(
                    'pianobar',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                self.music_type = "pianobar"
            
            # Start volume ramp as a background task (non-blocking)
            self.volume_task = asyncio.create_task(self.ramp_volume())
            
            print("✅ Music started, volume ramping up...")
            
        except Exception as e:
            print(f"❌ Error starting music: {e}")

    async def ramp_volume(self):
        """Gradual volume increase (runs in background)"""
        print(f"📈 Ramping up volume from {MIN_VOLUME}% to {MAX_VOLUME}% over {VOLUME_RAMP_SECONDS} seconds...")
        
        # Calculate step size and delay
        volume_range = MAX_VOLUME - MIN_VOLUME
        steps = volume_range // 2  # Increase by 2% each step
        if steps == 0:
            steps = 1  # At least one step
        step_delay = VOLUME_RAMP_SECONDS / steps
        
        current_volume = MIN_VOLUME
        
        for step in range(steps):
            if not self.alarm_active:  # Stop if alarm was cancelled
                break
                
            current_volume = MIN_VOLUME + (step * 2)
            if current_volume > MAX_VOLUME:
                current_volume = MAX_VOLUME
                
            subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{current_volume}%'], 
                        capture_output=True)
            
            print(f"   🔊 Volume: {current_volume}%")
            
            # Use small sleep intervals to be more responsive
            for _ in range(int(step_delay * 4)):  # 4 checks per step
                if not self.alarm_active:
                    break
                await asyncio.sleep(0.25)
                
        print(f"✅ Volume ramp complete at {MAX_VOLUME}%")

    async def pause_music_for_snooze(self):
        """Pause music for snooze without resetting daily alarm flag"""
        print("⏸️ Pausing music for snooze...")
        
        # Cancel volume ramp if it's still running
        if hasattr(self, 'volume_task') and self.volume_task and not self.volume_task.done():
            self.volume_task.cancel()
            try:
                await self.volume_task
            except asyncio.CancelledError:
                pass
        
        # Kill music player completely
        if hasattr(self, 'music_type') and self.music_type == "mp3":
            subprocess.run(['pkill', '-9', 'mpg123'], capture_output=True)
        else:
            subprocess.run(['pkill', '-9', 'pianobar'], capture_output=True)
        
        # Clear the process reference
        self.music_process = None
            
        # Reset volume to SAFE level
        subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '25%'], 
                    capture_output=True)
        
        print("🔊 Volume reset to 25%")
        
        # Clear display (will be updated with snooze time)
        display_file = self.signals_dir / 'alarm_display.txt'
        try:
            with open(display_file, 'w') as f:
                f.write("")
        except:
            pass
        
        # 🔒 IMPORTANT: DO NOT reset alarm_triggered_today during snooze!
        # The alarm is still active, just paused
        print("💤 Music paused for snooze - alarm still active for today")
            
        # Small delay to ensure music player is fully dead
        await asyncio.sleep(0.5)

    async def dismiss_alarm_completely(self):
        """Completely dismiss the alarm and reset daily alarm flag"""
        print("🛑 Dismissing alarm completely...")
        
        # First pause the music
        await self.pause_music_for_snooze()
        
        # 🆕 NOW reset the daily flag since alarm is fully dismissed
        self.alarm_triggered_today = False
        self.last_alarm_time = None
        self.save_state()
        print("🔄 Alarm dismissed completely - ready for new alarms today!")
            
    async def trigger_alarm(self):
        """Trigger the alarm sequence"""
        print(f"\n⏰ ALARM TRIGGERED at {datetime.now().strftime('%H:%M:%S')}!")
        
        self.alarm_active = True
        self.last_alarm_time = datetime.now()
        self.alarm_triggered_today = True
        self.save_state()
        
        # Start music
        await self.start_music()
        
        # Monitor for snooze or timeout
        alarm_start = datetime.now()
        
        print("📊 Entering alarm monitor loop...")
        check_counter = 0
        
        while self.alarm_active:
            check_counter += 1
            if check_counter % 30 == 0:  # Print every 30 checks (30 seconds)
                elapsed = int((datetime.now() - alarm_start).total_seconds())
                print(f"   ⏳ Alarm active for {elapsed}s...")
            
            # Check for stop button - this completely dismisses the alarm
            if await self.check_stop():
                print("✋ Alarm stopped by user - dismissing completely")
                await self.dismiss_alarm_completely()
                break
                
            # Check for snooze - this only pauses music temporarily
            if await self.check_snooze():
                await self.pause_music_for_snooze()
                print(f"😴 Snoozing until {self.snooze_until.strftime('%H:%M')}")
                
                # Update display with snooze info
                display_file = self.signals_dir / 'alarm_display.txt'
                try:
                    with open(display_file, 'w') as f:
                        f.write(f"SNZ {self.snooze_until.strftime('%H:%M')}")
                except:
                    pass
                
                # Wait for snooze period
                while datetime.now() < self.snooze_until and self.alarm_active:
                    # Still check for stop during snooze (complete dismissal)
                    if await self.check_stop():
                        print("✋ Alarm dismissed during snooze")
                        await self.dismiss_alarm_completely()
                        self.alarm_active = False
                        break
                    await asyncio.sleep(5)
                    
                # Restart music if still in alarm mode
                if self.alarm_active:
                    print("⏰ Snooze time over, resuming alarm...")
                    await self.start_music()
                    
            # Check for timeout - this also completely dismisses the alarm
            if datetime.now() - alarm_start > timedelta(minutes=ALARM_DURATION_MINUTES):
                print("⏱️ Alarm timeout reached - dismissing completely")
                await self.dismiss_alarm_completely()
                break
                
            # Check more frequently for better button responsiveness
            await asyncio.sleep(0.2)  # Check 5 times per second
            
        # Clean up
        self.alarm_active = False
        print("✅ Alarm sequence complete")
        
    async def monitor_loop(self):
        """Main monitoring loop"""
        print("🔍 Starting alarm monitor...")
        print(f"   Check interval: {CHECK_INTERVAL} seconds")
        print(f"   Snooze duration: {SNOOZE_MINUTES} minutes")
        print(f"   Volume ramp: {MIN_VOLUME}% to {MAX_VOLUME}% over {VOLUME_RAMP_SECONDS}s")
        print(f"   Trigger window: {TRIGGER_WINDOW_SECONDS} seconds")
        
        while self.running:
            try:
                # Get current wake time
                wake_time = await self.get_wake_time()
                
                if wake_time:
                    now = datetime.now()
                    time_until = (wake_time - now).total_seconds()
                    
                    # Reset daily flag at midnight
                    if now.hour == 0 and now.minute < 1:
                        self.alarm_triggered_today = False
                        print("🌙 New day - alarm flag reset")
                    
                    # Debug logging near trigger time
                    if -120 <= time_until <= 120:  # Within 2 minutes of alarm
                        print(f"⏰ DEBUG: Approaching alarm time!")
                        print(f"   Wake time: {wake_time.strftime('%H:%M:%S')}")
                        print(f"   Current time: {now.strftime('%H:%M:%S')}")
                        print(f"   Time until: {time_until:.1f}s")
                        print(f"   Triggered today: {self.alarm_triggered_today}")
                        print(f"   Alarm active: {self.alarm_active}")
                    
                    # Format time display
                    if time_until > 0:
                        hours = int(time_until / 3600)
                        minutes = int((time_until % 3600) / 60)
                        seconds = int(time_until % 60)
                        
                        if hours > 0:
                            time_str = f"{hours}h {minutes}m"
                        elif minutes > 0:
                            time_str = f"{minutes}m {seconds}s"
                        else:
                            time_str = f"{seconds}s"
                            
                        print(f"⏰ Next alarm: {wake_time.strftime('%a %H:%M')} (in {time_str})")
                    
                    # Check if it's time to trigger
                    trigger_start = 10    # Start checking 10 seconds early
                    trigger_end = -30     # Stop checking 30 seconds after
                    # Expanded trigger window: up to TRIGGER_WINDOW_SECONDS after alarm time
                    if trigger_end <= time_until <= trigger_start and not self.alarm_triggered_today and not self.alarm_active:
                        print(f"🎯 TRIGGER CONDITIONS MET! Time until: {time_until:.1f}s")
                        await self.trigger_alarm()
                    elif time_until < -TRIGGER_WINDOW_SECONDS and not self.alarm_triggered_today:
                        # We missed the window!
                        print(f"⚠️ WARNING: Missed trigger window! Time since alarm: {-time_until:.1f}s")
                        # Mark as triggered to avoid repeated warnings
                        self.alarm_triggered_today = True
                        self.save_state()
                else:
                    print("💤 No alarm set or server unreachable")
                    
            except Exception as e:
                print(f"❌ Monitor error: {e}")
                import traceback
                traceback.print_exc()
                
            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)
            
    def cleanup(self):
        """Clean up resources"""
        self.running = False
        # Force kill music players
        subprocess.run(['pkill', '-9', 'pianobar'], capture_output=True)
        subprocess.run(['pkill', '-9', 'mpg123'], capture_output=True)
        # Clear any status files
        for f in [
            self.signals_dir / 'alarm_display.txt',
            self.signals_dir / 'alarm_snooze',
            self.signals_dir / 'alarm_stop',
            Path('/tmp/alarm_display.txt'),
            Path('/tmp/alarm_snooze'),
            Path('/tmp/alarm_stop')
        ]:
            try:
                if f.exists():
                    os.remove(f)
            except:
                pass

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print("\n🛑 Shutting down alarm trigger...")
    try:
        trigger.cleanup()
        # Make sure both music players are killed
        subprocess.run(['pkill', '-9', 'pianobar'], capture_output=True)
        subprocess.run(['pkill', '-9', 'mpg123'], capture_output=True)
        # Reset terminal
        subprocess.run(['stty', 'sane'], capture_output=True)
    except:
        pass
    sys.exit(0)

async def main():
    global trigger
    
    # Immediate output to confirm script starts
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Alarm trigger starting...", flush=True)
    
    # Create trigger instance
    trigger = AlarmTrigger()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("⏰ Monty Alarm Clock Trigger")
    print("=" * 40)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Press Ctrl+C to exit\n")
    
    # Run the monitor loop
    await trigger.monitor_loop()

if __name__ == "__main__":
    # Run the async main
    asyncio.run(main())