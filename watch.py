#!/usr/bin/env python3
"""Watch NYRR volunteer pages for 9+1-eligible openings and alert via Telegram.

NYRR has no waitlist: cancelled spots silently reappear on the event page and are
taken first-come. Observed in the wild: a "near capacity" 9+1 slot went to "all
spots filled" in under an hour. So we poll often and alert the moment a slot
flips to available.
"""
import html
import json
import os
import re
import sys
import urllib.request

BASE = "https://events.nyrr.org/"
STATE_FILE = os.environ.get("NYRR_STATE", "state.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"

# slug -> (display name, date label). Nov 1 events are omitted: Pat is running
# the marathon that day and NYRR forbids running and volunteering the same event.
EVENTS = [
    ("new-balance-bronx-10m-volunteers", "Bronx 10M", "Sat Sep 19"),
    ("tcs-new-york-city-training-series-18m-volunteers", "Training Series 18M", "Sun Sep 20"),
    ("vcp-cross-country-1-volunteers", "Cross Country #1", "Sun Sep 27"),
    ("vcp-cross-country-2-volunteers", "Cross Country #2", "Sun Oct 4"),
    ("nyrr-jersey-city-5k-volunteers", "Jersey City 5K", "Sun Oct 4"),
    ("nyrr-staten-island-half-volunteers", "Staten Island Half", "Sun Oct 11"),
    ("rising-nyrr-fall-jamboree-volunteers", "Rising NYRR Fall Jamboree", "Sat Oct 17"),
    ("pre-marathon-support-volunteers", "Pre-Marathon Support", "Oct 17-31"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers-queens", "Kids Kickoff (Queens)", "Sat Oct 24"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers-brooklyn", "Kids Kickoff (Brooklyn)", "Sat Oct 24"),
    ("tcs-new-york-city-marathon-kids-kickoff-bronx-volunteers", "Kids Kickoff (Bronx)", "Sat Oct 24"),
    ("tcs-new-york-city-marathon-kids-kickoff-staten-island-volunteers", "Kids Kickoff (Staten Island)", "Sat Oct 24"),
    ("tcs-new-york-city-marathon-kids-kickoff-volunteers", "Kids Kickoff (Central Park)", "Sun Oct 25"),
    ("tcs-new-york-city-marathon-pre-race-bag-check-volunteers", "Marathon Pre-Race Bag Check", "Fri Oct 30"),
    ("2026-tcs-new-york-city-marathon-volunteers-marathon-opening-ceremony", "Marathon Opening Ceremony", "Fri Oct 30"),
    ("abbott-dash-to-the-finish-line-5k-volunteers", "Abbott Dash to the Finish 5K", "Sat Oct 31"),
    ("post-marathon-week-volunteers", "Post-Marathon Week", "Mon Nov 2"),
    ("vcp-cross-country-3-volunteers", "Cross Country #3", "Sun Nov 15"),
    ("race-to-deliver-4m-to-benefit-god-s-love-we-deliver-volunteers", "Race to Deliver 4M", "Sun Nov 22"),
    ("nyrr-ted-corbitt-15k-volunteers", "Ted Corbitt 15K", "Sat Dec 5"),
    ("nyrr-frosty-5k-volunteers", "Frosty 5K", "Sat Dec 12"),
    ("nyrr-midnight-run-volunteers", "Midnight Run", "Thu Dec 31"),
]

OPEN = {"AVL": "AVAILABLE", "NEA": "NEAR CAPACITY"}  # MED = medical (needs NYS license), SOL = filled

ASSIGNMENT_RE = re.compile(r'data-filterable-status="([A-Z]+)"(.*?)</li>', re.S)
NAME_RE = re.compile(r'class="category-name[^"]*">(.*?)</div>', re.S)
TAG_RE = re.compile(r'class="[^"]*tag-box[^"]*"[^>]*>\s*(.*?)\s*</span>', re.S)


def fetch(slug):
    req = urllib.request.Request(BASE + slug, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(page):
    """Yield (status_code, role_name, tags) for every assignment on the page."""
    for m in ASSIGNMENT_RE.finditer(page):
        status, block = m.group(1), m.group(2)
        name = NAME_RE.search(block)
        if not name:
            continue
        tags = [html.unescape(t.strip()).lower() for t in TAG_RE.findall(block)]
        yield status, html.unescape(re.sub(r"\s+", " ", name.group(1)).strip()), tags


def eligible(status, tags):
    """9+1 credit, open to a non-medical volunteer, and actually bookable."""
    return status in OPEN and "9+1" in tags and "medical" not in tags


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

    found, errors = {}, []
    for slug, name, date in EVENTS:
        try:
            page = fetch(slug)
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue
        for status, role, tags in parse(page):
            if eligible(status, tags):
                found[(slug, role)] = (name, date, OPEN[status])

    for (slug, role), (name, date, status) in sorted(found.items()):
        print(f"OPEN  {name} ({date}) — {role} [{status}]")
    if errors:
        print("ERRORS:", "; ".join(errors), file=sys.stderr)

    new = {k: v for k, v in found.items() if k not in seen}
    if new:
        lines = ["🏃 <b>NYRR 9+1 SLOT OPEN</b>", ""]
        for (slug, role), (name, date, status) in sorted(new.items()):
            lines += [
                f"<b>{html.escape(name)}</b> — {date}",
                f"{html.escape(role)} · {status}",
                f"{BASE}{slug}",
                "",
            ]
        lines.append("No waitlist, first-come. Grab it now.")
        telegram("\n".join(lines))
        print(f"ALERTED on {len(new)} new opening(s)")
    else:
        print(f"no new openings ({len(found)} currently open, {len(seen)} already known)")

    json.dump([list(k) for k in found], open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
