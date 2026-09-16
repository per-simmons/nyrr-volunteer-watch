#!/usr/bin/env python3
"""Watch for a 9+1 seat and register for it automatically.

Seats come from cancellations, are a single spot, and the winner is whoever
finishes checkout first -- one was measured alive for ~3 minutes. So detection
and checkout have to happen without a human in the loop.

Uses the signed-in Playwright profile in ./pw-profile. No credentials live here:
Pat logged in by hand once and the session persists on disk.

Safety rules, in order:
  * only assignments tagged 9+1, never 'medical', never 'No +1'
  * never an event before AVAILABLE_FROM, never a Nov 1 marathon-day event
  * ticks agreement checkboxes ONLY if --accept-waiver was passed
  * never ticks a checkbox asserting a qualification (e.g. "I confirm I am a
    Volunteer Leader"), which would be a false statement
  * stops and reports rather than guessing at anything unrecognised
"""
import argparse, datetime, json, pathlib, re, sys, time
import watch
from playwright.sync_api import sync_playwright

PROFILE = str(pathlib.Path(__file__).parent / "pw-profile")
LOG = pathlib.Path(__file__).parent / "autoreg.log"
# Once a seat is secured the job is done -- +1 is a single requirement. This
# sentinel stops a KeepAlive relaunch from grabbing a second shift someone else
# needs.
DONE = pathlib.Path(__file__).parent / ".registered"

# Never tick these: they assert a qualification Pat may not hold.
FALSE_CLAIM = re.compile(r"i (confirm|certify|am)\b.*\b(leader|licensed|medical|physician|nurse|emt|guardian)", re.I)
# Safe to tick only with --accept-waiver: ordinary participation agreements.
WAIVER = re.compile(r"waiver|terms|agree|release|liability|policy|consent|acknowledg", re.I)


def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


KEEPALIVE_EVERY = 240          # seconds; ASP.NET idle timeouts are typically 20 min


def session_alive(page):
    """Is this browser still signed into NYRR? Advisory only -- never blocking.

    Checks manage.nyrr.org, where the signed-in dashboard lives. www.nyrr.org
    is a different host and its /account page does not reliably reflect the
    login, which made an actually-signed-in browser read as logged out.

    Pass the DEDICATED checker tab, never the tab Pat is using -- navigating his
    tab mid-login throws him out of the login flow.
    """
    try:
        page.goto("https://manage.nyrr.org/communities/8415523",
                  wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3500)
        txt = page.inner_text("body").lower()
        return any(k in txt for k in ("patrick", "simmons", "your events",
                                      "membership status", "sign out", "log out"))
    except Exception as e:
        log(f"keepalive error: {str(e)[:100]}")
        return True          # a network blip is not proof of logout


def notify(text):
    """Tell Pat what happened; he is not watching the log."""
    try:
        import watch as _w
        _w.telegram(text)
    except Exception as e:
        log(f"(telegram failed: {e})")


FORENSICS = pathlib.Path(__file__).parent / "forensics"


def snapshot(page, tag):
    """Save what NYRR actually served, so a miss can be audited, not argued."""
    try:
        FORENSICS.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        (FORENSICS / f"{ts}-{tag}.html").write_text(page.content()[:800000])
    except Exception:
        pass


def register(page, url, option, accept_waiver, role_name=None):
    t0 = time.time()
    log(f"OPEN {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    log(f"  [t+{time.time()-t0:.1f}s] page loaded")
    # The assignment radios are rendered late; 2.5s was too short and produced a
    # false "radio-missing" on a live seat. Wait for the control itself.
    try:
        page.wait_for_selector('input[name="event_option_key"]', timeout=8000, state="attached")
    except Exception:
        pass

    body_l = page.inner_text("body")[:2000].lower()
    log(f"  [t+{time.time()-t0:.1f}s] body read")
    if "registration for this event is closed" in body_l or "maximum number of participants" in body_l:
        return "closed-per-registration"
    if "session_expired" in page.url or "session expired" in body_l:
        return "needs-human:logged-out"

    radio = page.query_selector(f'input[name="event_option_key"][value="{option}"]')
    if not radio and role_name:
        for cand in page.query_selector_all('input[name="event_option_key"]'):
            lab = page.evaluate(
                "e=>{const w=e.closest('li,div,label');return w?w.innerText.slice(0,160):''}", cand) or ""
            if role_name.lower()[:24] in lab.lower():
                if "full" in lab.lower():
                    return "assignment-full"
                radio = cand
                log(f"matched assignment by name instead of option id: {role_name!r}")
                break
    if not radio:
        # Report what the REGISTRATION system says about every assignment --
        # this is the authoritative view, unlike the listing page.
        rows = []
        for c in page.query_selector_all('input[name="event_option_key"]'):
            lab = page.evaluate(
                "e=>{const w=e.closest('li,div,label');return w?w.innerText.replace(/\\s+/g,' ').slice(0,80):''}", c) or ""
            rows.append(f"{(c.get_attribute('value') or '')[:10]}={lab[:60]!r}")
        log(f"  [t+{time.time()-t0:.1f}s] RADIO-MISSING want={option[:10]} "
            f"n_radios={len(rows)}")
        for r in rows:
            log(f"      {r}")
        snapshot(page, "radio-missing")
        return "radio-missing"
    if radio.get_attribute("disabled") is not None:
        return "assignment-full"
    radio.check(timeout=8000)
    log(f"  [t+{time.time()-t0:.1f}s] ASSIGNMENT SELECTED")
    page.wait_for_timeout(1200)

    for _ in range(4):                      # walk the wizard
        for cb in page.query_selector_all("input[type=checkbox]"):
            if not cb.is_visible() or cb.is_checked():
                continue
            label = page.evaluate(
                "e=>{const w=e.closest('div,label');return w?w.innerText.slice(0,200):''}", cb) or ""
            if FALSE_CLAIM.search(label):
                log(f"REFUSING checkbox (asserts a qualification): {label[:70]!r}")
                return "needs-human:qualification-claim"
            if WAIVER.search(label):
                if not accept_waiver:
                    return "needs-human:waiver"
                cb.check(timeout=4000)
                log(f"accepted agreement: {label[:60]!r}")

        btn = None
        for text in ("Next Step", "Continue", "Complete Registration", "Submit", "Confirm"):
            el = page.query_selector(f"button:has-text('{text}')")
            if el and el.is_visible():
                btn = (el, text); break
        if not btn:
            break
        log(f"  [t+{time.time()-t0:.1f}s] clicking '{btn[1]}'")
        btn[0].click()
        page.wait_for_timeout(5000)

        errs = [e.inner_text().strip() for e in page.query_selector_all("[class*=error]")
                if e.is_visible() and e.inner_text().strip()]
        if errs:
            log(f"  [t+{time.time()-t0:.1f}s] VALIDATION: " + " | ".join(errs[:4])[:200])
            snapshot(page, "validation")
            return "needs-human:validation"

        body = page.inner_text("body").lower()
        if any(k in body for k in ("you're registered", "you are registered",
                                   "registration complete", "thank you for registering",
                                   "confirmation number")):
            log(f"  [t+{time.time()-t0:.1f}s] CONFIRMED REGISTERED")
            snapshot(page, "registered")
            return "REGISTERED"
    return "needs-human:unknown-step"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept-waiver", action="store_true",
                    help="tick ordinary participation/waiver agreements on Pat's behalf")
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--once", metavar="URL", help="register this URL now and exit")
    ap.add_argument("--option", help="event_option_key for --once")
    a = ap.parse_args()

    with sync_playwright() as p:
        # Attach to the long-lived browser-host process instead of launching a
        # browser here, so restarting this bot never destroys Pat's session.
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.nyrr.org/account",
                      wait_until="domcontentloaded", timeout=40000)
            page.bring_to_front()
        except Exception:
            pass
        checker = ctx.new_page()      # separate tab: never disturbs Pat's tab

        if a.once:
            log("RESULT " + register(page, a.once, a.option, a.accept_waiver))
            return

        if DONE.exists():
            log("already registered (" + DONE.read_text().strip() + ") -- nothing to do")
            return
        log(f"watching {len([e for e in watch.EVENTS if e[3] >= watch.AVAILABLE_FROM])} events, "
            f"every {a.poll}s, accept_waiver={a.accept_waiver}")
        # Wait for a human login in THIS window rather than dying. The window
        # stays up for the life of the daemon; that is what keeps auth alive.
        if session_alive(checker):
            log("session OK at startup")
        else:
            log("session looks logged out -- watching anyway")
            try:
                page.goto("https://www.nyrr.org/account",
                          wait_until="domcontentloaded", timeout=40000)
            except Exception:
                pass
            notify("\U0001f510 <b>NYRR: sign in needed</b>\n\nA 'Chrome for Testing' window is "
                   "open on your Mac. Sign into NYRR in it and leave it open. The bot keeps "
                   "watching either way.")
        tried = set()
        last_ka = time.time()
        warned_out = False
        while True:
            if time.time() - last_ka > KEEPALIVE_EVERY:
                last_ka = time.time()
                ok = session_alive(checker)
                if ok:
                    warned_out = False
                elif not warned_out:
                    warned_out = True
                    log("SESSION LOST")
                    notify("\u26a0\ufe0f <b>NYRR session logged out</b>\n\nAuto-register cannot "
                           "book a seat until you sign in again.\nRun ./relogin.sh then ./resume.sh")
            for slug, name, date, iso in watch.EVENTS:
                if iso < watch.AVAILABLE_FROM:
                    continue
                try:
                    html_page = watch.fetch(slug)
                except Exception:
                    continue
                for status, role, tags, link in watch.parse(html_page):
                    if not watch.eligible(status, tags) or not link:
                        continue
                    key = (slug, role)
                    if key in tried:
                        continue
                    opt = re.search(r"option=([0-9a-f]+)", link)
                    if not opt:
                        continue
                    log(f"*** SEAT: {name} ({date}) {role} [{watch.OPEN[status]}] "
                        f"listing_seen={datetime.datetime.now().strftime('%H:%M:%S')}")
                    res = register(checker, link, opt.group(1), a.accept_waiver, role)
                    log(f"RESULT {name} / {role} -> {res}")
                    # Only stop retrying on a definitive answer. A transient
                    # failure must not blacklist a seat that is still live.
                    if res in ("REGISTERED", "assignment-full", "closed-per-registration") \
                            or res.startswith("needs-human"):
                        tried.add(key)
                    if res == "REGISTERED":
                        DONE.write_text(f"{name} | {role} | {date} | {datetime.datetime.now()}\n")
                        notify(f"\u2705 <b>NYRR 9+1 SECURED</b>\n\n{name} \u2014 {date}\n{role}\n\n"
                               f"Registered automatically. Check Your Events on nyrr.org to confirm.")
                        log("DONE. Stopping.")
                        return
                    if res == "closed-per-registration":
                        log("listing was stale; registration already closed")
                    if res.startswith("needs-human"):
                        notify(f"\u26a0\ufe0f <b>NYRR seat needs you</b>\n\n{name} \u2014 {date}\n{role}\n"
                               f"Bot stopped: {res}\n{link}")
            time.sleep(a.poll)


if __name__ == "__main__":
    main()
