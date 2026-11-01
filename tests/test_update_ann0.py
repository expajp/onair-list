import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import update_ann0 as a

JST = a.JST
ROWS = [["#284", "2026-10-29", a.NODA, "秦基博", "Rain", "X"]]
# 2026-11-05 の放送の次の火曜。
NOW =dt.datetime(2026, 11, 10, 12, 0, tzinfo=JST)


def times_row(selector, time):
    return ["#1", "2026-01-01", selector, "a", "b", time]


def post(selector, hour, minute, text="x"):
    return {"selector": selector, "text": text, "time": dt.datetime(2026, 11, 6, hour, minute, tzinfo=JST)}


def fetched(hour, minute):
    return {"text": "x", "time": dt.datetime(2026, 11, 6, hour, minute, tzinfo=JST)}


def extracted(artist, title, first_post, certain=True):
    return {"artist": artist, "title": title, "first_post": first_post, "certain": certain}


class WindowTest(unittest.TestCase):
    def test_uses_default_until_enough_samples(self):
        windows = a.slot_windows([times_row(a.NODA, "03:30")])
        self.assertEqual(windows[a.NODA], a.DEFAULT_WINDOWS[a.NODA])

    def test_uses_observed_range_with_margin(self):
        times = [times_row(a.NODA, t) for t in ["03:30", "03:31", "03:33", "03:36", "03:41"]]
        self.assertEqual(a.slot_windows(times)[a.NODA], (205, 226))

    def test_only_recent_samples_count(self):
        old = [times_row(a.NODA, "03:00")]
        recent = [times_row(a.NODA, "03:30")] * a.RECENT_SAMPLES
        self.assertEqual(a.slot_windows(old + recent)[a.NODA], (205, 215))


class LatestAirDateTest(unittest.TestCase):
    def test_broadcast_counts_after_friday_morning(self):
        before = dt.datetime(2026, 11, 6, 5, 0, tzinfo=JST)
        after = dt.datetime(2026, 11, 6, 5, 10, tzinfo=JST)
        self.assertEqual(a.latest_air_date(before), dt.date(2026, 10, 29))
        self.assertEqual(a.latest_air_date(after), dt.date(2026, 11, 5))

    def test_tuesday_run(self):
        self.assertEqual(a.latest_air_date(NOW), dt.date(2026, 11, 5))


class DecideSongsTest(unittest.TestCase):
    posts = [post(a.NODA, 3, 33), post(a.MURAKAMI, 4, 24)]

    def test_selector_follows_time_slot(self):
        songs, reasons = a.decide_songs(self.posts, [extracted("A", "x", 0), extracted("B", "y", 1)])
        self.assertEqual([s["selector"] for s in songs], [a.NODA, a.MURAKAMI])
        self.assertEqual(reasons, [])

    def test_noda_comes_first_whatever_the_extraction_order(self):
        songs, _ = a.decide_songs(self.posts, [extracted("B", "y", 1), extracted("A", "x", 0)])
        self.assertEqual([s["selector"] for s in songs], [a.NODA, a.MURAKAMI])

    def test_noda_only_needs_no_review(self):
        self.assertEqual(a.decide_songs(self.posts, [extracted("A", "x", 0)])[1], [])

    def test_missing_noda_needs_review(self):
        self.assertTrue(a.decide_songs(self.posts, [extracted("B", "y", 1)])[1])

    def test_no_song_needs_review(self):
        self.assertEqual(a.decide_songs(self.posts, []), ([], ["曲を特定できませんでした"]))

    def test_uncertain_song_needs_review(self):
        self.assertTrue(a.decide_songs(self.posts, [extracted("A", "x", 0, certain=False)])[1])

    def test_two_songs_in_one_slot_need_review(self):
        self.assertTrue(a.decide_songs(self.posts, [extracted("A", "x", 0), extracted("B", "y", 0)])[1])

    def test_out_of_range_post_is_rejected(self):
        songs, reasons = a.decide_songs(self.posts, [extracted("A", "x", 9)])
        self.assertEqual(songs, [])
        self.assertEqual(len(reasons), 2)

    def test_overlong_field_is_rejected(self):
        songs, _ = a.decide_songs(self.posts, [extracted("A", "x" * 200, 0)])
        self.assertEqual(songs, [])


class BuildUpdateTest(unittest.TestCase):
    times = [times_row(a.NODA, "03:30")]

    def run_update(self, posts, extract, rows=ROWS):
        return a.build_update(rows, self.times, NOW, lambda start, end: posts, extract)

    def test_adds_next_episode_and_records_time(self):
        rows, times, summary = self.run_update([fetched(3, 36)] * 6, lambda posts: [extracted("A", "x", 0)])
        self.assertEqual(rows[-1], ["#285", "2026-11-05", a.NODA, "A", "x", a.SOURCE])
        self.assertEqual(times[-1][5], "03:36")
        self.assertEqual(summary["reasons"], [])

    def test_too_few_posts_means_no_broadcast(self):
        rows, times, summary = self.run_update([], lambda posts: self.fail("抽出しない"))
        self.assertEqual(rows, ROWS)
        self.assertIsNone(summary["added"])

    def test_no_song_adds_blank_row(self):
        rows, times, summary = self.run_update([fetched(3, 36)] * 6, lambda posts: [])
        self.assertEqual(rows[-1], ["#285", "2026-11-05", "", "", "", a.NO_SONG_NOTE])
        self.assertEqual(times, self.times)
        self.assertTrue(summary["reasons"])

    def test_already_recorded_episode_is_skipped(self):
        current = [["#285", "2026-11-05", a.NODA, "A", "x", "X"]]
        rows, _, summary = a.build_update(current, self.times, NOW, lambda s, e: self.fail("取得しない"), None)
        self.assertEqual(rows, current)
        self.assertIsNone(summary["added"])

    def test_gap_asks_to_check_number(self):
        old = [["#283", "2026-10-22", a.NODA, "A", "x", "X"]]
        _, _, summary = self.run_update([fetched(3, 36)] * 6, lambda posts: [extracted("A", "x", 0)], old)
        self.assertTrue(any("回番号" in reason for reason in summary["reasons"]))


class WindowFetchTest(unittest.TestCase):
    def test_requests_only_slot_windows_on_friday_morning(self):
        calls = []
        a.collect_posts(dt.date(2026, 11, 5), {a.NODA: (205, 226)}, lambda s, e: calls.append((s, e)) or [])
        self.assertEqual(calls[0][0], dt.datetime(2026, 11, 6, 3, 25, tzinfo=JST))
        self.assertEqual(calls[0][1], dt.datetime(2026, 11, 6, 3, 46, tzinfo=JST))


if __name__ == "__main__":
    unittest.main()
