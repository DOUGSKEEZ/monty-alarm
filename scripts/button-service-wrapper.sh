#!/bin/bash
# Wrapper script for button handler service

echo "Starting button handler wrapper..."
echo "Current user: $(whoami)"
echo "Current directory: $(pwd)"
echo "Python path: $(which python3)"

# Change to the right directory
cd /home/pi/monty-alarm

# Run the button handler
exec /usr/bin/python3 -u /home/pi/monty-alarm/core/alarm_button_handler.py
