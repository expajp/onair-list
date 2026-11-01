#!/usr/bin/env python3
"""プレイリストの曲を放送順に並べ、タブ区切りで出力する。

入力は曲名とアーティスト名のタブ区切りファイルで、1行目がプレイリストの1曲目にあたる。
列は 曲の位置, 回, 曲名, アーティスト名 の順に並ぶ。一覧と照合できない曲は回を空にして最後に並べる。
"""
import argparse

from find_apple_music_tracks import CSV_URLS, THRESHOLD, load_songs, read_existing, score, select_songs


def find_song(songs, title, artist):
    """プレイリストの曲に最も近い一覧の曲の番号を返す。Apple Music の表記は一覧と少し違うことがある。"""
    best, best_score = None, 0.0
    for index, (_, song_artist, song_title) in enumerate(songs):
        title_score = score(title, song_title)
        artist_score = score(artist, song_artist) if song_artist else 1.0
        if title_score >= THRESHOLD and artist_score >= THRESHOLD and title_score + artist_score > best_score:
            best, best_score = index, title_score + artist_score
    if best is not None:
        return best
    # アーティスト名の表記が大きく違う曲は、曲名の完全一致で探す。
    return next((index for index, song in enumerate(songs) if score(title, song[2]) == 1.0), None)


def order_tracks(songs, tracks):
    """(曲の位置, 回, 曲名, アーティスト名) を放送順に返す。同じ順位の曲は元の並びを保つ。"""
    found = [find_song(songs, title, artist) for title, artist in tracks]
    positions = sorted(range(len(tracks)), key=lambda i: (found[i] is None, found[i] or 0))
    return [
        (i + 1, "" if found[i] is None else songs[found[i]][0], tracks[i][0], tracks[i][1]) for i in positions
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", required=True, help="プレイリストの曲名とアーティスト名のタブ区切りファイル")
    parser.add_argument("--program", choices=CSV_URLS, default="odoriba")
    parser.add_argument("--csv", help="番組の公開 CSV の代わりに読み込む CSV")
    args = parser.parse_args()

    songs = select_songs(load_songs(args.csv or CSV_URLS[args.program]), 0, "すべて")
    for row in order_tracks(songs, read_existing(args.tracks)):
        print("\t".join(map(str, row)))


if __name__ == "__main__":
    main()
