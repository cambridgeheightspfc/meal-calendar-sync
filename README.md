# meal-calendar-sync

Splits the San Juan Unified nutrition-services calendar subscription into one
feed per meal, with the menu promoted into the event title.

The district publishes every meal as a separate all-day event whose title is
just the meal name and whose menu is buried in the notes, after two paragraphs
of boilerplate:

```
SUMMARY:K-8 Lunch
DESCRIPTION:\nCountry Chicken Bowl (fresh)\n \nFalafel Wrap (fresh\, halal\, &
 vegan)\n \nOne breakfast is available to all students at no cost. All meals…
```

So a month view shows three identical rows per day and you have to tap each one
to find out what is actually being served. This turns that into:

```
SUMMARY:Lunch: Country Chicken Bowl (fresh) / Falafel Wrap (fresh, halal, & vegan)
```

split across three subscribable feeds — breakfast, lunch and snack — so you can
subscribe to only the meals you care about, or overlay all three. The original
notes are left on each event, so the full text is still there when you tap in.

## Subscribe

Once GitHub Pages is enabled (see below), the feeds live at:

| Meal | Subscription URL |
| --- | --- |
| Breakfast | `https://justinross.github.io/meal-calendar-sync/breakfast.ics` |
| Lunch | `https://justinross.github.io/meal-calendar-sync/lunch.ics` |
| Snack | `https://justinross.github.io/meal-calendar-sync/snack.ics` |

`https://justinross.github.io/meal-calendar-sync/` is a landing page with
one-tap subscribe buttons.

Subscribe to these URLs, don't import them — importing copies the events once
and they never update. Note that Google Calendar refreshes external feeds on its
own schedule, frequently only every 8–24 hours; Apple Calendar lets you pick.

## Setup

1. Merge this branch to `main`.
2. **Settings → Pages → Source: Deploy from a branch**, branch `main`, folder
   `/docs`.
3. **Settings → Actions → General → Workflow permissions: Read and write** so
   the scheduled job can commit regenerated feeds.
4. **Actions → Update meal feeds → Run workflow** to confirm it works without
   waiting for the schedule.

## How it refreshes

`.github/workflows/update-feeds.yml` runs once a day at 05:10 Pacific, plus on
demand. It runs the tests, regenerates `docs/*.ics`, and commits **only if a
menu actually changed** — which, given the district posts months at a time, will
be rare.

That last part is why event timestamps are derived from each event's date rather
than the current clock: the source feed's own `DTSTAMP` values change every time
the district regenerates their cache, which would otherwise produce a commit on
every single run whether or not anything about the menu was different.

If the district's site is down, the fetch retries three times with backoff before
failing the run. A failed run leaves the last good feeds in place.

## Running it yourself

Python 3.9+, no dependencies:

```bash
python split_meals.py                       # writes docs/{breakfast,lunch,snack}.ics
python split_meals.py --out /tmp/feeds      # somewhere else
python split_meals.py --source ./saved.ics  # from a local file
```

Options:

| Flag | Default | Effect |
| --- | --- | --- |
| `--source` | the district feed | Source `.ics` URL or local path |
| `--out` | `docs` | Output directory |
| `--separator` | `" / "` | Text between menu items in the title |
| `--timed` | off | Emit events at typical serving times instead of all-day |
| `--refresh-hours` | `24` | Refresh interval advertised to calendar clients |

Tests:

```bash
python -m unittest discover -s tests -t .
```

`tests/sample_feed.ics` is a five-event excerpt of the real feed, kept verbatim
so the parsing tests exercise the district's actual escaping and whitespace.

## Adapting it to another school or district

Every district calendar on `sanjuan.edu/calendar/` uses this same format, so
pointing `--source` at a different one is usually all it takes. Two constants in
`split_meals.py` control the rest:

- `MEALS` — the output feeds. Each entry pairs a case-insensitive substring
  matched against the source event title with the label used in the new title,
  so a site publishing "High School Lunch" already routes correctly.
- `BOILERPLATE` — substrings that mark a line in the notes as district
  boilerplate rather than a menu item. Matched case-insensitively, so small
  wording changes upstream don't start leaking legalese into event titles.

Events whose titles match no meal are skipped and listed on stderr rather than
dropped silently, so an unrecognised category shows up in the workflow log.
