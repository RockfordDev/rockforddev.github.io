#!/usr/bin/env python3
"""
update_events.py
Fetches RockfordDev events from the Eventbrite API, then renders
.github/templates/index.html.j2 → index.html using Jinja2.

Required environment variables:
  EVENTBRITE_TOKEN  – Private OAuth token from your Eventbrite account
  EVENTBRITE_ORG_ID – Numeric organization ID (see README for how to find it)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / ".github" / "templates"
TEMPLATE_NAME = "index.html.j2"
OUTPUT_FILE  = REPO_ROOT / "index.html"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TOKEN  = os.environ.get("EVENTBRITE_TOKEN", "")
ORG_ID = os.environ.get("EVENTBRITE_ORG_ID", "")

WEEKDAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
MONTHS   = ["January","February","March","April","May","June",
            "July","August","September","October","November","December"]

# Statuses that mean the event is in the future
FUTURE_STATUSES = {"live", "started", "draft"}
# Statuses to ignore entirely
SKIP_STATUSES   = {"canceled", "deleted"}


# ---------------------------------------------------------------------------
# Eventbrite API helpers
# ---------------------------------------------------------------------------
def api_get(path: str) -> dict:
    url = f"https://www.eventbriteapi.com/v3{path}"
    req = Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        sys.exit(f"Eventbrite API error {exc.code} for {url}:\n{body}")
    except URLError as exc:
        sys.exit(f"Network error fetching {url}: {exc.reason}")


def get_all_events() -> list:
    """Return every event for the org, handling pagination automatically."""
    events: list = []
    continuation: str | None = None

    while True:
        qs = "?order_by=start_desc&status=all&expand=venue"
        if continuation:
            qs += f"&continuation={continuation}"
        data = api_get(f"/organizations/{ORG_ID}/events/{qs}")
        events.extend(data.get("events", []))
        pagination = data.get("pagination", {})
        if pagination.get("has_more_items"):
            continuation = pagination.get("continuation")
        else:
            break

    return events


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------
def parse_local(local_str: str) -> datetime:
    return datetime.strptime(local_str, "%Y-%m-%dT%H:%M:%S")


def fmt_long(dt: datetime) -> str:
    """e.g. Wednesday, September 16 2026"""
    return f"{WEEKDAYS[dt.weekday()]}, {MONTHS[dt.month - 1]} {dt.day} {dt.year}"


def fmt_short(dt: datetime) -> str:
    """e.g. 2026-09-16"""
    return dt.strftime("%Y-%m-%d")


def fmt_time(dt: datetime) -> str:
    """e.g. 6:00 PM"""
    hour   = dt.hour % 12 or 12
    minute = dt.minute
    ampm   = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{minute:02d} {ampm}"


def venue_name(event: dict) -> str:
    """Return the venue name, falling back to the library address."""
    venue = event.get("venue") or {}
    return venue.get("name") or "Maker Lab @ Rockford Public Library"


# ---------------------------------------------------------------------------
# Build template context
# ---------------------------------------------------------------------------
def build_context(all_events: list) -> dict:
    now      = datetime.now()
    upcoming = []
    past     = []

    for ev in all_events:
        status = ev.get("status", "")
        if status in SKIP_STATUSES:
            continue
        start_dt = parse_local(ev["start"]["local"])
        if start_dt > now and status in FUTURE_STATUSES:
            upcoming.append(ev)
        elif start_dt <= now:
            past.append(ev)

    # Upcoming → soonest first; Past → most recent first
    upcoming.sort(key=lambda e: e["start"]["local"])
    past.sort(key=lambda e: e["start"]["local"], reverse=True)

    def shape(ev: dict, include_long: bool = False) -> dict:
        dt = parse_local(ev["start"]["local"])
        d  = {
            "title":      ev["name"]["text"],
            "url":        ev["url"],
            "date_short": fmt_short(dt),
        }
        if include_long:
            d["date_long"] = fmt_long(dt)
            d["time"]      = fmt_time(dt)
            d["venue"]     = venue_name(ev)
        return d

    next_event = shape(upcoming[0], include_long=True) if upcoming else None
    past_shaped = [shape(ev) for ev in past]

    return {
        "next_event":  next_event,
        "past_events": past_shaped,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not TOKEN:
        sys.exit("ERROR: EVENTBRITE_TOKEN environment variable is not set.")
    if not ORG_ID:
        sys.exit("ERROR: EVENTBRITE_ORG_ID environment variable is not set.")

    print("Fetching events from Eventbrite …")
    all_events = get_all_events()
    print(f"  → {len(all_events)} total events retrieved")

    context = build_context(all_events)
    next_ev = context["next_event"]
    print(f"  → Upcoming: {1 if next_ev else 0}, Past: {len(context['past_events'])}")
    if next_ev:
        print(f"  → Next event: {next_ev['title']}")
    else:
        print("  → No upcoming events.")

    # Render template → index.html
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        # Keep Jinja2 whitespace tidy: strip blocks trims blank lines left by
        # block tags, trim_blocks removes the newline after a block tag.
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_NAME)
    rendered = template.render(**context)

    OUTPUT_FILE.write_text(rendered, encoding="utf-8")
    print(f"✓ {OUTPUT_FILE} rendered successfully.")


if __name__ == "__main__":
    main()
