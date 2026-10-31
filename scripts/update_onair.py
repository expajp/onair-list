#!/usr/bin/env python3
"""RSS と X API からオンエア曲一覧を更新する。

新しい回は X の投稿から曲と選曲者を決める。判定が危ない回があれば、結果を
プルリクエストにするよう workflow へ伝える。X のトークンは環境変数
X_BEARER_TOKEN から読み、出力やファイルには書かない。
"""
import argparse
import csv
import datetime as dt
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HEADER = ["タイトル", "オンエア日", "選曲者", "アーティスト名", "曲名"]
BASE_NUMBER = 206
BASE_DATE = dt.date(2021, 3, 29)
JST = dt.timezone(dt.timedelta(hours=9))
OFFICIAL = "kuki_odoriba"
LIVE_REPORTER = "i_love_arata"
MOGURA = "鈴木もぐら"
KATAMARI = "水川かたまり"
LISTENER = "リスナー"
SECOND_HALF = dt.time(0, 40)
SEARCH_LIMIT = dt.timedelta(days=7)
SIMILARITY = 0.6
QUERY = (
    f"(from:{OFFICIAL} OR from:{LIVE_REPORTER}) "
    '("1曲目" OR "１曲目" OR "一曲目" OR "2曲目" OR "２曲目" OR "二曲目" OR "3曲目" OR "３曲目" OR サイコゥ) '
    "-is:retweet"
)
LABEL_PATTERNS = (
    ("second_half", re.compile(r"サイコゥ\s*(ソング|song)", re.I)),
    ("first", re.compile(r"[1１一]\s*曲目")),
    ("second", re.compile(r"[2２二]\s*曲目")),
    ("extra", re.compile(r"[3-9３-９三-九]\s*曲目")),
)
SONG_MARK = re.compile(r"[♪♫♬🎵🎶]")
LABEL_PREFIX = re.compile(r"^.*?(?:曲目|サイコゥ\s*(?:ソング|song))[^\s]*\s*", re.I)


def air_date(number):
    return BASE_DATE + dt.timedelta(weeks=number - BASE_NUMBER)


def broadcast_window(number):
    """放送枠と直後の投稿を含む時間帯を返す。月曜24時は火曜0時に当たる。"""
    start = dt.datetime.combine(air_date(number) + dt.timedelta(days=1), dt.time(0, 0), JST)
    return start, start + dt.timedelta(minutes=75)


def latest_aired(now):
    tuesday = now.date() - dt.timedelta(days=(now.weekday() - 1) % 7)
    if now < dt.datetime.combine(tuesday, dt.time(1, 15), JST):
        tuesday -= dt.timedelta(weeks=1)
    return BASE_NUMBER + (tuesday - dt.timedelta(days=1) - BASE_DATE).days // 7


def honpen_titles(rss_path):
    """【本編】だけを読み、【本編】を除いたタイトルを返す。"""
    titles = {}
    for item in ET.parse(rss_path).getroot().iter("item"):
        text = (item.findtext("title") or "").strip()
        match = re.fullmatch(r"#(\d+)【本編】\s*(.*)", text, re.S)
        if match:
            titles.setdefault(int(match.group(1)), f"#{match.group(1)} {match.group(2).strip()}")
    return titles


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if rows[0] != HEADER:
        sys.exit(f"CSV の列が想定と異なります: {rows[0]}")
    return rows[1:]


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)


def row_number(row):
    return int(re.match(r"#(\d+)", row[0]).group(1))


def half_width(text):
    """全角の英数字と記号だけを半角へ直す。日本語の表記は変えない。"""
    return "".join(
        chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else (" " if c == "　" else c) for c in text
    )


def clean_field(text):
    text = half_width(text).strip()
    while text and (unicodedata.category(text[-1]) in ("So", "Sk", "Mn", "Cf") or text[-1] == "️"):
        text = text[:-1].rstrip()
    return re.sub(r"\s+", " ", text).strip(" 「」\"")


def key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text)).lower()


def similar(a, b):
    a, b = key(a), key(b)
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= SIMILARITY


