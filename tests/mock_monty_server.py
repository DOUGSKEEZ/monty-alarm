#!/usr/bin/env python3
"""
Mock Monty server for testing alarm clock when not on home network
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime, timedelta
import threading
import time

class MockMontyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/scheduler/wake-up/status':
            # Calculate next wake up time (tomorrow at 7:00 AM)
            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            next_wakeup = tomorrow.replace(hour=7, minute=0, second=0, microsecond=0)
            
            # If it's before 7 AM today, use today instead
            today_7am = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now < today_7am:
                next_wakeup = today_7am
            
            response = {
                "success": True,
                "data": {
                    "enabled": True,
                    "time": "07:00",
                    "nextWakeUpTime": "07:00:00",
                    "nextWakeUp": next_wakeup.isoformat() + 'Z',  # For optimized script
                    "nextWakeUpDateTime": next_wakeup.strftime("%a, %b %d, %-I:%M %p"),
                    "lastTriggered": None,
                    "lastTriggered_formatted": None,
                    "goodMorningDelayMinutes": 30,
                    "currentTime": now.strftime("%b %d, %-I:%M %p"),
                    "currentDate": now.strftime("%-m/%-d/%Y, %-I:%M:%S %p"),
                    "timezone": "America/Denver (Mountain Time)"
                }
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/api/health':
            response = {
                "status": "ok",
                "message": "Mock Monty server is running",
                "time": datetime.now().isoformat()
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
        else:
            self.send_response(404)
            self.end_headers()
            
    def log_message(self, format, *args):
        # Suppress default logging
        pass

class MockMontyServer:
    def __init__(self, port=3001):
        self.port = port
        self.server = None
        self.thread = None
        
    def start(self):
        """Start mock server in background thread"""
        self.server = HTTPServer(('0.0.0.0', self.port), MockMontyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        print(f"✅ Mock Monty server running on port {self.port}")
        print(f"   Test with: curl http://localhost:{self.port}/api/scheduler/wake-up/status")
        
    def stop(self):
        """Stop mock server"""
        if self.server:
            self.server.shutdown()
            self.thread.join()
            print("🛑 Mock server stopped")

if __name__ == "__main__":
    print("🎭 Mock Monty Server")
    print("=" * 50)
    
    server = MockMontyServer(3001)
    server.start()
    
    try:
        print("\nPress Ctrl+C to stop\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n")
        server.stop()
