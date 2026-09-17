#!/bin/bash
# Keeps the stack alive without ever killing the browser.
#
# The browser holds a session that cannot be recreated without Pat signing in,
# so this NEVER touches browser-host unless it is already dead. The bot and the
# cookie keeper are disposable and get restarted freely.
cd "$(dirname "$0")" || exit 1
PY=/opt/homebrew/opt/python@3.14/bin/python3.14

while true; do
  # 1) browser: only start it if CDP is actually unreachable
  if ! curl -s --max-time 5 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    if ! pgrep -f "browser-host.py" >/dev/null; then
      echo "$(date '+%F %T') browser-host down -> starting (cookies will restore the session)"
      nohup "$PY" -u browser-host.py >> /tmp/nyrr-host.log 2>&1 &
      sleep 20
    fi
  fi
  # 2) cookie keeper
  if ! pgrep -f "cookie-keeper.py" >/dev/null; then
    echo "$(date '+%F %T') cookie-keeper down -> starting"
    nohup "$PY" -u cookie-keeper.py >> /tmp/nyrr-cookies.log 2>&1 &
  fi
  # 3) the bot, unless it already won
  if [ -f .registered ]; then
    echo "$(date '+%F %T') seat already secured; watchdog exiting"
    exit 0
  fi
  if ! pgrep -f "autoreg.py" >/dev/null; then
    echo "$(date '+%F %T') autoreg down -> starting"
    nohup ./run-autoreg.sh >> /tmp/nyrr-autoreg.log 2>&1 &
  fi
  sleep 60
done
