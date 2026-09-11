#!/bin/bash
# start_hostel.sh — BioSecure AI Girls Hostel Management System Startup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================================="
echo "  BioSecure AI — Girls Hostel Security & Management System"
echo "================================================================="

# Activate virtualenv if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Check required environment variables
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Copying .env.example to .env..."
        cp .env.example .env
    fi
fi

# Start application server
PORT="${PORT:-5000}"
HOST="${HOST:-0.0.0.0}"

echo "Starting BioSecure AI Girls Hostel server on http://${HOST}:${PORT}..."
exec python3 app.py "$@"
