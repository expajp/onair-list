import datetime as dt
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import update_onair as u

JST = u.JST
ARTISTS = {u.key(a) for a in ["JAGATARA", "GLAY", "松田聖子", "スピッツ"]}


def post(text, hour_min, official=False):
    h, m = hour_min
    return {"text": text, "time": dt.datetime(2026, 11, 3, h, m, tzinfo=JST), "official": official}


OFFICIAL_FIRST = "「空気階段の踊り場」ＯＡ中！\n\n今週の１曲目は、、、\n\n♫普通の日々／エレファントカシマシ\n#odoriba954\n\nTBSラジオ 2026/10/12(月) 24:00-25:00 https://radiko.jp/share/?t=2026"
LIVE_FIRST = "今週の1曲目🎧\nエレファントカシマシ/普通の日々\n #odoriba954"
OFFICIAL_SECOND = "「空気階段の踊り場」ＯＡ中！\n\n今週のサイコゥSongは...\n\n♫半日消防署長／グループ魂\n#odoriba954"
LIVE_SECOND = "今週のサイコゥソング🎧\nグループ魂/半日消防署長\n #odoriba954"


class ParseTest(unittest.TestCase):
    def test_official_is_title_then_artist(self):
        p = u.parse_post(post(OFFICIAL_FIRST, (0, 39), official=True))
        self.assertEqual((p["label"], p["artist"], p["title"]), ("first", "エレファントカシマシ", "普通の日々"))

    def test_live_is_artist_then_title(self):
        p = u.parse_post(post(LIVE_SECOND, (0, 56)))
        self.assertEqual((p["label"], p["artist"], p["title"]), ("second_half", "グループ魂", "半日消防署長"))

    def test_same_line_format(self):
        p = u.parse_post(post("今週の1曲目 山下達郎／ さよなら夏の日\n#odoriba954", (0, 21)))
        self.assertEqual((p["artist"], p["title"]), ("山下達郎", "さよなら夏の日"))

    def test_song_continues_on_next_line(self):
        p = u.parse_post(post("今週の1曲目✨\nASIAN KUNG-FU GENERATION／\nソラニン\n#odoriba954", (0, 17)))
        self.assertEqual((p["artist"], p["title"]), ("ASIAN KUNG-FU GENERATION", "ソラニン"))

    def test_ampersand_and_fullwidth(self):
        p = u.parse_post(post("１曲目は...\n♫春夏秋冬／Steady&Co.", (0, 19), official=True))
        self.assertEqual((p["artist"], p["title"]), ("Steady&Co.", "春夏秋冬"))
        p = u.parse_post(post("１曲目は、、、\n♫Believe Your Smile／Ｖ６", (0, 34), official=True))
        self.assertEqual(p["artist"], "V6")

    def test_trailing_emoji_is_removed(self):
        p = u.parse_post(post("今週の1曲目🎧\n乃木坂46/おいでシャンプー🧴", (0, 27)))
        self.assertEqual(p["title"], "おいでシャンプー")

    def test_chat_is_ignored(self):
        self.assertIsNone(u.parse_post(post("1曲目から名曲すぎて✨\n #odoriba954", (0, 16))))
        self.assertIsNone(u.parse_post(post("サイコゥソングは？\nなし？", (0, 57))))
        self.assertIsNone(u.parse_post(post("座長はかたまり\n副座長はもぐら", (0, 42))))

    def test_recommended_song_is_excluded(self):
        self.assertIsNone(u.parse_post(post("TBSラジオ今月の推薦曲\n♫曲／誰か 1曲目", (0, 30))))


