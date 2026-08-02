"""
Episode-page harvester
======================
Caches one wiki page per episode, across all three shows, and indexes them by
show/season/episode.

WHY THIS EXISTS
    Character pages are where the audit started, and they run out. Citation
    density on the character pages begins around Grey's season 9 -- before that
    the ==Romantic== sections are largely unreferenced prose, which is why
    roughly thirty ties still have no episode.

    Episode pages do not have that problem, and they solve a harder one too:
    the episode number is ON THE PAGE (`|episode = 1`) and the season is the
    CATEGORY the page belongs to. So a fact found in an episode summary arrives
    already dated. There is no inference step, which means none of the
    infer_season() failure modes apply.

    python episode_harvest.py list        # how many episodes per show/season
    python episode_harvest.py harvest     # ~665 pages -> ./episodecache
    python episode_harvest.py scan "Alex Karev" "Reed Adamson"

CACHING AND COURTESY
    Pages are cached and never re-fetched, with the same one-second pause the
    character harvester uses. The wiki is free and volunteer-run; 665 pages is
    already a lot to ask for, so ask once.

LICENSING
    Same as the character cache: episodecache/ is gitignored and never
    published. What leaves this directory is facts -- who, what, which episode.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from wiki_harvest import UA, WIKI

CACHE = "episodecache"
INDEX = os.path.join(CACHE, "index.csv")
PAUSE = 1.0

# Category naming on this wiki, confirmed against the live API:
#   Category:GA S14 Episodes / PP S1 Episodes / S19 S7 Episodes
SHOW_SEASONS = {"GA": 22, "PP": 6, "S19": 7}


def api(params):
    url = WIKI + "/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def season_members(show, season):
    """Episode page titles in one season's category."""
    out, cont = [], {}
    while True:
        params = {"action": "query", "list": "categorymembers",
                  "cmtitle": f"Category:{show} S{season} Episodes",
                  "cmlimit": "500", "format": "json", **cont}
        data = api(params)
        out += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        if "continue" not in data:
            return out
        cont = data["continue"]


def fetch(title):
    url = (WIKI + "/api.php?action=query&prop=revisions&rvslots=*&rvprop=content"
           "&format=json&titles=" + urllib.parse.quote(title))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for pid, page in data.get("query", {}).get("pages", {}).items():
        if pid == "-1" or "missing" in page:
            raise LookupError(title)
        return page["revisions"][0]["slots"]["main"]["*"]
    raise LookupError(title)


EPISODE_NUM = re.compile(r"^\s*\|\s*episode\s*=\s*(\d+)", re.M)


def cmd_list():
    total = 0
    for show, seasons in SHOW_SEASONS.items():
        for season in range(1, seasons + 1):
            n = len(season_members(show, season))
            total += n
            print(f"  {show:<4} S{season:<2} {n:>3} episodes")
            time.sleep(0.2)
    print(f"\n{total} episode pages in total")


def cmd_harvest():
    os.makedirs(CACHE, exist_ok=True)
    index = []
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as fh:
            index = list(csv.DictReader(fh))
    have = {(r["Show"], r["Season"], r["Title"]) for r in index}

    for show, seasons in SHOW_SEASONS.items():
        for season in range(1, seasons + 1):
            try:
                titles = season_members(show, season)
            except Exception as exc:
                print(f"  FAILED  {show} S{season} listing: {exc}", file=sys.stderr)
                continue
            for title in titles:
                if (show, str(season), title) in have:
                    continue
                safe = re.sub(r"[^A-Za-z0-9 ._-]", "_", title)
                path = os.path.join(CACHE, f"{show}_{season:02d}_{safe}.wiki")
                if os.path.exists(path):
                    text = open(path, encoding="utf-8").read()
                else:
                    try:
                        text = fetch(title)
                    except Exception as exc:
                        print(f"  FAILED  {title}: {exc}", file=sys.stderr)
                        time.sleep(PAUSE)
                        continue
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text)
                    time.sleep(PAUSE)
                m = EPISODE_NUM.search(text)
                index.append({"Show": show, "Season": str(season),
                              "Episode": m.group(1) if m else "",
                              "Title": title, "File": os.path.basename(path)})
                print(f"  {show} S{season:>2}E{(m.group(1) if m else '??'):>2}  {title}")

    with open(INDEX, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Show", "Season", "Episode", "Title", "File"])
        w.writeheader()
        w.writerows(sorted(index, key=lambda r: (r["Show"], int(r["Season"]),
                                                 int(r["Episode"] or 0))))
    print(f"\n{len(index)} episodes indexed in {INDEX}")


# Language that marks a relationship BEGINNING rather than merely two people
# being in the same scene. Deliberately narrow: this produces candidates for a
# person to read, and a loose pattern would bury the real hit in noise.
STARTS = re.compile(
    r"\b(slept together|sleep together|had sex|have sex|hooked up|hook up|"
    r"one-night stand|kissed|kiss(?:es|ing)?\b|asked (?:her|him) out|"
    r"went on a date|first date|started dating|began dating|"
    r"start(?:ed)? seeing|became a couple|spent the night)\b", re.I)


def cmd_scan(a, b, show=None, season=None):
    if not os.path.exists(INDEX):
        sys.exit("no index yet -- run: python episode_harvest.py harvest")
    with open(INDEX, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    first_a, first_b = a.split()[0], b.split()[0]
    hits = []
    for row in rows:
        if show and row["Show"] != show:
            continue
        if season and row["Season"] != str(season):
            continue
        path = os.path.join(CACHE, row["File"])
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        # Full Summary only: Cast lists and Medical Notes name everyone.
        m = re.search(r"==\s*Full Summary\s*==(.+?)(?=\n==[^=])", text, re.S)
        body = m.group(1) if m else text
        for para in re.split(r"\n\s*\n", body):
            if first_a in para and first_b in para and STARTS.search(para):
                hits.append((row, para.strip()))
                break

    if not hits:
        print(f"No candidate episode found for {a} & {b}.")
        return
    print(f"{len(hits)} candidate episode(s) for {a} & {b}:\n")
    for row, para in hits:
        print(f"  {row['Show']} {row['Season']}x{row['Episode'].zfill(2)}  {row['Title']}")
        snippet = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"\1", para)
        snippet = re.sub(r"<ref[^>]*>.*?</ref>", "", snippet, flags=re.S)
        snippet = re.sub(r"\s+", " ", snippet)
        print(f"      {snippet[:260]}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["list", "harvest", "scan"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--show")
    ap.add_argument("--season")
    args = ap.parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "harvest":
        cmd_harvest()
    else:
        if len(args.names) != 2:
            sys.exit('scan needs two names: scan "Alex Karev" "Reed Adamson"')
        cmd_scan(*args.names, show=args.show, season=args.season)
