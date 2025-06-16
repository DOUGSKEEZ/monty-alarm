# Wake-Up Mode Manager 🎵

Control how your Monty Alarm Clock wakes you up! Choose between Pandora (Pianobar), local MP3 files, or FM Radio (coming soon).

## Quick Start

### Check Current Mode
```bash
python3 wakeup_mode_manager.py
```

### Switch Modes
```bash
# Use Pandora Internet Radio
python3 wakeup_mode_manager.py mode pianobar

# Use local MP3 file
python3 wakeup_mode_manager.py mode mp3

# Use FM Radio (coming soon)
python3 wakeup_mode_manager.py mode fm
```

## MP3 Mode Setup

### 1. Add MP3 Files
```bash
# Copy MP3s to the music folder
cp your-favorite-song.mp3 /home/pi/monty-alarm/music/

# Or use the mp3_manager
python3 mp3_manager.py add /path/to/song.mp3
```

### 2. Select Your Wake-Up Song
```bash
# List available songs
python3 wakeup_mode_manager.py list

# Select a song
python3 wakeup_mode_manager.py select "your-favorite-song.mp3"

# Switch to MP3 mode
python3 wakeup_mode_manager.py mode mp3
```

### 3. Test It
```bash
python3 wakeup_mode_manager.py test
```

## All Commands

| Command | Description | Example |
|---------|-------------|---------|
| `mode <type>` | Set wake-up mode | `mode pianobar` |
| `status` | Show detailed status | `status` |
| `list` | List available MP3s | `list` |
| `select <file>` | Choose MP3 track | `select wake-up.mp3` |
| `station <freq>` | Set FM station (future) | `station 101.1` |
| `test` | Test current mode | `test` |

## Mode Details

### 🎹 Pianobar Mode
- Streams Pandora internet radio
- Requires internet connection
- Uses your configured Pandora account
- Random wake-up songs every day!

### 💿 MP3 Mode
- Plays a local MP3 file on loop
- No internet required
- Choose your perfect wake-up song
- Consistent wake-up experience

### 📻 FM Radio Mode (Coming Soon)
- Will tune to your favorite FM station
- Hardware integration pending
- Station preset ready: `python3 wakeup_mode_manager.py station 101.1`

## Configuration Files

The system uses these files (automatically managed):

- `/home/pi/monty-alarm/wakeup_config.json` - Main mode configuration
- `/home/pi/monty-alarm/mp3_config.json` - MP3-specific settings (backward compatible)
- `/home/pi/monty-alarm/music/` - MP3 files directory

## Hardware Switch Integration (Future)

When you wire up your 3-position switch:

```bash
# Position 1 - Pianobar
gpio_pin_1 → python3 wakeup_mode_manager.py mode pianobar

# Position 2 - MP3
gpio_pin_2 → python3 wakeup_mode_manager.py mode mp3

# Position 3 - FM Radio
gpio_pin_3 → python3 wakeup_mode_manager.py mode fm
```

## Troubleshooting

### MP3 Won't Play
```bash
# Check if file exists and mode is correct
python3 wakeup_mode_manager.py status

# Test the MP3 directly
python3 mp3_manager.py play
```

### Want to Switch Back to Pianobar
```bash
python3 wakeup_mode_manager.py mode pianobar
```

### See What Will Play at Wake-Up
```bash
python3 wakeup_mode_manager.py status
```

## Examples

### Set Up Your Favorite Song
```bash
# Add the song
cp ~/Music/good-morning.mp3 /home/pi/monty-alarm/music/

# Select it
python3 wakeup_mode_manager.py select "good-morning.mp3"

# Switch to MP3 mode
python3 wakeup_mode_manager.py mode mp3

# Verify
python3 wakeup_mode_manager.py status
```

### Quick Mode Toggle
```bash
# Toggle between Pianobar and your selected MP3
current_mode=$(python3 wakeup_mode_manager.py status | grep "Mode:" | awk '{print $2}')
if [ "$current_mode" = "pianobar" ]; then
    python3 wakeup_mode_manager.py mode mp3
else
    python3 wakeup_mode_manager.py mode pianobar
fi
```

---

*Part of the Monty Smart Alarm Clock System* 🏠⏰