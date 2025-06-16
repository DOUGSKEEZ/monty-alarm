# Alarm Trigger Service 🎯

The heart of the Monty Alarm Clock - monitors for wake-up time and triggers your morning alarm with music, volume ramping, snooze, and more!

## What It Does

`alarm_trigger.py` is a 600+ line Python service that:
- 📡 Polls the Monty backend server for wake-up times
- ⏰ Triggers alarms at the exact right moment
- 🎵 Plays wake-up music (Pianobar/MP3/FM)
- 📈 Gradually increases volume from 60% to 100%
- 😴 Handles 9-minute snooze with physical button
- 🛑 Stops alarm with long-press of check button
- 💾 Remembers if alarm already triggered today
- 🔄 Runs 24/7 as a systemd service

## Architecture

```
┌─────────────────┐     HTTP      ┌──────────────────┐
│ Monty Backend   │◄─────────────►│ alarm_trigger.py │
│ (Port 3001)     │ Wake-up Time  │   (Service)      │
└─────────────────┘               └────────┬─────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
              ┌──────────┐         ┌──────────┐         ┌──────────┐
              │ Pianobar │         │ mpg123   │         │ FM Radio │
              │ (Pandora)│         │ (MP3s)   │         │ (Future) │
              └──────────┘         └──────────┘         └──────────┘
```

## Key Features

### 🔍 Smart Polling
- Checks for alarm time every 5 seconds
- Connects to localhost:3001 first (testing)
- Falls back to 192.168.0.15:3001 (production)
- Handles connection failures gracefully

### ⏱️ Trigger Window
- 90-second window after alarm time
- Prevents missing alarms between checks
- Only triggers once per day
- Resets at midnight

### 🎵 Music Playback
- Reads wake-up mode from `wakeup_config.json`
- Falls back to Pianobar if MP3 not found
- Kills existing players before starting
- Non-blocking volume ramp

### 💤 Snooze System
- 9-minute snooze duration
- Triggered by `/home/pi/monty-alarm/signals/alarm_snooze` file
- Multiple snoozes allowed
- Music stops during snooze

### 🛑 Stop Mechanism
- Long-press creates `/home/pi/monty-alarm/signals/alarm_stop` file
- Checks for stop signal 5 times per second
- Immediate music termination
- Resets volume to 80%

## File Structure

```
/home/pi/monty-alarm/
├── alarm_trigger.py          # This service
├── alarm_state.json          # Persistent state (last trigger time)
├── wakeup_config.json        # Wake-up mode configuration
├── mp3_config.json           # MP3 selection (if in MP3 mode)
├── signals/                  # Button signal files
│   ├── alarm_snooze         # Created by snooze button
│   ├── alarm_stop           # Created by stop button (long press)
│   └── alarm_display.txt    # Display status (WAKE!/SNZ/etc)
└── music/                    # MP3 files directory
```

## Service Management

### Start/Stop/Restart
```bash
# Start the service
sudo systemctl start alarm-trigger.service

# Stop the service
sudo systemctl stop alarm-trigger.service

# Restart the service
sudo systemctl restart alarm-trigger.service

# Check status
sudo systemctl status alarm-trigger.service
```

### View Logs
```bash
# Live logs
sudo journalctl -u alarm-trigger.service -f

# Last 100 lines
sudo journalctl -u alarm-trigger.service -n 100

# Logs from today
sudo journalctl -u alarm-trigger.service --since today
```

## Testing

### Manual Test Run
```bash
# Run directly (not as service)
python3 /home/pi/monty-alarm/alarm_trigger.py
```

### Test with Mock Server
```bash
# Terminal 1: Start test server
python3 test-alarm-persistent-fixed.py set 2  # 2-minute alarm
python3 test-alarm-persistent-fixed.py &

# Terminal 2: Watch the service
sudo journalctl -u alarm-trigger.service -f
```

