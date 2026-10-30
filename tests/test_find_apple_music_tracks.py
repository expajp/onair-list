import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import find_apple_music_tracks as f


def row(title, selector="村上", artist="長澤知之", song="JUNKLIFE"):
    return {"タイトル": title, "選曲者": selector, "アーティスト名": artist, "曲名": song}


class SelectSongsTest(unittest.TestCase):
    def test_special_episode_counts_as_zero(self):
        rows = [row("単発#2"), row("#1", song="広い海の真ん中で")]
        self.assertEqual([s[0] for s in f.select_songs(rows, 0, "すべて")], ["単発#2", "#1"])
        self.assertEqual([s[0] for s in f.select_songs(rows, 1, "すべて")], ["#1"])

    def test_episode_label_drops_subtitle(self):
        rows = [row("#206 月曜深夜にお引越し")]
        self.assertEqual(f.select_songs(rows, 206, "村上")[0][0], "#206")

    def test_skips_other_selector_and_blank_song(self):
        rows = [row("#1", selector="野田クリスタル"), row("#2", song="")]
        self.assertEqual(f.select_songs(rows, 0, "村上"), [])


if __name__ == "__main__":
    unittest.main()
