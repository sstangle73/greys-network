"""
Citation verifier
=================
Checks every `cited` row in citations.csv against the episode page it names.

WHY
    `cited` is the highest confidence tier in this dataset, and it turned out
    not to be a guarantee. Meredith and George were recorded as `2x12, cited`.
    Episode 2x12 has a stub summary and contains no Meredith/George content at
    all -- the encounter is the closing scene of 2x18. One person read one page
    and wrote down a number, and nothing checked it.

    That was caught by luck, because a second pass happened to re-derive it.
    This checks the whole tier instead: for each cited code, open that episode
    page and confirm both people are actually in it.

WHAT A FAILURE MEANS
    Not necessarily a wrong date. An episode page can have a stub summary, and
    a pair can be named by first name only. A hit here means "nothing supports
    this citation on the page it points at" -- a prompt to go read, not a
    verdict.

    python verify_citations.py            # report
    python verify_citations.py --strict   # exit non-zero if anything fails
"""

import argparse
import csv
import os
import re
import sys

CACHE = "episodecache"
INDEX = os.path.join(CACHE, "index.csv")
CODE = re.compile(r"\b(\d{1,2})x(\d{2})\b")
# Which show a citation belongs to, when it says so.
SHOW_TAG = re.compile(r"\((PP|S19)\)")


def load_index():
    if not os.path.exists(INDEX):
        sys.exit("no episode cache -- run: python episode_harvest.py harvest")
    by_key = {}
    with open(INDEX, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["Show"], int(row["Season"]), int(row["Episode"] or 0))
            by_key[key] = row
    return by_key


# Episode summaries use the name people are CALLED on screen, which is often not
# the name in the dataset. Without these the checker reports Link, Vic and Dink
# as missing from every episode they are in -- the first run produced 45 hits,
# most of them this.
NICKNAMES = {
    "Atticus Lincoln": ["Link"],
    "Victoria Hughes": ["Vic"],
    "Vikram Roy": ["Vik"],
    "Fillmore Davis": ["Dink"],
    "Robert Sullivan": ["Sullivan", "Sully"],
    "Andrew DeLuca": ["DeLuca"],
    "Carina DeLuca": ["Carina"],
    "Miranda Bailey": ["Bailey"],
    "Benson Kwan": ["Kwan"],
    "Nathan Riggs": ["Riggs"],
    "Michael Dixon": ["Dixon"],
    "Preston Burke": ["Burke"],
    "Tom Koracick": ["Koracick"],
    "Cormac Hayes": ["Hayes"],
    "Nico Kim": ["Nico"],
    "Levi Schmitt": ["Schmitt", "Glasses"],
    "Mika Yasuda": ["Mika"],
    "Jules Millin": ["Jules"],
    "Simone Griffith": ["Simone"],
    "Winston Ndugu": ["Ndugu", "Winston"],
}


def names_for(full):
    """Ways the wiki might refer to someone: full name, surname, first name."""
    parts = full.split()
    out = {full}
    if len(parts) > 1:
        out.add(parts[-1])
    out.add(parts[0])
    out.update(NICKNAMES.get(full, []))
    return out


def mentions(text, person):
    return any(re.search(rf"\b{re.escape(n)}\b", text) for n in names_for(person))


def main(strict=False):
    index = load_index()
    with open("edges.csv", encoding="utf-8") as fh:
        show_of = {frozenset({r["Source"], r["Target"]}): r["Show"]
                   for r in csv.DictReader(fh)}

    checked = unsupported = skipped = 0
    problems, stubs = [], []

    with open("citations.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("Confidence") != "cited":
                continue
            pair = frozenset({row["Source"], row["Target"]})
            home = show_of.get(pair, "GA")
            for chunk in (row.get("Citation") or "").split(";"):
                m = CODE.search(chunk)
                if not m:
                    continue
                tag = SHOW_TAG.search(chunk)
                show = tag.group(1) if tag else home
                season, ep = int(m.group(1)), int(m.group(2))
                page = index.get((show, season, ep))
                if not page:
                    skipped += 1
                    continue
                path = os.path.join(CACHE, page["File"])
                if not os.path.exists(path):
                    skipped += 1
                    continue
                text = open(path, encoding="utf-8").read()
                body = re.search(r"==\s*Full Summary\s*==(.+?)(?=\n==[^=])", text, re.S)
                body = body.group(1) if body else text
                # The summary calls people what they are CALLED on screen, and a
                # character can appear without ever being named aloud. Bailey's
                # husband is credited "[[Tucker Jones|Bailey's Husband]]" and the
                # summary only ever says "her husband" -- so the strongest proof
                # he is in the episode sits in the cast list, which this was not
                # reading. That is not a laxer test: the question being asked is
                # whether the person is in the episode, and a credit answers it
                # more directly than the prose does.
                cast = re.search(r"\n==\s*Cast\s*==(.+?)(?=\n==[^=])", text, re.S)
                cast = cast.group(1) if cast else ""
                checked += 1
                # A page with no real summary cannot support OR refute a
                # citation. That is a gap in the source, not an error in the
                # data, and conflating the two buries the real signal.
                if len(body.strip()) < 400:
                    stubs.append(f"{row['Source']} & {row['Target']}  "
                                 f"{show} {season}x{ep:02d} ({page['Title']})")
                    continue
                missing = [p for p in (row["Source"], row["Target"])
                           if not mentions(body, p) and not mentions(cast, p)]
                if missing:
                    unsupported += 1
                    problems.append(
                        f"{row['Source']} & {row['Target']}  "
                        f"{show} {season}x{ep:02d} ({page['Title']})"
                        f"  -- no mention of {', '.join(missing)}")

    print(f"checked {checked} cited codes, {skipped} with no cached page")
    print(f"{len(stubs)} pointed at a page with no usable summary "
          f"(source gap, not a data error)\n")
    if not problems:
        print("Every checkable cited episode names both people. The tier holds.")
    else:
        print(f"{unsupported} citation(s) NOT supported by the page they name:\n")
        for line in sorted(problems):
            print("  " + line)
    if strict and problems:
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true")
    main(ap.parse_args().strict)
