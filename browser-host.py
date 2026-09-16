#!/usr/bin/env python3
"""Hold the signed-in browser in its OWN process, exposed over CDP.

NYRR's auth cookies are session-only, so they die with the browser process.
While the bot launched its own browser, every code fix forced a restart and
destroyed Pat's login -- six times. Now the browser lives here and autoreg
attaches to it; restarting the bot no longer costs a login.

Start this once, sign in once, leave it running.
"""
import json
import pathlib
from playwright.sync_api import sync_playwright

PROFILE = str(pathlib.Path(__file__).parent / "pw-profile")
PORT = 9222

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport=None,
        args=[f"--remote-debugging-port={PORT}", "--window-size=1280,950"],
    )
    # Restore the cookies Chrome refuses to persist. If the server-side session
    # is still alive, this brings the login straight back with no re-sign-in.
    jar = pathlib.Path(__file__).parent / "cookies.json"
    if jar.exists():
        try:
            ctx.add_cookies(json.loads(jar.read_text()))
            print(f"restored {len(json.loads(jar.read_text()))} saved nyrr cookies", flush=True)
        except Exception as e:
            print("cookie restore failed:", str(e)[:140], flush=True)

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://www.nyrr.org/account", wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print("(nav warning)", e, flush=True)
    print(f"BROWSER HOST UP on CDP {PORT}. Sign in here and LEAVE THIS WINDOW OPEN.", flush=True)
    while True:
        page.wait_for_timeout(60000)