def parse_post(post):
    """投稿を解析する。曲を示さない投稿は None を返す。"""
    text = post["text"]
    if "推薦曲" in text:
        return None
    label = next((name for name, pattern in LABEL_PATTERNS if pattern.search(text)), None)
    if label is None:
        return None

    lines = []
    for line in text.splitlines():
        line = re.sub(r"https?://\S+|#\S+|@\S+", "", line).strip()
        if line and "TBSラジオ" not in line:
            lines.append(line)

    marked = [line for line in lines if SONG_MARK.search(line)]
    body = None
    for index, line in enumerate(lines):
        candidate = SONG_MARK.sub("", line).strip()
        if any(pattern.search(candidate) for _, pattern in LABEL_PATTERNS):
            candidate = LABEL_PREFIX.sub("", candidate)
        if re.search(r"[／/]", candidate):
            if re.search(r"[／/]\s*$", candidate) and index + 1 < len(lines):
                candidate += lines[index + 1]
            if not marked or SONG_MARK.search(line):
                body = candidate
                break

    result = {"label": label, "time": post["time"], "official": post["official"], "listener": "リスナー" in text}
    if body is None:
        # 雑談にも「1曲目」は出てくるので、曲の記号がない投稿は無視する。
        return {**result, "unparsed": True, "text": text} if marked else None

    left, right = (clean_field(part) for part in re.split(r"[／/]", body, maxsplit=1))
    if not left or not right:
        return {**result, "unparsed": True, "text": text}
    # 公式は「曲名／アーティスト」、実況は主に「アーティスト/曲名」の順で書く。
    artist, title = (right, left) if post["official"] else (left, right)
    return {**result, "artist": artist, "title": title}


def reconcile(official, live, artists):
    """同じ枠の公式と実況を1曲にまとめる。一致しなければ None を返す。"""
    if official and live:
        if similar(official["title"], live["title"]) and similar(official["artist"], live["artist"]):
            return {**official, "artist": live["artist"], "title": live["title"], "time": min(official["time"], live["time"])}
        if similar(official["title"], live["artist"]) and similar(official["artist"], live["title"]):
            return {**official, "artist": live["title"], "title": live["artist"], "time": min(official["time"], live["time"])}
        return None
    song = official or live
    if not official and key(song["artist"]) not in artists and key(song["title"]) in artists:
        return {**song, "artist": song["title"], "title": song["artist"]}
    return song


def decide_episode(posts, artists):
    """1回分の曲と選曲者を決め、確認が必要な理由も返す。"""
    parsed = [p for p in map(parse_post, posts) if p]
    reasons = [f"曲名を解析できない投稿があります: {p['text'][:60]!r}" for p in parsed if p.get("unparsed")]
    usable = [p for p in parsed if not p.get("unparsed")]

    songs = {}
    for label, _ in LABEL_PATTERNS:
        group = [p for p in usable if p["label"] == label]
        if not group:
            continue
        official = next((p for p in group if p["official"]), None)
        live = next((p for p in group if not p["official"]), None)
        song = reconcile(official, live, artists)
        if song is None:
            reasons.append(
                f"公式と実況で曲が異なります: {official['title']} / {official['artist']} と "
                f"{live['artist']} / {live['title']}"
            )
            song = official
        songs[label] = song

    rows = []
    if "first" in songs:
        first = songs["first"]
        if "second" in songs or first["listener"]:
            selector = LISTENER
        elif "second_half" not in songs and first["time"].time() >= SECOND_HALF:
            selector = KATAMARI
        else:
            selector = MOGURA
        rows.append((selector, first))
    if "second" in songs:
        reasons.append("2曲目の投稿があります。リスナー選曲か確認してください")
        rows.append((LISTENER, songs["second"]))
    if "extra" in songs:
        rows.append((MOGURA, songs["extra"]))
    if "second_half" in songs:
        rows.append((KATAMARI, songs["second_half"]))
    if len(rows) >= 3:
        reasons.append(f"{len(rows)}曲あります。選曲者を確認してください")
    return [{"selector": s, "artist": x["artist"], "title": x["title"]} for s, x in rows], reasons


def fetch_posts(token, start, end, query=QUERY):
    """放送時間帯の投稿を取得する。読み取りは件数課金なので2ページで止める。"""
    params = {
        "query": query,
        "start_time": start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_results": "100",
        "post.fields": "created_at,author_id,note_post",
        "expansions": "author_id",
        "user.fields": "username",
    }
    posts = []
    for _ in range(2):
        request = urllib.request.Request(
            "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(params),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "onair-list-updater"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            sys.exit(f"X API がエラーを返しました: HTTP {error.code} {error.read()[:300]!r}")
        users = {u["id"]: u["username"] for u in payload.get("includes", {}).get("users", [])}
        for item in payload.get("data", []):
            posts.append(
                {
                    "text": item.get("note_post", {}).get("text") or item["text"],
                    "time": dt.datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).astimezone(JST),
                    "official": users.get(item.get("author_id"), "").lower() == OFFICIAL,
                }
            )
        next_token = payload.get("meta", {}).get("next_token")
        if not next_token:
            break
        params["next_token"] = next_token
    return posts


