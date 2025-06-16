#!/usr/bin/env python3
"""
Alarm check script for testing - uses localhost mock server
Based on the optimized version
"""
import socket
import json
from datetime import datetime
import time
import sys

# Use localhost for testing
MONTY_HOST = "localhost"
MONTY_PORT = 3001

def get_wake_time_socket():
    """Ultra-fast socket-based implementation"""
    try:
        # Create socket with aggressive timeout
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        
        # Connect
        sock.connect((MONTY_HOST, MONTY_PORT))
        
        # Send minimal HTTP request
        request = (
            "GET /api/scheduler/wake-up/status HTTP/1.0\r\n"
            f"Host: {MONTY_HOST}\r\n"
            "\r\n"
        ).encode()
        sock.sendall(request)
        
        # Read response
        response = b""
        sock.settimeout(0.3)
        
        while True:
            try:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                response += chunk
                if b"}" in response and b"\r\n\r\n" in response:
                    break
            except socket.timeout:
                break
        
        sock.close()
        
        # Parse response
        if b"\r\n\r\n" in response:
            header, body = response.split(b"\r\n\r\n", 1)
            if b"200 OK" in header and body:
                start = body.find(b"{")
                end = body.rfind(b"}") + 1
                if start >= 0 and end > start:
                    json_str = body[start:end]
                    data = json.loads(json_str)
                    
                    # Check both possible fields for next wake up
                    wake_str = data.get('data', {}).get('nextWakeUp')
                    if not wake_str:
                        # Fallback for real Monty format
                        wake_str = data.get('nextWakeUp')
                    
                    if wake_str:
                        wake_time = datetime.fromisoformat(wake_str.replace('Z', '+00:00'))
                        return wake_time
        
        return None
        
    except Exception as e:
        if "--debug" in sys.argv:
            print(f"Error: {e}")
        return None

def format_time_for_display(wake_time):
    """Format time for display"""
    if wake_time:
        local_time = wake_time.replace(tzinfo=None)
        hour = local_time.hour
        minute = local_time.minute
        
        # Convert to 12-hour format
        if hour == 0:
            hour = 12
        elif hour > 12:
            hour -= 12
            
        return f"{hour}:{minute:02d}"
    else:
        return "NONE"

def check_alarm_once():
    """Check alarm time once"""
    start = time.time()
    
    wake_time = get_wake_time_socket()
    display_text = format_time_for_display(wake_time)
    
    elapsed = time.time() - start
    
    if wake_time:
        print(f"✓ {display_text}")
    else:
        print("✗ No alarm")
    
    if "--debug" in sys.argv:
        print(f"Response time: {elapsed:.3f}s")
        if wake_time:
            print(f"Raw time: {wake_time}")
    
    # Write to display file
    try:
        with open('/tmp/alarm_display.txt', 'w') as f:
            f.write(display_text)
    except:
        pass
    
    return wake_time

if __name__ == "__main__":
    if "--server" in sys.argv:
        # Run mock server
        from mock_monty_server import MockMontyServer
        server = MockMontyServer(3001)
        server.start()
        
        try:
            print("\nMock server running. Press Ctrl+C to stop\n")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
    else:
        # Normal check
        check_alarm_once()