### Force Reset State
```bash
# Clear "already triggered today" flag
touch /home/pi/monty-alarm/reset_alarm_state
sudo systemctl restart alarm-trigger.service
```

## Configuration

### Constants (in alarm_trigger.py)
```python
CHECK_INTERVAL = 5              # How often to check for alarm (seconds)
SNOOZE_MINUTES = 9             # Snooze duration
VOLUME_RAMP_SECONDS = 10       # Time to reach 100% volume
ALARM_DURATION_MINUTES = 60    # Auto-stop after 1 hour
MIN_VOLUME = 60                # Starting volume (%)
TRIGGER_WINDOW_SECONDS = 90    # Window after alarm time to trigger
```

### Wake-Up Modes
See `wakeup_mode_manager.py` to configure:
- Pianobar (Pandora)
- MP3 (local files)
- FM Radio (coming soon)

## Troubleshooting

### Alarm Won't Trigger
```bash
# 1. Check if service is running
sudo systemctl status alarm-trigger.service

# 2. Check if alarm is set
curl http://localhost:3001/api/scheduler/wake-up/status | jq

# 3. Clear state and restart
rm -f /home/pi/monty-alarm/alarm_state.json
touch /home/pi/monty-alarm/reset_alarm_state
sudo systemctl restart alarm-trigger.service
```

### Music Won't Play
```bash
# Kill stuck processes
pkill -9 pianobar
pkill -9 mpg123

# Check audio system
pactl info
speaker-test -t wav -c 2

# Test music directly
pianobar  # Ctrl+C to exit
mpg123 /home/pi/monty-alarm/music/*.mp3
```

### Buttons Not Working
```bash
# Check button handler service
sudo systemctl status alarm-button-handler.service

# Test signal files manually
sudo touch /home/pi/monty-alarm/signals/alarm_snooze
# Should see snooze activate in logs

sudo touch /home/pi/monty-alarm/signals/alarm_stop
# Should stop alarm
```

### Volume Issues
```bash
# Set volume manually
pactl set-sink-volume @DEFAULT_SINK@ 80%

# List audio sinks
pactl list short sinks
```

## How It All Works Together

1. **Every 5 seconds**: Checks Monty server for wake-up time
2. **When alarm time arrives**: Triggers if not already triggered today
3. **Music starts**: At 60% volume, gradually increasing
4. **User presses snooze**: Music stops, resumes in 9 minutes
5. **User holds stop**: Alarm stops completely
6. **After 1 hour**: Auto-stops if user doesn't intervene
7. **At midnight**: Resets for next day

## Debug Output Examples

### Normal Operation
```
⏰ Next alarm: Mon 06:30 (in 5m 23s)
⏰ Next alarm: Mon 06:30 (in 5m 18s)
⏰ DEBUG: Approaching alarm time!
   Wake time: 06:30:00
   Current time: 06:29:50
   Time until: 10.0s
   Triggered today: False
   Alarm active: False
🎯 TRIGGER CONDITIONS MET! Time until: -5.0s
⏰ ALARM TRIGGERED at 06:30:05!
🎵 Starting wake-up music...
   Wake-up mode: PIANOBAR
   Starting Pianobar...
✅ Music started, volume ramping up...
```

### Snooze Activated
```
📁 Found snooze file at 06:32:15: /home/pi/monty-alarm/signals/alarm_snooze
💤 Snooze activated until 06:41
🛑 Stopping music...
😴 Snoozing until 06:41
```

### Stop Button Pressed
```
🛑 Found stop file at 06:33:22: /home/pi/monty-alarm/signals/alarm_stop
   ✓ Removed stop file with os.remove
🛑 Stop button pressed - stopping alarm
✋ Alarm stopped by user
```

## Development Notes

- **623 lines** because it handles every edge case!
- **Async/await** for non-blocking operation
- **Multiple file removal methods** for permission issues
- **Extensive logging** for debugging
- **Graceful degradation** when services unavailable

---

*The alarm clock that actually wakes you up!* ⏰💪