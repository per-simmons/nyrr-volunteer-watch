#!/usr/bin/env python3
"""Ask the REGISTRATION system the truth about every assignment, all 20 events.

The listing page (events.nyrr.org) advertises seats registration has already
closed -- proven 2026-09-16 when Bag Check read NEAR CAPACITY while registration
said the event was closed. Only register.nyrr.org is authoritative.

Every event page exposes <input id="event_key" value="..."> even when fully
booked, so the registration URL is recoverable for all 20 events.

IMPORTANT: this attaches to the shared browser and must NOT close it. Exiting a
`with sync_playwright()` block closes the CDP-connected browser -- that is what
repeatedly destroyed Pat's session. We start the driver manually and os._exit()
so no cleanup runs.
"""
import os, re, sys, json
import watch
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
out = []
try:
    b = pw.chromium.connect_over_cdp("http://localhost:9222")
    ctx = b.contexts[0]
    pg = ctx.new_page()
    for slug, name, date, iso in watch.EVENTS:
        if iso < watch.AVAILABLE_FROM:
            continue
        try:
            html = watch.fetch(slug)
        except Exception as e:
            print(f"{name:<30} listing fetch failed: {str(e)[:40]}"); continue
        key = re.search(r'id="event_key"[^>]*value="([0-9a-f]{20})"', html)
        listing = {r: s for s, r, t, l in watch.parse(html)
                   if any("9+1" in x for x in t) and not any("medical" in x for x in t)}
        if not key:
            print(f"{name:<30} NO event_key in page"); continue
        try:
            pg.goto("https://register.nyrr.org/?event=" + key.group(1),
                    wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3000)
            body = pg.inner_text("body")
        except Exception as e:
            print(f"{name:<30} reg load failed: {str(e)[:50]}"); continue

        if "registration for this event is closed" in body.lower() \
           or "maximum number of participants" in body.lower():
            verdict = "EVENT CLOSED"
            openr = []
        else:
            openr = []
            for c in pg.query_selector_all('input[name="event_option_key"]'):
                lab = pg.evaluate(
                    "e=>{const w=e.closest('li,div,label');return w?w.innerText.replace(/\\s+/g,' '):''}", c) or ""
                if "full" not in lab.lower() and "no +1" not in lab.lower() \
                   and "medical" not in lab.lower() and "leader" not in lab.lower():
                    openr.append(lab[:48].strip())
            verdict = "OPEN: " + "; ".join(openr) if openr else "all 9+1 full"
        listing_open = [r for r, s in listing.items() if s in watch.OPEN]
        flag = ""
        if openr and not listing_open:
            flag = "   <<< REGISTRATION HAS A SEAT THE LISTING HIDES"
        if listing_open and not openr:
            flag = "   <<< listing phantom"
        print(f"{name:<30} {date:<11} {verdict}{flag}")
        out.append({"event": name, "key": key.group(1), "reg_open": openr,
                    "listing_open": listing_open})
    json.dump(out, open("audit.json", "w"), indent=1)
    print("\nwrote audit.json")
finally:
    sys.stdout.flush()
    os._exit(0)          # skip playwright cleanup so the browser survives
