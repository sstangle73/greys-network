"""
Portrait cache
==============
Downloads one small headshot per character from the Grey's Anatomy Universe Wiki
and writes portraits/manifest.csv, which greys_network.py reads to populate
Image_URL. The visualizer already knows what to do with that: cards become
circular portraits automatically.

    python fetch_portraits.py            # cache every character in nodes.csv
    python fetch_portraits.py --limit 5  # try a handful first

LICENSING -- READ THIS BEFORE PUBLISHING
    Unlike the relationship data, these are NOT facts. They are screencaps and
    promotional stills belonging to ABC/Shondaland, which the wiki hosts under
    its own terms. Caching them locally for a personal chart is one thing;
    committing them to a public repository is redistribution.

    portraits/ is therefore gitignored by default. If you decide to publish
    them, remove that line from .gitignore deliberately -- it should be your
    call, not a side effect.

NOTE ON WHICH IMAGE YOU GET
    The infobox image is whatever the wiki currently uses, which is usually a
    still from a RECENT episode. It is a headshot, not a plot point, but it does
    mean a portrait can come from further along than your cutoff.
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

from wiki_harvest import ALIASES, CACHE, UA, WIKI

OUT = "portraits"
PAUSE = 1.0          # the wiki is free and volunteer-run; same courtesy as the harvester
WIDTH = 200          # a node card is ~44px; 200 covers retina without pulling 3000px originals

INFOBOX_IMAGE = re.compile(r"^\s*\|\s*image\s*=\s*([^\s|<}][^\n|<}]*?)\s*$", re.M)


def cached_pages():
    """dataset name -> cached wikitext path, resolving the harvester's aliases."""
    out = {}
    if not os.path.isdir(CACHE):
        return out
    for fname in os.listdir(CACHE):
        if not fname.endswith(".wiki"):
            continue
        title = fname[:-5]
        out[ALIASES.get(title, title)] = os.path.join(CACHE, fname)
    return out


def image_field(path):
    text = open(path, encoding="utf-8").read()
    m = INFOBOX_IMAGE.search(text)
    if not m:
        return None
    value = m.group(1).strip()
    # Some infoboxes wrap it in a link or a gallery entry.
    value = re.sub(r"^\[\[(?:File|Image):", "", value).split("]]")[0].strip()
    return value or None


def resolve(filename):
    """File name -> a direct URL, scaled down rather than the full-size original."""
    url = (f"{WIKI}/api.php?action=query&prop=imageinfo&iiprop=url&format=json"
           f"&titles={urllib.parse.quote('File:' + filename)}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for _, page in data.get("query", {}).get("pages", {}).items():
        info = (page.get("imageinfo") or [{}])[0]
        direct = info.get("url")
        if not direct:
            continue
        base = direct.split("/revision/")[0]
        return f"{base}/revision/latest/scale-to-width-down/{WIDTH}"
    return None


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main(limit=None):
    os.makedirs(OUT, exist_ok=True)
    pages = cached_pages()

    with open("nodes.csv", encoding="utf-8") as fh:
        characters = [row["Character"] for row in csv.DictReader(fh)]
    if limit:
        characters = characters[:limit]

    manifest, missing, failed = [], [], []
    for name in characters:
        path = pages.get(name)
        if not path:
            missing.append(name)
            continue
        field = image_field(path)
        if not field:
            missing.append(name)
            continue

        target = os.path.join(OUT, slug(name) + os.path.splitext(field)[1].lower())
        if os.path.exists(target):
            manifest.append((name, target.replace("\\", "/")))
            print(f"  cached  {name}")
            continue

        try:
            direct = resolve(field)
            if not direct:
                raise LookupError("no imageinfo url")
            req = urllib.request.Request(direct, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as resp:
                blob = resp.read()
            with open(target, "wb") as out:
                out.write(blob)
            manifest.append((name, target.replace("\\", "/")))
            print(f"  got     {name}  ({len(blob) // 1024}KB)")
        except Exception as exc:
            failed.append(f"{name}: {exc}")
            print(f"  FAILED  {name}: {exc}", file=sys.stderr)
        time.sleep(PAUSE)

    with open(os.path.join(OUT, "manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Character", "File"])
        writer.writerows(sorted(manifest))

    print(f"\n{len(manifest)} portraits cached, {len(missing)} without a wiki image, "
          f"{len(failed)} failed")
    print("Re-run greys_network.py to fold them into nodes.csv.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="only try the first N characters")
    main(ap.parse_args().limit)
