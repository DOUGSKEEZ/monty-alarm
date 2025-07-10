#!/bin/bash
set -e

# Change to the project directory
cd /home/pi/monty-alarm

# Activate virtual environment
source venv/bin/activate

# Start the server
exec python3 server.py
