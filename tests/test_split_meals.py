"""Tests for the meal feed splitter.

``tests/sample_feed.ics`` is a five-event excerpt of the real San Juan USD
feed, kept verbatim so the parsing tests exercise the district's actual
escaping and whitespace padding.
"""

import unittest
import unittest.mock
from pathlib import Path

import split_meals

SAMPLE = Path(__file__).with_name("sample_feed.ics").read_text(encoding="utf-8")


class ParsingTests(unittest.TestCase):
    def test_unfold_rejoins_continuation_lines(self):
        folded = "SUMMARY:a very long\r\n  title\r\nUID:1\r\n"
        self.assertEqual(split_meals.unfold(folded), ["SUMMARY:a very long title", "UID:1"])

    def test_unescape_decodes_text_values(self):
        self.assertEqual(
            split_meals.unescape(r"Falafel Wrap (fresh\, halal)\nnext"),
            "Falafel Wrap (fresh, halal)\nnext",
        )

    def test_escape_round_trips(self):
        original = "Beans; rice, corn\\slaw\nsecond line"
        self.assertEqual(split_meals.unescape(split_meals.escape(original)), original)

    def test_parse_events_finds_every_vevent(self):
        events = split_meals.parse_events(SAMPLE)
        self.assertEqual(len(events), 5)
        self.assertTrue(all("UID" in event for event in events))

    def test_prop_ignores_parameters_on_the_key(self):
        event = {"DTSTART;VALUE=DATE": "20260710"}
        self.assertEqual(split_meals.prop(event, "DTSTART"), ("DTSTART;VALUE=DATE", "20260710"))
        self.assertIsNone(split_meals.prop(event, "DTEND"))


class MenuExtractionTests(unittest.TestCase):
    def test_boilerplate_is_stripped_and_items_kept_in_order(self):
        description = (
            r"\nCountry Chicken Bowl (fresh)\n    \n \n    \n"
            r"Falafel Wrap (fresh\, halal\, & vegan)\n    \n \n    \n"
            r"One breakfast is available to all students at no cost. All meals are "
            r"served with fruit variety and 1% low-fat or non-fat chocolate milk "
            r"(soy milk available upon request). Students must choose at least one "
            r"fruit option. All grains offered are whole grain rich. Menu subject to "
            r"change based on product availability.\n    \n"
            r"This institution is an equal opportunity provider.\n"
        )
        self.assertEqual(
            split_meals.menu_items(description),
            ["Country Chicken Bowl (fresh)", "Falafel Wrap (fresh, halal, & vegan)"],
        )

    def test_repeated_items_are_collapsed(self):
        self.assertEqual(split_meals.menu_items(r"\nBagel\n \nBagel\n"), ["Bagel"])

    def test_empty_description_yields_no_items(self):
        self.assertEqual(split_meals.menu_items(""), [])

    def test_title_falls_back_to_the_bare_label(self):
        breakfast = split_meals.MEALS[0]
        self.assertEqual(split_meals.build_title(breakfast, [], " / "), "Breakfast")


class ClassificationTests(unittest.TestCase):
    def test_known_summaries_route_to_their_feed(self):
        for summary, expected in [
            ("K-8 Breakfast", "breakfast"),
            ("K-8 Lunch", "lunch"),
            ("Bridges Super Snack", "snack"),
            ("HIGH SCHOOL LUNCH", "lunch"),
        ]:
            with self.subTest(summary=summary):
                self.assertEqual(split_meals.classify(summary).key, expected)

    def test_unknown_summary_is_unclassified(self):
        self.assertIsNone(split_meals.classify("No School - Holiday"))


