#!/bin/bash
# The daemon owns the browser window -- logging in anywhere else cannot work,
# because NYRR's auth cookies are session-only and die with the process.
# This just restarts the daemon, which will prompt for sign-in in its own window.
launchctl unload ~/Library/LaunchAgents/ai.clearhaven.nyrr-autoreg.plist 2>/dev/null
pkill -9 -f autoreg.py 2>/dev/null; sleep 2
launchctl load ~/Library/LaunchAgents/ai.clearhaven.nyrr-autoreg.plist
echo "Daemon restarted. Sign into NYRR in the window it opens, then leave it open."
