# NYRR 9+1 volunteer watch

Polls every NYRR volunteer event page for the rest of 2026 and pings Telegram the
moment a **9+1-eligible, non-medical** assignment opens up.

## Why this exists

NYRR has no waitlist. Cancelled spots just reappear on the event page and go
first-come. A "near capacity" 9+1 slot at the Midnight Run went to "all spots
filled" in under an hour on 2026-09-11 — which is why this polls every 10 minutes
rather than daily.

## What it alerts on

An assignment qualifies when all three hold:

- `data-filterable-status` is `AVL` (available) or `NEA` (near capacity)
- tags include `9+1`
- tags do **not** include `medical` (those need a NYS license)

`SOL` (filled) and `MED` (medical) are ignored, as are `No +1` roles.

Nov 1 marathon-day events are deliberately left out of `EVENTS`: Pat is running
the marathon, and NYRR does not let you run and volunteer at the same event.

## Run it locally

    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 watch.py

Prints every currently-open slot; alerts only on ones not already in `state.json`.

## Verifying an alert after the fact

Every alert appends a record to `alerts-evidence.jsonl` containing the UTC
timestamp and the **raw markup NYRR served at that moment**, so a later "was that
slot really open?" is answerable from the record rather than from trust.

The parser reads `data-filterable-status`, the same field that renders the
visible badge on the page — verified 1:1 against a browser rendering of
nyrr-staten-island-half-volunteers on 2026-09-15 (all 9 roles matched).

Note there is no third-party archive: the Wayback Machine has no snapshots of
these event pages, so alerts fired before this log existed cannot be re-checked.