def build_update(rows, titles, now, posts_for, skip=frozenset()):
    """CSV の更新内容と、プルリクエストにする理由を返す。"""
    known = {row_number(row) for row in rows}
    latest = latest_aired(now)
    updated = [[titles.get(row_number(r), r[0]) if re.fullmatch(r"#\d+", r[0]) else r[0], *r[1:]] for r in rows]
    changed_titles = sum(a[0] != b[0] for a, b in zip(rows, updated))
    artists = {key(row[3]) for row in rows if row[3]}

    reasons, added = [], []
    for number in range(BASE_NUMBER, latest + 1):
        if number in known or number in skip:
            continue
        title = titles.get(number, f"#{number}")
        start, end = broadcast_window(number)
        if now - start >= SEARCH_LIMIT:
            songs = []
            reasons.append(f"#{number}: 検索できる7日間を過ぎたため、曲を取得できませんでした")
        else:
            songs, episode_reasons = decide_episode(posts_for(start, end), artists)
            reasons += [f"#{number}: {reason}" for reason in episode_reasons]
        date = air_date(number).isoformat()
        added.append({"number": number, "songs": songs})
        for song in songs or [{"selector": "", "artist": "", "title": ""}]:
            updated.append([title, date, song["selector"], song["artist"], song["title"]])

    updated.sort(key=row_number)
    return updated, {"added": added, "changed_titles": changed_titles, "reasons": reasons}


def pr_body(summary):
    lines = ["## 追加した回", "", "| 回 | 選曲者 | アーティスト名 | 曲名 |", "| --- | --- | --- | --- |"]
    for episode in summary["added"]:
        for song in episode["songs"] or [{"selector": "", "artist": "", "title": "曲なし"}]:
            lines.append(f"| #{episode['number']} | {song['selector']} | {song['artist']} | {song['title']} |")
    lines += ["", "## 確認してほしい点", ""]
    lines += [f"- [ ] {reason}" for reason in summary["reasons"]]
    lines += ["", "問題なければマージしてください。修正する場合は、CSV を編集してからマージしてください。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/onair_songs.csv")
    parser.add_argument("--rss", required=True)
    parser.add_argument("--body", default="pr_body.md", help="プルリクエスト本文の出力先")
    parser.add_argument("--skip", default="", help="処理しない回番号のカンマ区切り。確認待ちの回に使う")
    parser.add_argument("--check", type=int, help="指定した回の判定結果を表示する。CSV は変更しない")
    args = parser.parse_args()

    now = dt.datetime.now(JST)
    skip = {int(n) for n in args.skip.split(",") if n}
    rows = read_rows(args.csv)
    titles = honpen_titles(args.rss)

    def posts_for(start, end):
        token = os.environ.get("X_BEARER_TOKEN")
        if not token:
            sys.exit("X_BEARER_TOKEN が設定されていません")
        return fetch_posts(token, start, end)

    if args.check:
        artists = {key(row[3]) for row in rows if row[3]}
        posts = posts_for(*broadcast_window(args.check))
        print(f"#{args.check}: 取得した投稿 {len(posts)} 件")
        print(json.dumps(decide_episode(posts, artists), ensure_ascii=False, indent=2))
        return

    updated, summary = build_update(rows, titles, now, posts_for, skip)
    if updated != rows:
        write_rows(args.csv, updated)
    mode = "none" if updated == rows else ("pr" if summary["reasons"] else "direct")
    numbers = [e["number"] for e in summary["added"]]
    label = "、".join(f"#{n}" for n in numbers) or "タイトル"
    if mode == "pr":
        with open(args.body, "w", encoding="utf-8") as f:
            f.write(pr_body(summary))
    print(f"mode={mode} added={numbers} titles={summary['changed_titles']} reasons={len(summary['reasons'])}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"mode={mode}\nlabel={label}\nbranch=update/onair-{numbers[0] if numbers else 'titles'}\n")


if __name__ == "__main__":
    main()
