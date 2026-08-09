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
| Breakfast | `https://cambridgeheightspfc.github.io/meal-calendar-sync/breakfast.ics` |
| Lunch | `https://cambridgeheightspfc.github.io/meal-calendar-sync/lunch.ics` |
| Snack | `https://cambridgeheightspfc.github.io/meal-calendar-sync/snack.ics` |

`https://cambridgeheightspfc.github.io/meal-calendar-sync/` is a landing page with
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

### Custom domain

A subdomain of a PFC domain is the link worth sharing, and it keeps working if
this ever moves off GitHub Pages:

1. Add a DNS `CNAME` record for the subdomain you want, pointing at
   `cambridgeheightspfc.github.io.` (with the trailing dot). Use a subdomain
   rather than the apex — a `CNAME` on `meals.` cannot disturb whatever serves
   the main PFC site, and apex domains need four `A` records instead.
2. Put that hostname, alone on one line, in `docs/CNAME`.
3. **Settings → Pages → Custom domain**, enter it, and wait for the DNS check.
4. Tick **Enforce HTTPS** once the certificate finishes provisioning. Do not
   skip this: several calendar clients refuse plain-HTTP subscriptions outright,
   and others will fetch it but warn.

`docs/index.html` needs no edit — it builds its subscribe links from whatever
address it is served at, so the custom domain propagates on its own. The feed
generator never deletes files it did not write, so `docs/CNAME` survives every
scheduled rebuild.

Verify with `curl -sI https://<domain>/lunch.ics`, checking for
`content-type: text/calendar`. Anything else — `text/plain` especially — and
some clients will refuse to subscribe.

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

## If the repository moves again

The splitter itself has no notion of who owns this repository, so a transfer or
rename needs no code change. What does depend on the owner:

- `docs/index.html` rewrites its own links from the address it is served at, so
  the landing page follows a move on its own. The URLs written into the markup
  are the fallback for browsers with JavaScript disabled — worth correcting, but
  not urgent.
- This README's table, and the `User-Agent` the fetch sends, are plain strings.
- Anyone already subscribed keeps hitting the old URL. GitHub redirects a
  transferred repository's Pages site for a while, but not forever, so re-share
  the new links.

Move the repository **before** enabling Pages and handing the links out, and none
of that last point applies. Also note that Pages on a free organization plan
requires the repository to be public, and organizations can restrict Actions
permissions org-wide — check that the workflow can still write after a transfer.

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