class SplitFeedTests(unittest.TestCase):
    def setUp(self):
        self.feeds, self.unmatched = split_meals.split_feed(SAMPLE)

    def test_one_feed_per_meal(self):
        self.assertEqual(
            sorted(self.feeds), ["breakfast.ics", "lunch.ics", "snack.ics"]
        )

    def test_events_are_routed_to_the_right_feed(self):
        self.assertEqual(self.feeds["breakfast.ics"].count("BEGIN:VEVENT"), 2)
        self.assertEqual(self.feeds["lunch.ics"].count("BEGIN:VEVENT"), 2)
        self.assertEqual(self.feeds["snack.ics"].count("BEGIN:VEVENT"), 1)

    def test_menu_is_promoted_into_the_title(self):
        self.assertIn(
            "SUMMARY:Lunch: Country Chicken Bowl (fresh) / Falafel Wrap (fresh\\, "
            "halal\\, & vegan)",
            split_meals.unfold(self.feeds["lunch.ics"]),
        )

    def test_boilerplate_never_reaches_a_title(self):
        for name, text in self.feeds.items():
            for line in split_meals.unfold(text):
                if line.startswith("SUMMARY:"):
                    with self.subTest(feed=name, line=line):
                        self.assertNotIn("equal opportunity", line.lower())

    def test_original_description_is_preserved(self):
        self.assertIn("equal opportunity provider", self.feeds["lunch.ics"])

    def test_all_day_events_get_an_explicit_end_date(self):
        lines = split_meals.unfold(self.feeds["breakfast.ics"])
        self.assertIn("DTSTART;VALUE=DATE:20260710", lines)
        self.assertIn("DTEND;VALUE=DATE:20260711", lines)

    def test_timed_mode_uses_the_serving_time(self):
        feeds, _ = split_meals.split_feed(SAMPLE, timed=True)
        lines = split_meals.unfold(feeds["breakfast.ics"])
        self.assertIn("DTSTART;VALUE=DATE-TIME:20260710T073000", lines)
        self.assertIn("DTEND;VALUE=DATE-TIME:20260710T080000", lines)

    def test_custom_separator_is_used(self):
        feeds, _ = split_meals.split_feed(SAMPLE, separator=" | ")
        self.assertIn("Country Chicken Bowl (fresh) | Falafel Wrap", feeds["lunch.ics"])

    def test_unrecognised_events_are_reported_not_dropped_silently(self):
        source = SAMPLE.replace("SUMMARY:K-8 Breakfast", "SUMMARY:No School", 1)
        _, unmatched = split_meals.split_feed(source)
        self.assertEqual(unmatched, ["No School"])

    def test_every_feed_is_a_well_formed_calendar(self):
        for name, text in self.feeds.items():
            with self.subTest(feed=name):
                self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
                self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
                self.assertEqual(
                    text.count("BEGIN:VEVENT"), text.count("END:VEVENT")
                )
                for line in text.split("\r\n")[:-1]:
                    self.assertLessEqual(len(line.encode("utf-8")), 75)
                    self.assertTrue(line, "blank content line")

    def test_uids_are_preserved_from_the_source(self):
        self.assertIn("UID:3370354@www.sanjuan.edu", self.feeds["lunch.ics"])

    def test_output_is_deterministic(self):
        again, _ = split_meals.split_feed(SAMPLE)
        self.assertEqual(self.feeds, again)


class FoldingTests(unittest.TestCase):
    def test_short_lines_are_untouched(self):
        self.assertEqual(split_meals.fold("UID:1"), "UID:1")

    def test_long_lines_are_folded_to_75_octets(self):
        folded = split_meals.fold("SUMMARY:" + "a" * 300)
        for segment in folded.split("\r\n"):
            self.assertLessEqual(len(segment.encode("utf-8")), 75)
        self.assertEqual(folded.replace("\r\n ", ""), "SUMMARY:" + "a" * 300)

    def test_multibyte_characters_are_not_split(self):
        folded = split_meals.fold("SUMMARY:" + "piñata café ☕ " * 12)
        for segment in folded.split("\r\n"):
            segment.encode("utf-8").decode("utf-8")  # raises if a char was cut
            self.assertLessEqual(len(segment.encode("utf-8")), 75)
        self.assertEqual(
            folded.replace("\r\n ", ""), "SUMMARY:" + "piñata café ☕ " * 12
        )


class FetchTests(unittest.TestCase):
    def test_local_paths_are_read_directly(self):
        path = Path(__file__).with_name("sample_feed.ics")
        self.assertIn("BEGIN:VCALENDAR", split_meals.fetch(str(path)))

    def test_transient_failures_are_retried(self):
        attempts = []
        slept = []

        def flaky(request, timeout=None):
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("connection reset")
            raise AssertionError("should not reach a third call in this test")

        with unittest.mock.patch.object(split_meals.urllib.request, "urlopen", flaky):
            with self.assertRaises(AssertionError):
                split_meals.fetch("https://example.test/f.ics", sleep=slept.append)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(slept, [2, 4])  # backoff between the first two failures

    def test_giving_up_raises_the_last_error(self):
        def always_fails(request, timeout=None):
            raise OSError("down for maintenance")

        with unittest.mock.patch.object(
            split_meals.urllib.request, "urlopen", always_fails
        ):
            with self.assertRaises(OSError):
                split_meals.fetch(
                    "https://example.test/f.ics", retries=2, sleep=lambda _: None
                )


class CliTests(unittest.TestCase):
    def test_writes_three_feeds_from_a_local_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            code = split_meals.main(
                ["--source", str(Path(__file__).with_name("sample_feed.ics")),
                 "--out", str(out)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                sorted(p.name for p in out.iterdir()),
                ["breakfast.ics", "lunch.ics", "snack.ics"],
            )

    def test_missing_source_is_an_error_not_a_traceback(self):
        code = split_meals.main(["--source", "/nonexistent/feed.ics", "--out", "/tmp/x"])
        self.assertEqual(code, 1)

    def test_non_calendar_response_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "junk.ics"
            junk.write_text("<html>404</html>", encoding="utf-8")
            self.assertEqual(
                split_meals.main(["--source", str(junk), "--out", str(Path(tmp) / "o")]),
                1,
            )

    def test_calendar_with_no_meals_does_not_publish_empty_feeds(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.ics"
            empty.write_text(
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n", encoding="utf-8"
            )
            self.assertEqual(
                split_meals.main(["--source", str(empty), "--out", str(Path(tmp) / "o")]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
