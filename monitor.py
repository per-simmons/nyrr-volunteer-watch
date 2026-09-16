#!/usr/bin/env python3
"""Emit one line per NEWLY-opened 9+1 slot, forever.

Written for the Monitor tool: each stdout line becomes a notification in
Claude's session, so Claude itself is woken the moment a seat appears and can
drive the already-logged-in browser to register. Telegram alerting stays with
the LaunchAgent; this stream exists purely to wake Claude.

Only NEW openings print. A slot that stays open does not re-emit, or every poll
would spam the session and get the monitor rate-limited.
"""
import sys, time, datetime, watch

POLL = 60
seen = set()
fails = 0

def say(msg):
    print(msg, flush=True)

while True:
    found, errors = {}, 0
    for slug, name, date, iso in watch.EVENTS:
        if iso < watch.AVAILABLE_FROM:
            continue
        try:
            page = watch.fetch(slug)
        except Exception:
            errors += 1
            continue
        for status, role, tags, link in watch.parse(page):
            if watch.eligible(status, tags):
                found[(slug, role)] = (name, date, watch.OPEN[status], link)

    # Coverage: a silent monitor and a broken monitor look identical, so say so
    # when every fetch is failing rather than going quiet.
    fails = fails + 1 if errors and not found else 0
    if fails in (5, 30):
        say(f"WATCHER-DEGRADED: {errors} fetch failures, {fails} polls with no data")

    new = {k: v for k, v in found.items() if k not in seen}
    for (slug, role), (name, date, status, link) in sorted(new.items()):
        say(f"SLOT OPEN >> {name} ({date}) | {role} | {status} | "
            f"REGISTER: {link or 'https://events.nyrr.org/'+slug} | seen {datetime.datetime.now().strftime('%H:%M:%S')}")
    seen = set(found)
    time.sleep(POLL)
