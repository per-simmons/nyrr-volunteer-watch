#!/usr/bin/env python3
"""Snapshot the live browser's cookies to disk every 30s, session cookies included.

Chrome never persists session cookies (NYRR's ASP.NET_SessionId and the
auth.nyrr.org token are both session-only), so a browser restart has been
destroying Pat's login every single time. Chrome won't save them -- but
Playwright can read them out of the running browser, so we save them ourselves
and restore them on the next start.

Attaches over CDP, so it never disturbs the browser or the bot.
"""
import json, pathlib, time
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).parent / "cookies.json"

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://localhost:9222")
    ctx = b.contexts[0]
    last = 0
    while True:
        try:
            cookies = [c for c in ctx.cookies() if "nyrr" in c.get("domain", "")]
            if cookies:
                OUT.write_text(json.dumps(cookies, indent=1))
            # The actual login is tgSession in localStorage on manage.nyrr.org,
            # not a cookie. Capture it so a restart can restore the session.
            for pg in ctx.pages:
                if "manage.nyrr.org" in pg.url:
                    tg = pg.evaluate("()=>localStorage.getItem('tgSession')")
                    if tg:
                        (OUT.parent / "tgsession.json").write_text(json.dumps({"tgSession": tg}))
                    break
                if len(cookies) != last:
                    last = len(cookies)
                    names = sorted({c["name"] for c in cookies})
                    print(f"saved {len(cookies)} nyrr cookies: {names[:8]}", flush=True)
        except Exception as e:
            print("snapshot error:", str(e)[:120], flush=True)
        time.sleep(30)
