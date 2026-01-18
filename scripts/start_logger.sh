#!/bin/bash

# Navigate to edge-agent directory
cd "$(dirname "$0")/.."

PID_FILE="scripts/sensor_logger.pid"

if [ -f "$PID_FILE" ]; then
    if ps -p $(cat "$PID_FILE") > /dev/null; then
        echo "Sensor logger is already running (PID: $(cat "$PID_FILE"))"
        exit 1
    else
        echo "Found stale PID file. Removing..."
        rm "$PID_FILE"
    fi
fi

# Start logger
echo "Starting sensor_logger.py..."
# redirect stdout/stderr to /dev/null as internal logging is handling file output
./env/bin/python scripts/sensor_logger.py > /dev/null 2>&1 &
PID=$!
echo $PID > "$PID_FILE"
echo "Sensor logger started with PID $PID"
