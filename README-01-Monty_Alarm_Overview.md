# Monty Alarm Clock System Overview 🏠⏰

A comprehensive smart alarm clock system that integrates with the Monty home automation platform.

## Current Directory Structure ✨

```
/home/pi/monty-alarm/
├── config/                      # Runtime configuration (auto-generated)
│   └── mp3_config.json         # Current MP3 selection
├── core/                        # Core system components
│   ├── alarm_button_handler.py  # Physical button input handler
│   ├── alarm_trigger.py         # Main alarm monitoring service
│   ├── mp3_manager.py           # MP3 track management
│   └── wakeup_mode_manager.py   # Wake-up mode selection
├── music/                       # MP3 wake-up tracks
│   ├── Beethoven.mp3
│   └── THE_HIT.mp3
├── scripts/                     # Utility scripts
│   ├── button-service-wrapper.sh # Button handler startup wrapper
│   ├── check-alarm-system.sh    # System health check
│   ├── CLEANUP-TEST.sh          # Test environment cleanup
│   └── quick-alarm-test.sh      # Quick alarm testing
├── services/                    # Systemd service files
│   ├── alarm-buttons.service    # Button handler service definition
│   └── alarm-trigger.service    # Main alarm service definition
├── signals/                     # Inter-process communication
└── tests/                       # Testing infrastructure
    ├── mock_monty_server.py     # Full Monty backend mock
    ├── monty-alarm-test.py      # Alarm time checker
    ├── test-alarm-persistent-fixed.py  # Persistent test server
    └── test-with-service.sh     # Service testing script
```

## System Architecture

```
┌─────────────────────┐
│   Physical Layer    │
├─────────────────────┤
│ • USB Snooze Button │ ──┐
│ • USB Check Button  │ ──┤
│ • 3-Pos Switch (TBD)│   │
└─────────────────────┘   │
                          │
┌─────────────────────┐   │     ┌─────────────────────┐
│   Monty Backend     │   │     │   Button Handler    │
├─────────────────────┤   │     ├─────────────────────┤
│ • Wake-up Schedule  │   └────►│ core/alarm_button_  │
│ • /api/scheduler/   │         │ handler.py          │
│   wake-up/status    │         └──────────┬──────────┘
└──────────┬──────────┘                    │
           │                               │ Signal Files
           │ HTTP                          ▼
           │                    ┌─────────────────────┐
           │                    │  /signals/ folder   │
           │                    │ • alarm_snooze      │
           ▼                    │ • alarm_stop        │
┌─────────────────────┐         │ • alarm_display.txt │
│   Alarm Trigger     │◄────────┴─────────────────────┘
├─────────────────────┤
│ core/alarm_         │         ┌─────────────────────┐
│ trigger.py          │────────►│  Wake-up Manager    │
│ • Polls schedule    │         ├─────────────────────┤
│ • Triggers alarm    │         │ core/wakeup_mode_   │
│ • Handles snooze    │◄────────│ manager.py          │
│ • Volume ramping    │         └─────────────────────┘
└─────────┬───────────┘                   │
          │                               │ Config
          ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│   Music Players     │         │   MP3 Manager       │
├─────────────────────┤         ├─────────────────────┤
│ • Pianobar (Pandora)│         │ core/mp3_manager.py │
│ • mpg123 (MP3s)     │◄────────│ • Select tracks     │
│ • FM Radio (Future) │         │ • Manage library    │
└─────────────────────┘         └─────────────────────┘
```

## System Requirements

The alarm system requires TWO systemd services running:

### 🎯 alarm-trigger.service
- Monitors Monty backend for wake-up times
- Triggers alarms and manages music playback
- Handles snooze timing and volume control

### 🔘 alarm-buttons.service  
- Monitors USB button inputs
- Creates signal files for snooze/stop
- Requires root access for USB device handling

Both services must be active for full functionality!

### 🎯 alarm_trigger.py (623 lines)
The heart of the system - a robust service that:
- Polls Monty backend every 5 seconds for wake-up times
- Triggers alarms within a 90-second window
- Manages music playback with volume ramping
- Handles snooze (9 minutes) and stop signals
- Persists state to prevent duplicate alarms

### 🔘 alarm_button_handler.py
Manages physical USB button inputs:
- **Snooze button** (left): Single press for 9-minute snooze
- **Check button** (right): Short press to check time, long press (2s) to stop

### 🎵 wakeup_mode_manager.py
Central control for wake-up audio sources:
- **Pianobar mode**: Pandora internet radio
- **MP3 mode**: Local music files
- **FM mode**: Radio tuner (future feature)

### 💿 mp3_manager.py
MP3 library management:
- Add/remove tracks from music library
- Select active wake-up track
- Test playback functionality

## Quick Command Reference

### Service Control
```bash
# Start BOTH required services
sudo systemctl start alarm-trigger.service
sudo systemctl start alarm-buttons.service

# Stop both services
sudo systemctl stop alarm-trigger.service
sudo systemctl stop alarm-buttons.service

# Check status of both services
sudo systemctl status alarm-trigger.service
sudo systemctl status alarm-buttons.service

# View live logs (choose one)
sudo journalctl -u alarm-trigger.service -f
sudo journalctl -u alarm-buttons.service -f

# View both services together
sudo journalctl -u alarm-trigger.service -u alarm-buttons.service -f
```

### Wake-Up Configuration
```bash
# Check current mode
python3 core/wakeup_mode_manager.py status

# Switch modes
python3 core/wakeup_mode_manager.py mode pianobar
python3 core/wakeup_mode_manager.py mode mp3
python3 core/wakeup_mode_manager.py mode fm

# Manage MP3s
python3 core/mp3_manager.py list
python3 core/mp3_manager.py select "THE_HIT.mp3"
python3 core/mp3_manager.py play
```

### Testing
```bash
# Quick test with mock server
./scripts/quick-alarm-test.sh

# Full service test
./tests/test-with-service.sh

# Clean shutdown after testing
./scripts/CLEANUP-TEST.sh
```

## Configuration Files

### Auto-Generated (in config/)
- `mp3_config.json` - Selected MP3 track
- `wakeup_config.json` - Current wake-up mode
- `alarm_state.json` - Last alarm trigger time

### Signal Files (in signals/)
- `alarm_snooze` - Created by snooze button
- `alarm_stop` - Created by stop button hold
- `alarm_display.txt` - Current display state

## System Health Check

Run the comprehensive health check:
```bash
./scripts/check-alarm-system.sh
```

This verifies:
- ✅ Service status
- ✅ Audio system
- ✅ Button functionality
- ✅ Server connectivity
- ✅ Music playback

## Key Features

- **Robust error handling** - Handles network failures, missing files, permissions
- **Multiple audio sources** - Pandora, MP3s, FM radio (future)
- **Physical controls** - USB buttons for snooze/stop
- **Smart triggering** - 90-second window prevents missed alarms
- **State persistence** - Survives reboots and restarts
- **Volume ramping** - Gentle wake-up from 60% to 100%
- **Test infrastructure** - Mock servers and test scripts

## Future Enhancements

- [ ] 3-position switch for mode selection
- [ ] FM radio integration
- [ ] LED display for time/status
- [ ] Web interface for configuration
- [ ] Multiple alarm times
- [ ] Weekend/weekday schedules

---

*A 623-line "monstrosity" that reliably wakes you up every morning!* 💪⏰
