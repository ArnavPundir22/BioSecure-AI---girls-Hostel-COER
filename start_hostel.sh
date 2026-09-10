#!/bin/bash
# start_hostel.sh — Shortcut to start BioSecure AI Girls Hostel Security System
exec "$(dirname "$0")/start_face_attendance.sh" "$@"
