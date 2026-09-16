#!/usr/bin/env python3
"""Open a real browser on a DEDICATED, persistent profile for a one-time login.

Pat signs into NYRR by hand in this window. The session is written to
./pw-profile on disk, so the auto-register bot reuses it later with no password
anywhere in code and none ever seen by Claude. Leave the window open or close
it -- the profile persists either way.
"""
import pathlib
from playwright.sync_api import sync_playwright

PROFILE = str(pathlib.Path(__file__).parent / "pw-profile")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport=None,
        args=["--window-size=1280,950"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://www.nyrr.org/account", wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print("(nav warning)", e)
    print(f"PROFILE={PROFILE}")
    print(">>> Log into NYRR in the window that opened, then tell Claude 'logged in'.")
    try:
        page.wait_for_timeout(1000 * 60 * 60)   # hold the window open an hour
    except Exception:
        pass
