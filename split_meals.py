#!/usr/bin/env python3
"""Split a school meal calendar subscription into one feed per meal.

The San Juan USD nutrition-services feed publishes every meal for a site as a
separate all-day event whose SUMMARY is just the meal name ("K-8 Breakfast")
and whose DESCRIPTION holds the actual menu items followed by the district's
standard boilerplate. That is awkward to live with: a month view shows three
identical rows per day and you have to tap each one to find out what is
actually being served.

This script rewrites the feed into one .ics per meal, moving the menu items up
into the event title, so the month view reads:

    Breakfast: Cinn Maple Sausage / Fresh Baked Mini Loaf (fresh)

Only the standard library is used, so the script runs anywhere Python 3.9+ is
available with no install step.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, NamedTuple

DEFAULT_SOURCE = "https://www.sanjuan.edu/calendar/calendar_445.ics"

PRODID = "-//meal-calendar-sync//Split meal feeds//EN"

# Wall-clock time each meal is served, used to place the event in the day.
# See --timed; by default events stay all-day like the source feed.
DEFAULT_TIMES = {
    "breakfast": ("0730", "0800"),
    "lunch": ("1130", "1215"),
    "snack": ("1430", "1445"),
}


class Meal(NamedTuple):
    """One output feed: how to recognise its events and what to call it."""

    key: str  # slug, also the output filename stem
    label: str  # title prefix, e.g. "Breakfast"
    match: str  # case-insensitive substring matched against the source SUMMARY
    calname: str  # X-WR-CALNAME of the generated feed


MEALS = (
    Meal("breakfast", "Breakfast", "breakfast", "School Breakfast"),
    Meal("lunch", "Lunch", "lunch", "School Lunch"),
    Meal("snack", "Snack", "snack", "School Snack"),
)

# Lines in DESCRIPTION that are district boilerplate rather than menu items.
# Matched case-insensitively as substrings so small wording changes upstream
# do not start leaking legalese into event titles.
BOILERPLATE = (
    "available to all students at no cost",
    "menu subject to change",
    "equal opportunity provider",
    "soy milk available upon request",
    "all grains offered are whole grain",
)


# ---------------------------------------------------------------------------
# iCalendar parsing
# ---------------------------------------------------------------------------


def unfold(text: str) -> list[str]:
    """Undo RFC 5545 line folding and return the logical lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)
    return [line for line in text.split("\n") if line.strip()]


def unescape(value: str) -> str:
    """Decode an RFC 5545 TEXT value into plain text."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "N": "\n"}.get(nxt, nxt))
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def escape(value: str) -> str:
    """Encode plain text as an RFC 5545 TEXT value."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def parse_events(text: str) -> list[dict[str, str]]:
    """Return each VEVENT as a mapping of property name to raw value.

    Property parameters are kept on the key (``DTSTART;VALUE=DATE``) because
    the ones this script cares about are copied through verbatim.
    """
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue
        name, _, value = line.partition(":")
        current[name.upper()] = value
    return events


def prop(event: dict[str, str], name: str) -> tuple[str, str] | None:
    """Look up a property by name, ignoring any parameters on the key."""
    name = name.upper()
    for key, value in event.items():
        if key == name or key.startswith(name + ";"):
            return key, value
    return None


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------


def classify(summary: str) -> Meal | None:
    """Pick the output feed an event belongs to, or None if it fits nowhere."""
    lowered = summary.lower()
    for meal in MEALS:
        if meal.match in lowered:
            return meal
    return None


def menu_items(description: str) -> list[str]:
    """Pull the menu items out of a DESCRIPTION, dropping the boilerplate."""
    items: list[str] = []
    for line in unescape(description).split("\n"):
        line = " ".join(line.split())  # collapse the padding whitespace
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in BOILERPLATE):
            continue
        if line in items:  # the source occasionally repeats an item
            continue
        items.append(line)
    return items


def build_title(meal: Meal, items: Iterable[str], separator: str) -> str:
    items = list(items)
    if not items:
        return meal.label
    return f"{meal.label}: {separator.join(items)}"


def event_date(event: dict[str, str]) -> str | None:
    """Return the DTSTART date as YYYYMMDD, for date and date-time values."""
    found = prop(event, "DTSTART")
    if not found:
        return None
    value = found[1].strip()
    match = re.match(r"(\d{8})", value)
    return match.group(1) if match else None


def next_day(yyyymmdd: str) -> str:
    day = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=1)
    return day.strftime("%Y%m%d")