class DecideTest(unittest.TestCase):
    def selectors(self, posts):
        rows, reasons = u.decide_episode(posts, ARTISTS)
        return [(r["selector"], r["artist"], r["title"]) for r in rows], reasons

    def test_normal_episode_merges_both_accounts(self):
        rows, reasons = self.selectors(
            [
                post(OFFICIAL_FIRST, (0, 39), True),
                post(LIVE_FIRST, (0, 43)),
                post(OFFICIAL_SECOND, (0, 56), True),
                post(LIVE_SECOND, (0, 56)),
            ]
        )
        self.assertEqual(
            rows,
            [
                (u.MOGURA, "エレファントカシマシ", "普通の日々"),
                (u.KATAMARI, "グループ魂", "半日消防署長"),
            ],
        )
        self.assertEqual(reasons, [])

    def test_one_song_before_threshold_is_mogura(self):
        rows, reasons = self.selectors([post(LIVE_FIRST, (0, 39))])
        self.assertEqual(rows[0][0], u.MOGURA)
        self.assertEqual(reasons, [])

    def test_one_song_after_threshold_is_katamari_without_review(self):
        rows, reasons = self.selectors([post(LIVE_FIRST, (0, 40))])
        self.assertEqual(rows[0][0], u.KATAMARI)
        self.assertEqual(reasons, [])

    def test_second_half_only_is_katamari(self):
        rows, _ = self.selectors([post(LIVE_SECOND, (0, 54))])
        self.assertEqual(rows[0][0], u.KATAMARI)

    def test_second_song_means_listener_and_review(self):
        rows, reasons = self.selectors(
            [post("今週の1曲目🎧\nDA PUMP/Rhapsody", (0, 17)), post("今週の2曲目🎧\nDA PUMP/Rhapsody in Blue", (0, 24))]
        )
        self.assertEqual([r[0] for r in rows], [u.LISTENER, u.LISTENER])
        self.assertEqual(len(reasons), 1)

    def test_listener_request_text(self):
        rows, _ = self.selectors([post("リスナーリクエストの1曲目✨\nOKAMOTO'S/Beautiful Days", (0, 21))])
        self.assertEqual(rows[0][0], u.LISTENER)

    def test_conflict_needs_review(self):
        _, reasons = self.selectors([post(OFFICIAL_FIRST, (0, 39), True), post("今週の1曲目🎧\nGLAY/誘惑", (0, 40))])
        self.assertTrue(any("異なります" in r for r in reasons))

    def test_three_songs_need_review(self):
        _, reasons = self.selectors(
            [post("1曲目🎧\nA/B", (0, 10)), post("2曲目🎧\nC/D", (0, 20)), post(LIVE_SECOND, (0, 55))]
        )
        self.assertTrue(any("3曲" in r for r in reasons))

    def test_no_posts_is_silent(self):
        self.assertEqual(self.selectors([]), ([], []))

    def test_live_reversed_order_is_fixed_by_known_artist(self):
        rows, _ = self.selectors([post("今週の1曲目🎧\nもうがまんできない/JAGATARA", (0, 26))])
        self.assertEqual(rows[0][1:], ("JAGATARA", "もうがまんできない"))


class BuildTest(unittest.TestCase):
    rows = [["#496 既存", "2026-10-19", u.KATAMARI, "あいみょん", "マリーゴールド"], ["#497", "2026-10-26", u.MOGURA, "V6", "Believe Your Smile"]]
    now = dt.datetime(2026, 11, 3, 12, 0, tzinfo=JST)

    def test_window_and_latest(self):
        self.assertEqual(u.latest_aired(dt.datetime(2026, 11, 3, 1, 0, tzinfo=JST)), 497)
        self.assertEqual(u.latest_aired(self.now), 498)
        self.assertEqual(u.broadcast_window(498)[0].isoformat(), "2026-11-03T00:00:00+09:00")

    def test_no_posts_adds_blank_row_directly(self):
        rows = [["#" + str(n), u.air_date(n).isoformat(), "", "", ""] for n in range(206, 498)]
        updated, summary = u.build_update(rows, {}, self.now, lambda s, e: [])
        self.assertEqual(updated[-1], ["#498", "2026-11-02", "", "", ""])
        self.assertEqual(summary["reasons"], [])

    def test_title_update_keeps_songs(self):
        rows = [[f"#{n}", u.air_date(n).isoformat(), "", "", ""] for n in range(206, 499)]
        rows[-2:] = self.rows[1:] + [["#498", "2026-11-02", "", "", ""]]
        updated, summary = u.build_update(rows, {497: "#497 とにかく働く"}, self.now, lambda s, e: [])
        self.assertEqual(updated[-2], ["#497 とにかく働く", "2026-10-26", u.MOGURA, "V6", "Believe Your Smile"])
        self.assertEqual(summary["changed_titles"], 1)

    def test_too_old_episode_needs_review_and_skip_works(self):
        rows = [[f"#{n}", u.air_date(n).isoformat(), "", "", ""] for n in range(206, 497)]
        calls = []
        updated, summary = u.build_update(rows, {}, self.now, lambda s, e: calls.append(s) or [], skip={498})
        self.assertEqual(calls, [])
        self.assertEqual(summary["added"], [{"number": 497, "songs": []}])
        self.assertIn("7日間", summary["reasons"][0])

    def test_rss_reads_honpen_only(self):
        xml = """<rss><channel><item><title>#498【アフタートーク】違う</title></item>
        <item><title>#498【本編】新しい回</title></item><item><title>#494【未公開】違う</title></item></channel></rss>"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8") as f:
            f.write(xml)
            f.flush()
            self.assertEqual(u.honpen_titles(f.name), {498: "#498 新しい回"})


if __name__ == "__main__":
    unittest.main()
