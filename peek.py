#!/usr/bin/env python3
"""Read registration pages via the shared browser WITHOUT closing it.

Never use `with sync_playwright()` here: exiting that block closes the
CDP-connected browser and destroys the login. Start the driver manually, then
os._exit() so no cleanup runs.
"""
import os, sys
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
try:
    b = pw.chromium.connect_over_cdp("http://localhost:9222")
    pg = b.contexts[0].new_page()
    for ev in sys.argv[1:]:
        pg.goto("https://register.nyrr.org/?event=" + ev,
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(3000)
        txt = pg.inner_text("body")
        head = " | ".join(x.strip() for x in txt.split("\n") if x.strip())[:230]
        print(f"\n=== {ev} ===\n{head}")
        rows = []
        for c in pg.query_selector_all('input[name="event_option_key"]'):
            lab = pg.evaluate("e=>{const w=e.closest('li,div,label');return w?w.innerText.replace(/\\s+/g,' '):''}", c) or ""
            rows.append(("FULL" if "full" in lab.lower() else "OPEN") + " | " + lab[:58].strip())
        for r in rows:
            print("   ", r)
finally:
    sys.stdout.flush()
    os._exit(0)
