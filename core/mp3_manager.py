#!/usr/bin/env python3
"""
MP3 Manager for Alarm Clock
Manages wake-up track selection
"""

import os
import json
from pathlib import Path
import shutil

class MP3Manager:
    def __init__(self):
        self.music_dir = Path("/home/pi/monty-alarm/music")
        self.config_file = Path("/home/pi/monty-alarm/mp3_config.json")
        
        # Create music directory if it doesn't exist
        self.music_dir.mkdir(exist_ok=True)
        
        # Load current configuration
        self.load_config()
    
    def load_config(self):
        """Load current MP3 configuration"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "selected_track": None,
                "volume": 80,
                "fade_in": True
            }
    
    def save_config(self):
        """Save MP3 configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def list_tracks(self):
        """List all available MP3 files"""
        tracks = []
        for file in self.music_dir.glob("*.mp3"):
            tracks.append({
                "filename": file.name,
                "path": str(file),
                "size_mb": file.stat().st_size / (1024 * 1024),
                "selected": file.name == self.config.get("selected_track")
            })
        return sorted(tracks, key=lambda x: x["filename"])
    
    def select_track(self, filename):
        """Select a track as the wake-up song"""
        track_path = self.music_dir / filename
        
        if not track_path.exists():
            return {"success": False, "message": f"Track '{filename}' not found"}
        
        if not filename.endswith('.mp3'):
            return {"success": False, "message": "Only MP3 files supported"}
        
        self.config["selected_track"] = filename
        self.save_config()
        
        return {
            "success": True, 
            "message": f"Selected '{filename}' as wake-up track",
            "track": filename
        }
    
    def get_selected_track(self):
        """Get the currently selected track"""
        if self.config.get("selected_track"):
            track_path = self.music_dir / self.config["selected_track"]
            if track_path.exists():
                return {
                    "exists": True,
                    "filename": self.config["selected_track"],
                    "path": str(track_path)
                }
        
        return {"exists": False, "filename": None, "path": None}
    
    def add_track(self, source_path, new_name=None):
        """Copy an MP3 file to the music directory"""
        source = Path(source_path)
        
        if not source.exists():
            return {"success": False, "message": "Source file not found"}
        
        if not source.suffix.lower() == '.mp3':
            return {"success": False, "message": "Only MP3 files supported"}
        
        # Use original name or provided new name
        filename = new_name if new_name else source.name
        dest_path = self.music_dir / filename
        
        # Don't overwrite existing files
        if dest_path.exists():
            return {"success": False, "message": f"File '{filename}' already exists"}
        
        try:
            shutil.copy2(source, dest_path)
            return {
                "success": True,
                "message": f"Added '{filename}' to music library",
                "filename": filename
            }
        except Exception as e:
            return {"success": False, "message": f"Error copying file: {e}"}
    
    def remove_track(self, filename):
        """Remove a track from the music directory"""
        track_path = self.music_dir / filename
        
        if not track_path.exists():
            return {"success": False, "message": "Track not found"}
        
        # If this was the selected track, clear selection
        if self.config.get("selected_track") == filename:
            self.config["selected_track"] = None
            self.save_config()
        
        try:
            track_path.unlink()
            return {"success": True, "message": f"Removed '{filename}'"}
        except Exception as e:
            return {"success": False, "message": f"Error removing file: {e}"}

# CLI interface
if __name__ == "__main__":
    import sys
    
    manager = MP3Manager()
    
    if len(sys.argv) == 1:
        # No arguments - show status
        print("🎵 MP3 Alarm Manager")
        print("=" * 40)
        
        selected = manager.get_selected_track()
        if selected["exists"]:
            print(f"Selected track: {selected['filename']}")
        else:
            print("No track selected!")
        
        print("\nAvailable tracks:")
        tracks = manager.list_tracks()
        if tracks:
            for track in tracks:
                marker = "→" if track["selected"] else " "
                print(f"{marker} {track['filename']} ({track['size_mb']:.1f} MB)")
        else:
            print("  No MP3 files found in /home/pi/monty-alarm/music/")
        
        print("\nCommands:")
        print("  python3 mp3_manager.py list              - List all tracks")
        print("  python3 mp3_manager.py select <file>     - Select wake-up track")
        print("  python3 mp3_manager.py add <path>        - Add MP3 to library")
        print("  python3 mp3_manager.py remove <file>     - Remove from library")
        print("  python3 mp3_manager.py play              - Test selected track")
    
    elif sys.argv[1] == "list":
        tracks = manager.list_tracks()
        for track in tracks:
            marker = "→" if track["selected"] else " "
            print(f"{marker} {track['filename']}")
    
    elif sys.argv[1] == "select" and len(sys.argv) > 2:
        result = manager.select_track(sys.argv[2])
        print(result["message"])
    
    elif sys.argv[1] == "add" and len(sys.argv) > 2:
        result = manager.add_track(sys.argv[2])
        print(result["message"])
    
    elif sys.argv[1] == "remove" and len(sys.argv) > 2:
        result = manager.remove_track(sys.argv[2])
        print(result["message"])
    
    elif sys.argv[1] == "play":
        selected = manager.get_selected_track()
        if selected["exists"]:
            print(f"Playing: {selected['filename']}")
            print("Press Ctrl+C to stop")
            os.system(f"mpg123 '{selected['path']}'")
        else:
            print("No track selected!")
    
    else:
        print("Invalid command. Run without arguments for help.")
