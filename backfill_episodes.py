"""
Episode backfill
================
Recovers First_Episode for ties that are still sitting on the season boundary.

REPORT ONLY. DO NOT TRUST THE OUTPUT WITHOUT READING THE PROSE.
    This was written expecting it to be safe: the season is already audited, so
    narrowing to codes INSIDE that season, in that pair's own section, and
    taking the earliest, looked bounded -- worst case a later episode, which is
    the safe direction under the date-late rule.

    That reasoning is wrong, and here is the case that proves it:

        Owen Hunt & Teddy Altman, season 14. This picks 14x02. The prose at
        14x02 is Owen kissing Teddy and TEDDY BACKING AWAY. The relationship
        actually starts at 14x17. Mining lands fifteen episodes EARLY.

    A ==Romantic== section narrates the friendship, the near-misses and the
    rejected passes before it gets to the relationship, so the earliest code in
    a season is routinely a beat that is not the tie. The error is systematically
    in the EARLY direction -- the one that spoils people.

    This is infer_season()'s failure mode one level down, and it is why the
    audited backfill used hand-checked citations from citations.csv instead:
    those record the episode of the EVENT, because a human read the sentence.

    Treat this as a candidate generator, like the diff. Every hit needs the
    prose checked before it becomes a date. --write exists for after that.

    python backfill_episodes.py            # report only
    python backfill_episodes.py --write    # only after checking each one
"""

import argparse
import csv
import os
import re

import review
from wiki_harvest import ALIASES, CACHE

CODE = re.compile(r"\b(\d{1,2})x(\d{2})\b")
# Sections whose codes describe something other than the relationship.
NOISE = re.compile(r"quote|trivia|gallery|memorable", re.I)


def cached_pages():
    out = {}
    if not os.path.isdir(CACHE):
        return out
    for fname in os.listdir(CACHE):
        if fname.endswith(".wiki"):
            title = fname[:-5]
            out[ALIASES.get(title, title)] = title
    return out


def earliest_in_season(subject_file, partner, season):
    """Earliest episode code in that pair's own section, inside `season`."""
    try:
        text = review.load(subject_file)
    except FileNotFoundError:
        return None
    best = None
    for name, _level, body in review.sections(text):
        canon = ALIASES.get(name.split("|")[0].strip(), name.split("|")[-1].strip())
        if partner.lower() not in canon.lower() and canon.lower() not in partner.lower():
            continue
        if NOISE.search(name):
            continue
        for s, e in CODE.findall(body):
            if int(s) != season:
                continue
            ep = int(e)
            if ep > 1 and (best is None or ep < best):
                best = ep
    return best


def main(write=False):
    pages = cached_pages()
    edges = [e for e in csv.DictReader(open("edges.csv", encoding="utf-8"))
             if e["Relationship_Type"] != "Parent"]

    cites = {}
    fields = ["Source", "Target", "Citation", "Confidence", "Note"]
    if os.path.exists("citations.csv"):
        with open("citations.csv", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames)
            for row in reader:
                cites[frozenset({row["Source"], row["Target"]})] = row

    found, missed = [], []
    for e in edges:
        if int(e["First_Episode"]) > 1:
            continue
        season = int(e["First_Season"])
        hit = None
        for a, b in ((e["Source"], e["Target"]), (e["Target"], e["Source"])):
            page = pages.get(a)
            if not page:
                continue
            hit = earliest_in_season(page, b, season)
            if hit:
                break
        if hit:
            found.append((e, hit))
        else:
            missed.append(e)

    print(f"{len(found)} episode(s) recovered, {len(missed)} still on the boundary\n")
    for e, ep in sorted(found, key=lambda t: (t[0]["Show"], int(t[0]["First_Season"]))):
        print(f"  {e['Show']:<4} S{e['First_Season']:>2} E01 -> E{ep:02d}   "
              f"{e['Source']} & {e['Target']}")

    if not write:
        print("\n(report only; pass --write to record these in citations.csv)")
        return

    for e, ep in found:
        key = frozenset({e["Source"], e["Target"]})
        row = cites.get(key)
        code = f"{e['First_Season']}x{ep:02d}"
        if row:
            if code not in (row.get("Citation") or ""):
                row["Citation"] = (code + ";" + row["Citation"]).strip(";")
            if row.get("Confidence") in (None, "", "unrecorded"):
                row["Confidence"] = "episode-mined"
        else:
            cites[key] = {f: "" for f in fields} | {
                "Source": e["Source"], "Target": e["Target"], "Citation": code,
                "Confidence": "episode-mined",
                "Note": "Earliest code inside the audited season, from that pair's own section",
            }

    with open("citations.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in sorted(cites.values(), key=lambda r: (r["Source"], r["Target"])):
            w.writerow(row)
    print(f"\ncitations.csv updated ({len(cites)} rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    main(ap.parse_args().write)
