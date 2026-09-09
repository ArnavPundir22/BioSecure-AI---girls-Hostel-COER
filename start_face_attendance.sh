#!/bin/bash
# start_face_attendance.sh / start_hostel.sh
#
# Starts the BioSecure AI — Girls Hostel Security System using Gunicorn (production WSGI server).
#
# Usage:
#   ./start_face_attendance.sh
#

set -euo pipefail

# Change to the directory where this script lives.
cd "$(dirname "$0")"

# Activate virtual environment if present.
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Load .env if present.
if [ -f ".env" ]; then
    set -o allexport
    source .env
    set +o allexport
fi

PORT="${PORT:-5000}"

echo "============================================================"
echo " Starting BioSecure AI — Girls Hostel Security System"
echo " Schema Scope : girls_hostel"
echo " Access URL   : http://localhost:${PORT}/hostel/"
echo "============================================================"

# Run with Gunicorn WSGI server on port 5000
exec gunicorn wsgi:app \
    --workers 2 \
    --bind "0.0.0.0:${PORT}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -


