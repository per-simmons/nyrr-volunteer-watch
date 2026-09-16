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


def notify(text):
    """Tell Pat what happened; he is not watching the log."""
    try:
        import watch as _w
        _w.telegram(text)
    except Exception as e:
        log(f"(telegram failed: {e})")


def register(page, url, option, accept_waiver):
    log(f"OPEN {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # The assignment radios are rendered late; 2.5s was too short and produced a
    # false "radio-missing" on a live seat. Wait for the control itself.
    try:
        page.wait_for_selector(f'input[name="event_option_key"][value="{option}"]',
                               timeout=25000, state="attached")
    except Exception:
        body = page.inner_text("body")[:300].replace("\n", " | ")
        if "log in" in body.lower() or "sign in" in body.lower():
            return "needs-human:logged-out"
        log(f"no radio after wait; page says: {body[:200]}")
        return "radio-missing"

    radio = page.query_selector(f'input[name="event_option_key"][value="{option}"]')
    if not radio:
        return "radio-missing"
    if radio.get_attribute("disabled") is not None:
        return "assignment-full"
    radio.check(timeout=8000)
    log("assignment selected")
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
        log(f"clicking '{btn[1]}'")
        btn[0].click()
        page.wait_for_timeout(5000)

        errs = [e.inner_text().strip() for e in page.query_selector_all("[class*=error]")
                if e.is_visible() and e.inner_text().strip()]
        if errs:
            log("VALIDATION: " + " | ".join(errs[:4])[:200])
            return "needs-human:validation"

        body = page.inner_text("body").lower()
        if any(k in body for k in ("you're registered", "you are registered",
                                   "registration complete", "thank you for registering",
                                   "confirmation number")):
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
        ctx = p.chromium.launch_persistent_context(PROFILE, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if a.once:
            log("RESULT " + register(page, a.once, a.option, a.accept_waiver))
            return

        if DONE.exists():
            log("already registered (" + DONE.read_text().strip() + ") -- nothing to do")
            return
        log(f"watching {len([e for e in watch.EVENTS if e[3] >= watch.AVAILABLE_FROM])} events, "
            f"every {a.poll}s, accept_waiver={a.accept_waiver}")
        tried = set()
        while True:
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
                    if not watch.confirm_open(link):
                        log(f"phantom (registration closed): {name} / {role}")
                        continue
                    log(f"*** SEAT: {name} ({date}) {role} [{watch.OPEN[status]}]")
                    res = register(page, link, opt.group(1), a.accept_waiver)
                    log(f"RESULT {name} / {role} -> {res}")
                    # Only stop retrying on a definitive answer. A transient
                    # failure must not blacklist a seat that is still live.
                    if res in ("REGISTERED", "assignment-full") or res.startswith("needs-human"):
                        tried.add(key)
                    if res == "REGISTERED":
                        DONE.write_text(f"{name} | {role} | {date} | {datetime.datetime.now()}\n")
                        notify(f"\u2705 <b>NYRR 9+1 SECURED</b>\n\n{name} \u2014 {date}\n{role}\n\n"
                               f"Registered automatically. Check Your Events on nyrr.org to confirm.")
                        log("DONE. Stopping.")
                        return
                    if res.startswith("needs-human"):
                        notify(f"\u26a0\ufe0f <b>NYRR seat needs you</b>\n\n{name} \u2014 {date}\n{role}\n"
                               f"Bot stopped: {res}\n{link}")
            time.sleep(a.poll)


if __name__ == "__main__":
    main()
