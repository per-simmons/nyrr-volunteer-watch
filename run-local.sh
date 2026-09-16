#!/bin/bash
# Local poller. Reads Telegram creds from the campaign repo's .env so no secret
# is duplicated here. State lives beside the script so alerts dedupe.
cd "$(dirname "$0")" || exit 1
P=/Users/patsimmons/coding/clearhaven-instantly-campaign_1.19.26
# listing-based alerts cannot tell a phantom from a real seat; autoreg notifies instead
# export TELEGRAM_BOT_TOKEN=$(grep -rhoE '^TELEGRAM_BOT_TOKEN=.*' "$P"/.env* "$P"/clearhaven-os/.env* 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
# export TELEGRAM_CHAT_ID=$(grep -rhoE '^TELEGRAM_CHAT_ID=.*' "$P"/.env* "$P"/clearhaven-os/.env* 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
export NYRR_STATE="$HOME/.nyrr-watch-state.json"
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec /usr/bin/python3 watch.py
