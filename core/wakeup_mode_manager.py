#!/usr/bin/env python3
"""
Wake-Up Mode Manager for Monty Alarm Clock
Manages switching between Pianobar, MP3, and FM Radio modes
"""

import json
import os
from pathlib import Path
import subprocess

class WakeupModeManager:
    def __init__(self):
        self.config_file = Path("/home/pi/monty-alarm/wakeup_config.json")
        self.mp3_config_file = Path("/home/pi/monty-alarm/mp3_config.json")
        self.music_dir = Path("/home/pi/monty-alarm/music")
        
        # Valid modes
        self.MODES = {
            "pianobar": "Pandora Internet Radio (Pianobar)",
            "mp3": "Local MP3 File",
            "fm": "FM Radio (Coming Soon)"
        }
        
        # Load current configuration
        self.load_config()
    
    def load_config(self):
        """Load current wake-up configuration"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            # Default configuration
            self.config = {
                "mode": "pianobar",
                "mp3_track": None,
                "fm_station": "101.1",  # Default FM station
                "volume": 80
            }
    
    def save_config(self):
        """Save wake-up configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get_current_mode(self):
        """Get the current wake-up mode"""
        return self.config.get("mode", "pianobar")
    
    def set_mode(self, mode):
        """Set the wake-up mode"""
        if mode not in self.MODES:
            return {
                "success": False,
                "message": f"Invalid mode '{mode}'. Valid modes: {', '.join(self.MODES.keys())}"
            }
        
        old_mode = self.config.get("mode", "pianobar")
        self.config["mode"] = mode
        self.save_config()
        
        # Update MP3 config file for backward compatibility
        if mode == "mp3" and self.config.get("mp3_track"):
            # Create mp3_config.json for alarm_trigger.py
            mp3_config = {
                "selected_track": self.config["mp3_track"],
                "volume": self.config.get("volume", 80),
                "fade_in": True
            }
            with open(self.mp3_config_file, 'w') as f:
                json.dump(mp3_config, f, indent=2)
        else:
            # Remove mp3_config.json if not in MP3 mode
            if self.mp3_config_file.exists():
                self.mp3_config_file.unlink()
        
        return {
            "success": True,
            "message": f"Wake-up mode changed from '{old_mode}' to '{mode}'",
            "mode": mode,
            "description": self.MODES[mode]
        }
    
    def select_mp3(self, filename):
        """Select an MP3 track (doesn't change mode automatically)"""
        track_path = self.music_dir / filename
        
        if not track_path.exists():
            return {"success": False, "message": f"Track '{filename}' not found"}
        
        self.config["mp3_track"] = filename
        self.save_config()
        
        # If we're in MP3 mode, update the mp3_config.json
        if self.config.get("mode") == "mp3":
            mp3_config = {
                "selected_track": filename,
                "volume": self.config.get("volume", 80),
                "fade_in": True
            }
            with open(self.mp3_config_file, 'w') as f:
                json.dump(mp3_config, f, indent=2)
        
        return {
            "success": True,
            "message": f"Selected '{filename}' as MP3 wake-up track",
            "track": filename
        }
    
    def set_fm_station(self, station):
        """Set FM radio station (for future use)"""
        self.config["fm_station"] = station
        self.save_config()
        
        return {
            "success": True,
            "message": f"FM station set to {station} (FM radio coming soon)",
            "station": station
        }
    
    def get_status(self):
        """Get complete wake-up configuration status"""
        mode = self.config.get("mode", "pianobar")
        status = {
            "mode": mode,
            "description": self.MODES[mode],
            "details": {}
        }
        
        if mode == "pianobar":
            status["details"] = {
                "info": "Pandora internet radio via Pianobar",
                "ready": True
            }
        elif mode == "mp3":
            mp3_track = self.config.get("mp3_track")
            if mp3_track:
                track_path = self.music_dir / mp3_track
                status["details"] = {
                    "track": mp3_track,
                    "exists": track_path.exists(),
                    "ready": track_path.exists()
                }
            else:
                status["details"] = {
                    "track": None,
                    "ready": False,
                    "message": "No MP3 track selected"
                }
        elif mode == "fm":
            status["details"] = {
                "station": self.config.get("fm_station", "101.1"),
                "ready": False,
                "message": "FM radio support coming soon"
            }
        
        return status
    
    def list_mp3_tracks(self):
        """List available MP3 tracks"""
        tracks = []
        for file in self.music_dir.glob("*.mp3"):
            tracks.append({
                "filename": file.name,
                "selected": file.name == self.config.get("mp3_track"),
                "current_mode_mp3": self.config.get("mode") == "mp3"
            })
        return sorted(tracks, key=lambda x: x["filename"])
    
    def test_current_mode(self):
        """Test the current wake-up mode"""
        mode = self.config.get("mode", "pianobar")
        
        print(f"🔊 Testing {self.MODES[mode]}...")
        
        if mode == "pianobar":
            print("Starting Pianobar for 10 seconds...")
            proc = subprocess.Popen(['pianobar'], 
                                  stdout=subprocess.DEVNULL, 
                                  stderr=subprocess.DEVNULL)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("✅ Pianobar test complete")
            
        elif mode == "mp3":
            mp3_track = self.config.get("mp3_track")
            if mp3_track:
                track_path = self.music_dir / mp3_track
                if track_path.exists():
                    print(f"Playing '{mp3_track}' for 10 seconds...")
                    proc = subprocess.Popen(['mpg123', '-q', str(track_path)],
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    print("✅ MP3 test complete")
                else:
                    print(f"❌ MP3 track '{mp3_track}' not found!")
            else:
                print("❌ No MP3 track selected!")
                
        elif mode == "fm":
            print("📻 FM Radio test not yet implemented")
            print("   Will tune to station:", self.config.get("fm_station", "101.1"))

# CLI interface
if __name__ == "__main__":
    import sys
    
    manager = WakeupModeManager()
    
    if len(sys.argv) == 1:
        # No arguments - show status
        print("🎵 Wake-Up Mode Manager")
        print("=" * 40)
        
        status = manager.get_status()
        print(f"Current Mode: {status['mode'].upper()}")
        print(f"Description: {status['description']}")
        
        if status['mode'] == 'mp3':
            if status['details'].get('track'):
                print(f"Selected Track: {status['details']['track']}")
                print(f"Track Ready: {'Yes' if status['details']['ready'] else 'No - File not found!'}")
            else:
                print("Selected Track: None")
        elif status['mode'] == 'fm':
            print(f"FM Station: {status['details']['station']}")
        
        print("\nCommands:")
        print("  python3 wakeup_mode_manager.py mode <pianobar|mp3|fm>")
        print("  python3 wakeup_mode_manager.py status")
        print("  python3 wakeup_mode_manager.py list")
        print("  python3 wakeup_mode_manager.py select <mp3_file>")
        print("  python3 wakeup_mode_manager.py station <fm_freq>")
        print("  python3 wakeup_mode_manager.py test")
    
    elif sys.argv[1] == "mode" and len(sys.argv) > 2:
        result = manager.set_mode(sys.argv[2])
        print(result["message"])
        if result["success"] and sys.argv[2] == "mp3" and not manager.config.get("mp3_track"):
            print("⚠️  Note: No MP3 track selected. Use 'select' command to choose one.")
    
    elif sys.argv[1] == "status":
        status = manager.get_status()
        print(f"Mode: {status['mode']} - {status['description']}")
        print(f"Details: {json.dumps(status['details'], indent=2)}")
    
    elif sys.argv[1] == "list":
        tracks = manager.list_mp3_tracks()
        print("Available MP3 tracks:")
        for track in tracks:
            marker = "→" if track["selected"] and track["current_mode_mp3"] else " "
            selected = " (selected)" if track["selected"] else ""
            print(f"{marker} {track['filename']}{selected}")
    
    elif sys.argv[1] == "select" and len(sys.argv) > 2:
        result = manager.select_mp3(sys.argv[2])
        print(result["message"])
        if result["success"] and manager.config.get("mode") != "mp3":
            print("ℹ️  Note: Currently in {} mode. Switch to MP3 mode to use this track.".format(
                manager.config.get("mode", "pianobar").upper()
            ))
    
    elif sys.argv[1] == "station" and len(sys.argv) > 2:
        result = manager.set_fm_station(sys.argv[2])
        print(result["message"])
    
    elif sys.argv[1] == "test":
        manager.test_current_mode()
    
    else:
        print("Invalid command. Run without arguments for help.")
