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
| Breakfast | `https://meals.chpfc.space/breakfast.ics` |
| Lunch | `https://meals.chpfc.space/lunch.ics` |
| Snack | `https://meals.chpfc.space/snack.ics` |

`https://meals.chpfc.space/` is a landing page with one-tap subscribe buttons —
that is the link to share with families.

Subscribe to these URLs, don't import them — importing copies the events once
and they never update. Note that Google Calendar refreshes external feeds on its
own schedule, frequently only every 8–24 hours; Apple Calendar lets you pick.

## Setup

Do these in order. Transferring after the links are out means re-sharing them,
and DNS before Pages means the certificate provisions on the first try.

1. **Transfer the repository to the `cambridgeheightspfc` organization** and make
   it public. Pages on a free organization plan requires a public repository.
2. **Merge this branch to `main`.**
3. **Settings → Pages → Source: Deploy from a branch**, branch `main`, folder
   `/docs`.
4. **Settings → Actions → General → Workflow permissions: Read and write**, so
   the scheduled job can commit regenerated feeds. This is a repository setting
   an organization can override, so confirm it *after* the transfer.
5. **Add the DNS record** (below), then **Settings → Pages → Custom domain** →
   `meals.chpfc.space`.
6. **Actions → Update meal feeds → Run workflow** to confirm the daily job works
   without waiting for the schedule.

### Custom domain

`docs/CNAME` already pins the site to `meals.chpfc.space`. What remains is one
DNS record, at whoever hosts DNS for `chpfc.space`:

| Type | Name | Value |
| --- | --- | --- |
| `CNAME` | `meals` | `cambridgeheightspfc.github.io.` |

A subdomain rather than the apex, deliberately: a `CNAME` on `meals.` cannot
disturb whatever might later serve the main PFC site, and apex domains need four
`A` records instead. If you would rather serve this at `chpfc.space` itself, that
is a one-line change to `docs/CNAME` plus the apex records GitHub documents.

Then tick **Enforce HTTPS** once the certificate finishes provisioning. Do not
skip it: several calendar clients refuse plain-HTTP subscriptions outright, and
others fetch it but warn.

`docs/index.html` needs no edit — it builds its subscribe links from whatever
address it is served at, so the domain propagates on its own. The feed generator
never deletes files it did not write, so `docs/CNAME` survives every rebuild.

Two things to check once it is live:

```bash
curl -sI https://meals.chpfc.space/lunch.ics | grep -i 'content-type\|^HTTP'
```

Expect `200` and `content-type: text/calendar`. Anything else — `text/plain`
especially — and some clients refuse to subscribe.

Second, send the link to yourself through whatever the PFC uses for family
email before announcing it. Newer TLDs like `.space` carry a worse reputation
with spam filters than `.org` does, and school-district mail filters are often
strict. If it gets flagged, linking to the landing page from an existing PFC
page and sharing *that* avoids putting the bare domain in an email.

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

Because the published URL is `meals.chpfc.space` rather than a `github.io`
address, subscribers do not care who owns the repository or where it is hosted.
A transfer, a rename, or a move to another static host only needs:

- **The DNS record** repointed, if the owner changed — GitHub matches the `CNAME`
  target against the account serving the site.
- **`docs/CNAME`** left alone, unless the domain itself changes.
- **The `User-Agent`** in `split_meals.py`, which names the repository as a
  courtesy to the district's server. Cosmetic.

`docs/index.html` needs nothing: it derives its subscribe links from wherever it
is being served. The hardcoded URLs in the markup are only the fallback for
browsers with JavaScript disabled.

That is the point of the custom domain — the link you hand to families is the
one thing that never has to change again.

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