def fold(line: str) -> str:
    """Fold a content line to 75 octets, never splitting a UTF-8 character."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    chunks: list[bytes] = []
    limit = 75
    while encoded:
        if len(encoded) <= limit:
            chunks.append(encoded)
            break
        cut = limit
        while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1  # back off into the start of the character
        chunks.append(encoded[:cut])
        encoded = encoded[cut:]
        limit = 74  # continuation lines carry a leading space
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def render_calendar(
    meal: Meal,
    events: list[dict[str, str]],
    *,
    separator: str,
    timed: bool,
    refresh_hours: int,
) -> str:
    """Render one meal's events as a complete iCalendar document."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(meal.calname)}",
        f"NAME:{escape(meal.calname)}",
        f"REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_hours}H",
        f"X-PUBLISHED-TTL:PT{refresh_hours}H",
    ]

    for event in sorted(events, key=lambda e: (event_date(e) or "", e.get("UID", ""))):
        day = event_date(event)
        if day is None:
            continue
        description = event.get("DESCRIPTION", "")
        title = build_title(meal, menu_items(description), separator)

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{event.get('UID', f'{day}-{meal.key}@meal-calendar-sync')}")
        # DTSTAMP is derived from the event date rather than the current clock
        # so that regenerating an unchanged menu produces a byte-identical
        # file, and the scheduled job only commits when a menu really changed.
        lines.append(f"DTSTAMP:{day}T000000Z")
        if timed:
            start, end = DEFAULT_TIMES.get(meal.key, ("1200", "1230"))
            lines.append(f"DTSTART;VALUE=DATE-TIME:{day}T{start}00")
            lines.append(f"DTEND;VALUE=DATE-TIME:{day}T{end}00")
        else:
            lines.append(f"DTSTART;VALUE=DATE:{day}")
            lines.append(f"DTEND;VALUE=DATE:{next_day(day)}")
        lines.append(f"SUMMARY:{escape(title)}")
        if description:
            lines.append(f"DESCRIPTION:{description}")
        lines.append("TRANSP:TRANSPARENT")
        lines.append("SEQUENCE:0")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def split_feed(
    source_text: str,
    *,
    separator: str = " / ",
    timed: bool = False,
    refresh_hours: int = 24,
) -> tuple[dict[str, str], list[str]]:
    """Split a source feed into ``{filename: ics text}`` plus unmatched titles."""
    grouped: dict[str, list[dict[str, str]]] = {meal.key: [] for meal in MEALS}
    unmatched: list[str] = []

    for event in parse_events(source_text):
        summary = unescape(event.get("SUMMARY", "")).strip()
        meal = classify(summary)
        if meal is None:
            if summary and summary not in unmatched:
                unmatched.append(summary)
            continue
        grouped[meal.key].append(event)

    feeds = {
        f"{meal.key}.ics": render_calendar(
            meal,
            grouped[meal.key],
            separator=separator,
            timed=timed,
            refresh_hours=refresh_hours,
        )
        for meal in MEALS
    }
    return feeds, unmatched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def fetch(url: str, *, timeout: int = 60, retries: int = 3, sleep=time.sleep) -> str:
    """Read the source feed, from a URL or a local path.

    School district sites go down often enough that a single transient failure
    should not turn into a red scheduled build, so network reads are retried
    with a short backoff.
    """
    if "://" not in url:  # allow a local file for testing
        return Path(url).read_text(encoding="utf-8")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "meal-calendar-sync (+https://github.com/cambridgeheightspfc/meal-calendar-sync)"
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - retry any transport failure
            if attempt == retries - 1:
                raise
            delay = 2 ** (attempt + 1)
            print(f"fetch failed ({exc}); retrying in {delay}s", file=sys.stderr)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE, help="source .ics URL or local path"
    )
    parser.add_argument(
        "--out",
        default="docs",
        type=Path,
        help="directory to write the generated feeds into (default: docs)",
    )
    parser.add_argument(
        "--separator",
        default=" / ",
        help="text placed between menu items in the title (default: ' / ')",
    )
    parser.add_argument(
        "--timed",
        action="store_true",
        help="emit timed events at typical serving times instead of all-day events",
    )
    parser.add_argument(
        "--refresh-hours",
        type=int,
        default=24,
        help="refresh interval advertised to calendar clients (default: 24)",
    )
    args = parser.parse_args(argv)

    try:
        source_text = fetch(args.source)
    except Exception as exc:  # noqa: BLE001 - surface any fetch failure plainly
        print(f"error: could not fetch {args.source}: {exc}", file=sys.stderr)
        return 1

    if "BEGIN:VCALENDAR" not in source_text:
        print(f"error: {args.source} did not return an iCalendar feed", file=sys.stderr)
        return 1

    feeds, unmatched = split_feed(
        source_text,
        separator=args.separator,
        timed=args.timed,
        refresh_hours=args.refresh_hours,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    for filename, text in feeds.items():
        path = args.out / filename
        path.write_text(text, encoding="utf-8", newline="")
        count = text.count("BEGIN:VEVENT")
        print(f"wrote {path} ({count} events)")

    if unmatched:
        print(
            "note: ignored events with unrecognised titles: "
            + ", ".join(sorted(unmatched)),
            file=sys.stderr,
        )

    if all(text.count("BEGIN:VEVENT") == 0 for text in feeds.values()):
        print("error: no meal events matched; refusing to publish empty feeds",
              file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
