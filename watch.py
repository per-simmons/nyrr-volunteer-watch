#!/usr/bin/env python3
"""Watch NYRR volunteer pages for 9+1-eligible openings and alert via Telegram.

NYRR has no waitlist: cancelled spots silently reappear on the event page and are
taken first-come. Observed in the wild: a "near capacity" 9+1 slot went to "all
spots filled" in under an hour. So we poll often and alert the moment a slot
flips to available.
"""
import datetime
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://events.nyrr.org/"
STATE_FILE = os.environ.get("NYRR_STATE", "state.json")
EVIDENCE = os.environ.get("NYRR_EVIDENCE", "alerts-evidence.jsonl")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"

# slug -> (display name, date label, ISO date). Nov 1 events are omitted: Pat is
# running the marathon that day and NYRR forbids running and volunteering the
# same event. Events before AVAILABLE_FROM are skipped entirely -- alerting on a
# shift he cannot attend just trains him to ignore the alerts.
EVENTS = [
    ("new-balance-bronx-10m-volunteers", "Bronx 10M", "Sat Sep 19", "2026-09-19"),
    ("tcs-new-york-city-training-series-18m-volunteers", "Training Series 18M", "Sun Sep 20", "2026-09-20"),
    ("vcp-cross-country-1-volunteers", "Cross Country #1", "Sun Sep 27", "2026-09-27"),
    ("vcp-cross-country-2-volunteers", "Cross Country #2", "Sun Oct 4", "2026-10-04"),
    ("nyrr-jersey-city-5k-volunteers", "Jersey City 5K", "Sun Oct 4", "2026-10-04"),
    ("nyrr-staten-island-half-volunteers", "Staten Island Half", "Sun Oct 11", "2026-10-11"),
    ("rising-nyrr-fall-jamboree-volunteers", "Rising NYRR Fall Jamboree", "Sat Oct 17", "2026-10-17"),
    ("pre-marathon-support-volunteers", "Pre-Marathon Support", "Oct 17-31", "2026-10-17"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers-queens", "Kids Kickoff (Queens)", "Sat Oct 24", "2026-10-24"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers-brooklyn", "Kids Kickoff (Brooklyn)", "Sat Oct 24", "2026-10-24"),
    ("tcs-new-york-city-marathon-kids-kickoff-bronx-volunteers", "Kids Kickoff (Bronx)", "Sat Oct 24", "2026-10-24"),
    ("tcs-new-york-city-marathon-kids-kickoff-staten-island-volunteers", "Kids Kickoff (Staten Island)", "Sat Oct 24", "2026-10-24"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers", "Kids Kickoff (Central Park)", "Sun Oct 25", "2026-10-25"),
    ("tcs-new-york-city-marathon-pre-race-bag-check-volunteers", "Marathon Pre-Race Bag Check", "Fri Oct 30", "2026-10-30"),
    ("2026-tcs-new-york-city-marathon-volunteers-marathon-opening-ceremony", "Marathon Opening Ceremony", "Fri Oct 30", "2026-10-30"),
    ("abbott-dash-to-the-finish-line-5k-volunteers", "Abbott Dash to the Finish 5K", "Sat Oct 31", "2026-10-31"),
    ("post-marathon-week-volunteers", "Post-Marathon Week", "Mon Nov 2", "2026-11-02"),
    ("vcp-cross-country-3-volunteers", "Cross Country #3", "Sun Nov 15", "2026-11-15"),
    ("race-to-deliver-4m-to-benefit-god-s-love-we-deliver-volunteers", "Race to Deliver 4M", "Sun Nov 22", "2026-11-22"),
    ("nyrr-ted-corbitt-15k-volunteers", "Ted Corbitt 15K", "Sat Dec 5", "2026-12-05"),
    ("nyrr-frosty-5k-volunteers", "Frosty 5K", "Sat Dec 12", "2026-12-12"),
    ("nyrr-midnight-run-volunteers", "Midnight Run", "Thu Dec 31", "2026-12-31"),
]

# Pat is out of state until ~Sep 25, 2026. Raise this if travel shifts.
AVAILABLE_FROM = os.environ.get("NYRR_FROM", "2026-09-26")

OPEN = {"AVL": "AVAILABLE", "NEA": "NEAR CAPACITY"}  # MED = medical (needs NYS license), SOL = filled

ASSIGNMENT_RE = re.compile(r'data-filterable-status="([A-Z]+)"(.*?)</li>', re.S)
NAME_RE = re.compile(r'class="category-name[^"]*">(.*?)</div>', re.S)
TAG_RE = re.compile(r'class="[^"]*tag-box[^"]*"[^>]*>\s*(.*?)\s*</span>', re.S)
# Each role carries its own direct registration URL. Linking straight to it
# skips the event page, which is pure latency when the seat lives ~3 minutes.
REG_RE = re.compile(r'href="(https://register\.nyrr\.org/[^"]+)"')


def fetch(slug, attempts=3):
    """Fetch one event page, retrying transient 502/504s and read timeouts.

    A page that errors is a silent blind spot: its assignments drop out of the
    result, so an opening there would go unseen. Retrying costs nothing at this
    poll rate and closes that gap.
    """
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(BASE + slug, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise last


def parse(page, with_raw=False):
    """Yield (status_code, role_name, tags[, raw_html]) for each assignment."""
    for m in ASSIGNMENT_RE.finditer(page):
        status, block = m.group(1), m.group(2)
        name = NAME_RE.search(block)
        if not name:
            continue
        tags = [html.unescape(t.strip()).lower() for t in TAG_RE.findall(block)]
        role = html.unescape(re.sub(r"\s+", " ", name.group(1)).strip())
        reg = REG_RE.search(block)
        link = html.unescape(reg.group(1)) if reg else None
        if with_raw:
            yield status, role, tags, re.sub(r"\s+", " ", m.group(0))[:600], link
        else:
            yield status, role, tags, link


CLOSED_MSG = re.compile(r"registration for this event is closed|maximum number of participants", re.I)


def confirm_open(link, attempts=2):
    """Ask the REGISTRATION system whether a seat is really bookable.

    The event listing's status goes stale: on 2026-09-16 it advertised
    Post-Marathon Week / Central Park Green Team as NEA with a live Register
    link while registration had already closed. Alerting off the listing alone
    sends Pat chasing seats that never existed.

    Both open and closed events bounce through NYRR's Queue-it waiting room, so
    the redirect itself proves nothing -- and without a cookie jar the hop loops
    forever. Carry cookies, land on the real page, then read it.
    """
    if not link:
        return True
    for i in range(attempts):
        try:
            jar = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            op.addheaders = [("User-Agent", UA)]
            with op.open(link, timeout=30) as r:
                body = r.read(400000).decode("utf-8", "replace")
            return not CLOSED_MSG.search(body)
        except Exception:
            if i == attempts - 1:
                return True          # never silently drop a possibly-real seat
            time.sleep(1)
    return True


def eligible(status, tags):
    """9+1 credit, open to a non-medical volunteer, and actually bookable.

    Tags are matched as substrings, not exact strings: NYRR labels some roles
    "9+1" and others "9+1 credit", and an exact match silently skipped the
    latter. "No +1" does not contain "9+1", so it is still correctly excluded.
    """
    if status not in OPEN:
        return False
    if any("medical" in t for t in tags):
        return False
    return any("9+1" in t for t in tags)


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("!! Telegram creds missing; alert not sent", file=sys.stderr)
        return
    body = json.dumps({
        "chat_id": chat, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("telegram:", r.status)


def main():
    try:
        seen = set(map(tuple, json.load(open(STATE_FILE))))
    except Exception:
        seen = set()

    found, errors, raw = {}, [], {}
    for slug, name, date, iso in EVENTS:
        if iso < AVAILABLE_FROM:
            continue
        try:
            page = fetch(slug)
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue
        for status, role, tags, block, link in parse(page, with_raw=True):
            if eligible(status, tags):
                found[(slug, role)] = (name, date, OPEN[status], link)
                raw[(slug, role)] = block

    for (slug, role), (name, date, status, link) in sorted(found.items()):
        print(f"OPEN  {name} ({date}) — {role} [{status}]")
    if errors:
        print("ERRORS:", "; ".join(errors), file=sys.stderr)

    new = {k: v for k, v in found.items() if k not in seen}
    # The listing lies. Confirm against the registration system before waking
    # Pat, or he chases seats that were never bookable.
    if new:
        confirmed = {}
        for k, v in new.items():
            if confirm_open(v[3]):
                confirmed[k] = v
            else:
                print(f"PHANTOM (listing says open, registration closed): {v[0]} / {k[1]}")
                found.pop(k, None)
        new = confirmed
    if new:
        lines = ["🏃 <b>NYRR 9+1 SLOT OPEN</b>", ""]
        for (slug, role), (name, date, status, link) in sorted(new.items()):
            lines += [
                f"<b>{html.escape(name)}</b> — {date}",
                f"{html.escape(role)} · {status}",
                f"<b>REGISTER: {html.escape(link or BASE + slug)}</b>",
                "",
            ]
        lines.append("No waitlist, first-come. Grab it now.")
        # Append-only evidence log: the exact markup NYRR served at alert time,
        # so any later "was that real?" can be answered from the record.
        with open(EVIDENCE, "a") as fh:
            for k, v in sorted(new.items()):
                fh.write(json.dumps({
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "slug": k[0], "role": k[1], "status": v[2],
                    "register_url": v[3], "html": raw.get(k, ""),
                }) + "\n")
        telegram("\n".join(lines))
        print(f"ALERTED on {len(new)} new opening(s)")
    else:
        print(f"no new openings ({len(found)} currently open, {len(seen)} already known)")

    json.dump([list(k) for k in found], open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
