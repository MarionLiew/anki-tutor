#!/bin/bash
# launchd entry point: opens the Anki GUI so AnkiConnect serves on 127.0.0.1:8765.
# LaunchAgent context gives us the user's Aqua session, so the Qt GUI renders.
# launchd owns the process exclusively (KeepAlive respawns it if it dies) —
# do NOT add an "already running, exit 0" guard here or KeepAlive would spin.

export HOME="/Users/marionliew"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/marionliew/.local/bin:/Users/marionliew/miniconda3/bin"

ANKI_VENV="/Users/marionliew/Library/Application Support/AnkiProgramFiles/.venv/bin"

cd "/Users/marionliew/Library/Application Support/AnkiProgramFiles"
exec "$ANKI_VENV/anki"