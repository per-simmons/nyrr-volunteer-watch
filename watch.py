#!/usr/bin/env python3
"""Watch NYRR volunteer pages for 9+1-eligible openings and alert via Telegram.

NYRR has no waitlist: cancelled spots silently reappear on the event page and are
taken first-come. Observed in the wild: a "near capacity" 9+1 slot went to "all
spots filled" in under an hour. So we poll often and alert the moment a slot
flips to available.
"""
import datetime
import html
import json
import os
import re
import sys
import time
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
        if with_raw:
            yield status, role, tags, re.sub(r"\s+", " ", m.group(0))[:600]
        else:
            yield status, role, tags


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
        for status, role, tags, block in parse(page, with_raw=True):
            if eligible(status, tags):
                found[(slug, role)] = (name, date, OPEN[status])
                raw[(slug, role)] = block

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
        # Append-only evidence log: the exact markup NYRR served at alert time,
        # so any later "was that real?" can be answered from the record.
        with open(EVIDENCE, "a") as fh:
            for k, v in sorted(new.items()):
                fh.write(json.dumps({
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "slug": k[0], "role": k[1], "status": v[2], "html": raw.get(k, ""),
                }) + "\n")
        telegram("\n".join(lines))
        print(f"ALERTED on {len(new)} new opening(s)")
    else:
        print(f"no new openings ({len(found)} currently open, {len(seen)} already known)")

    json.dump([list(k) for k in found], open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
