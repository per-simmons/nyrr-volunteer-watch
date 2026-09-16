#!/bin/bash
# Auto-register daemon. Telegram creds are read from the campaign repo's .env so
# nothing secret lives in this repo.
cd "$(dirname "$0")" || exit 1
P=/Users/patsimmons/coding/clearhaven-instantly-campaign_1.19.26
export TELEGRAM_BOT_TOKEN=$(grep -rhoE '^TELEGRAM_BOT_TOKEN=.*' "$P"/.env* "$P"/clearhaven-os/.env* 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
export TELEGRAM_CHAT_ID=$(grep -rhoE '^TELEGRAM_CHAT_ID=.*' "$P"/.env* "$P"/clearhaven-os/.env* 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
export NYRR_STATE="$HOME/.nyrr-autoreg-state.json"
exec /opt/homebrew/opt/python@3.14/bin/python3.14 -u autoreg.py --accept-waiver --poll 60
