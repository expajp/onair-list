import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import sort_playlist_tracks as s

SONGS = [("#1", "長澤知之", "JUNKLIFE"), ("#2", "the pillows", "I Think I Can"), ("#3", "tricot", "おとずれ")]


class OrderTracksTest(unittest.TestCase):
    def test_sorts_by_broadcast_order(self):
        tracks = [("おとずれ", "tricot"), ("JUNKLIFE", "長澤知之"), ("I Think I Can", "the pillows")]
        self.assertEqual([row[0] for row in s.order_tracks(SONGS, tracks)], [2, 3, 1])

    def test_unmatched_track_goes_last(self):
        tracks = [("知らない曲", "知らない人"), ("JUNKLIFE", "長澤知之")]
        self.assertEqual(s.order_tracks(SONGS, tracks)[-1], (1, "", "知らない曲", "知らない人"))

    def test_first_song_is_not_treated_as_unmatched(self):
        tracks = [("おとずれ", "tricot"), ("JUNKLIFE", "長澤 知之")]
        self.assertEqual(s.order_tracks(SONGS, tracks)[0][1], "#1")

    def test_catalog_spelling_matches(self):
        self.assertEqual(s.find_song(SONGS, "I Think I Can (Remastered)", "THE PILLOWS"), 1)

    def test_title_alone_matches_when_artist_differs(self):
        self.assertEqual(s.find_song(SONGS, "おとずれ", "トリコ"), 2)

    def test_same_title_uses_artist(self):
        songs = [("#1", "A", "Rain"), ("#2", "B", "Rain")]
        self.assertEqual(s.find_song(songs, "Rain", "B"), 1)


if __name__ == "__main__":
    unittest.main()
