#!/usr/bin/env python3
"""指定した回以降の曲を Apple Music のカタログから探し、タブ区切りで出力する。

開発者登録が不要な iTunes Search API を使う。列は次の順に並ぶ。
状態, 回, アーティスト名, 曲名, Apple Music の URL, カタログの曲名, カタログのアーティスト名
状態は found, not_found, exists のいずれかになる。
"""
import argparse
import csv
import difflib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

CSV_URLS = {
    "odoriba": "https://expajp.github.io/onair-list/data/onair_songs.csv",
    "ann0": "https://expajp.github.io/onair-list/data/magical_lovely_ann0_songs.csv",
}
SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "onair-list-apple-music"
# 公開 API は1分あたり20回程度までとされている。
SEARCH_INTERVAL = 3.2
THRESHOLD = 0.8


def key(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[\(（\[〔].*?[\)）\]〕]", "", text) or text
    text = re.sub(r"\b(feat|ft|with)\b.*", "", text) or text
    return re.sub(r"[\W_]+", "", text)


def score(a, b):
    a, b = key(a), key(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def load_songs(source):
    if re.match(r"https?://", source):
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8-sig")
    else:
        with open(source, encoding="utf-8-sig") as f:
            text = f.read()
    return list(csv.DictReader(io.StringIO(text)))


def select_songs(rows, start, selector):
    songs, seen = [], set()
    for row in rows:
        # 単発放送はレギュラー放送の #1 より前なので、0回目として扱う。
        special, number = re.match(r"(単発)?#(\d+)", row["タイトル"]).groups()
        if (0 if special else int(number)) < start or not row["曲名"]:
            continue
        if selector != "すべて" and row["選曲者"] != selector:
            continue
        identity = (key(row["アーティスト名"]), key(row["曲名"]))
        if identity not in seen:
            seen.add(identity)
            songs.append((row["タイトル"].split()[0], row["アーティスト名"], row["曲名"]))
    return songs


def search(term):
    params = {"term": term, "country": "jp", "lang": "ja_jp", "entity": "song", "limit": "25"}
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response).get("results", [])


def best_match(artist, title):
    """曲名とアーティスト名の両方が近い候補を返す。

    実在しない候補を追加しないよう、アーティスト名が不明な曲は曲名の完全一致だけを認める。
    """
    terms = [f"{artist} {title}".strip()]
    if artist:
        terms.append(title)
    for index, term in enumerate(terms):
        if index:
            time.sleep(SEARCH_INTERVAL)
        best, best_score = None, 0.0
        for item in search(term):
            title_score = score(title, item.get("trackName", ""))
            artist_score = score(artist, item.get("artistName", "")) if artist else 1.0
            required = THRESHOLD if artist else 1.0
            if title_score >= required and artist_score >= THRESHOLD and title_score + artist_score > best_score:
                best, best_score = item, title_score + artist_score
        if best:
            return best
    return None


def read_existing(path):
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return [tuple((line.rstrip("\n").split("\t") + [""])[:2]) for line in f if line.strip()]


def in_playlist(existing, artist, title):
    return any(score(title, t) >= 0.9 and (not artist or score(artist, a) >= THRESHOLD) for t, a in existing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, required=True, help="この回以降を対象にする")
    parser.add_argument("--selector", required=True, help="選曲者。「すべて」で全員を対象にする")
    parser.add_argument("--existing", help="プレイリストの曲名とアーティスト名のタブ区切りファイル")
    parser.add_argument("--program", choices=CSV_URLS, default="odoriba")
    parser.add_argument("--csv", help="番組の公開 CSV の代わりに読み込む CSV")
    args = parser.parse_args()

    songs = select_songs(load_songs(args.csv or CSV_URLS[args.program]), args.start, args.selector)
    existing = read_existing(args.existing)
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar="\\")
    for index, (episode, artist, title) in enumerate(songs):
        if in_playlist(existing, artist, title):
            writer.writerow(["exists", episode, artist, title, "", "", ""])
            continue
        if index:
            time.sleep(SEARCH_INTERVAL)
        match = best_match(artist, title)
        if match and in_playlist(existing, match["artistName"], match["trackName"]):
            writer.writerow(["exists", episode, artist, title, "", match["trackName"], match["artistName"]])
        elif match:
            url = match["trackViewUrl"].split("&uo=")[0]
            writer.writerow(["found", episode, artist, title, url, match["trackName"], match["artistName"]])
        else:
            writer.writerow(["not_found", episode, artist, title, "", "", ""])
        sys.stdout.flush()


if __name__ == "__main__":
    main()
