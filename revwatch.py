"""
Revision watch
==============
Notices when ANY page this dataset was built from changes, and re-downloads
only the ones that moved.

    python revwatch.py check     # report what changed; exit 1 if anything did
    python revwatch.py accept    # record the current revisions, then COMMIT

WHY NOT JUST RE-DOWNLOAD EVERYTHING
    836 pages -- 155 character pages and 681 episode pages -- at the one-second
    pause this project uses is fourteen minutes of requests against a free,
    volunteer-run wiki, every week, to discover that almost nothing changed.

    MediaWiki will answer "what revision is each of these pages on" for fifty
    titles in a single request. So the whole corpus costs SEVENTEEN requests to
    check, and only pages whose revision id actually moved get downloaded. In
    practice that is a handful a week.

WHY WATCH EVERYTHING AND NOT JUST THE GAPS
    The first version of this watched only the 59 episode pages with no
    summary, on the theory that a page which already has content only ever
    changes in ways that do not matter. That is wrong in the case that matters
    most: someone CORRECTING a page. A wrong episode number being fixed, a
    citation being added, a date being amended -- those all happen on pages
    that already look complete, and they are the edits most likely to mean this
    dataset is now wrong. Watching only the empty pages would have caught new
    information and missed corrections.

    The known Station 19 season 5-6 numbering errors are exactly this shape.

WHAT COUNTS AS A CHANGE WORTH REPORTING
    A revision id moving is the trigger, not the verdict. For episode pages the
    report also says whether the page went from having no usable summary to
    having one, because that is the change that turns an undatable tie into a
    datable one.
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

from wiki_harvest import UA, WIKI, CACHE as CHAR_CACHE, seeds, fetch_wikitext
import episode_harvest as ep

STATE = "revision_baseline.json"
# The API's own limit for an anonymous query. Asking for more silently drops
# the overflow, which would look like those pages had never changed.
BATCH = 50
PAUSE = 0.4
SUMMARY = re.compile(r"==\s*Full Summary\s*==(.+?)(?=\n==[^=])", re.S)
STUB_CHARS = 400


def summary_len(text: str) -> int:
    m = SUMMARY.search(text)
    return len((m.group(1) if m else "").strip())


def revisions(titles):
    """{title: revid} for many pages, fifty at a time.

    MediaWiki normalises titles it considers equivalent (underscores, initial
    case) and reports the mapping separately, so the result is keyed back to
    the title WE asked for -- otherwise a normalised title looks like a page
    that vanished and a brand-new one that appeared.
    """
    out, missing = {}, []
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        url = (f"{WIKI}/api.php?action=query&prop=revisions&rvprop=ids"
               f"&format=json&titles=" + urllib.parse.quote("|".join(chunk)))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        query = data.get("query", {})
        back = {n["to"]: n["from"] for n in query.get("normalized", [])}
        for pid, page in query.get("pages", {}).items():
            asked = back.get(page["title"], page["title"])
            if pid == "-1" or "missing" in page:
                missing.append(asked)
                continue
            revs = page.get("revisions") or [{}]
            out[asked] = revs[0].get("revid")
        time.sleep(PAUSE)
    return out, missing


def watched():
    """Every page the dataset reads, as {title: (kind, cache_path)}."""
    pages = {}
    for title in seeds():
        pages[title] = ("character",
                        os.path.join(CHAR_CACHE, title.replace("/", "_") + ".wiki"))
    if os.path.exists(ep.INDEX):
        with open(ep.INDEX, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                # An episode page and a character page can share a title; the
                # episode cache is keyed by file, so keep them apart by kind.
                pages.setdefault(row["Title"],
                                 ("episode", os.path.join(ep.CACHE, row["File"])))
    return pages


def refresh(title, kind, path):
    """Re-download one page. Returns (before, after) summary lengths."""
    before = summary_len(open(path, encoding="utf-8").read()) if os.path.exists(path) else 0
    text = ep.fetch(title) if kind == "episode" else fetch_wikitext(title)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return before, summary_len(text)


def check(accept=False):
    pages = watched()
    titles = sorted(pages)
    print(f"checking {len(titles)} page(s) in "
          f"{(len(titles) + BATCH - 1) // BATCH} request(s)...")
    now, missing = revisions(titles)

    prior = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            prior = json.load(fh)

    if not prior and not accept:
        print(f"\nNo {STATE} yet, so there is nothing to compare against.\n"
              f"Run `python revwatch.py accept` and commit it to set the baseline.")
        return 1

    changed = [t for t, r in now.items() if t in prior and prior[t] != r]
    added = [t for t in now if t not in prior]
    gone = [t for t in prior if t not in now]

    # Re-download only what moved, so the next parse reads the new text. This is
    # the entire point: the corpus stays current without re-fetching all of it.
    filled, failed = [], []
    for title in changed + added:
        kind, path = pages[title]
        try:
            before, after = refresh(title, kind, path)
        except Exception as exc:
            failed.append(f"{title} ({exc})")
            continue
        if kind == "episode" and before < STUB_CHARS <= after:
            filled.append((title, before, after))
        time.sleep(PAUSE)

    print(f"\n  changed : {len(changed)}")
    print(f"  new     : {len(added)}")
    print(f"  gone    : {len(gone)}")
    print(f"  no page : {len(missing)}")
    if failed:
        print(f"  re-download FAILED for {len(failed)}: {', '.join(failed[:5])}")

    for title in sorted(changed):
        kind = pages[title][0]
        print(f"    CHANGED  [{kind}] {title}")
    for title in sorted(added):
        print(f"    NEW      {title}")
    for title in sorted(gone):
        print(f"    GONE     {title}  (renamed? check ALIASES)")

    if filled:
        print(f"\n{len(filled)} episode page(s) went from having NO usable summary "
              f"to having one. These may date a tie that could not be dated before:")
        for title, before, after in filled:
            print(f"    {title}   {before} -> {after} chars")

    if accept:
        with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(now, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"\n{STATE}: {len(now)} revision(s) recorded. Commit it -- that "
              f"commit is the record that these were reviewed.")
        return 0

    if changed or added or gone:
        print("\nReview the pages above, then run `python revwatch.py accept` and "
              "commit revision_baseline.json. Nothing in CI can clear this.")
        return 1
    print("\nNothing has been edited since the last check.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["check", "accept"])
    args = ap.parse_args()
    sys.exit(check(accept=args.command == "accept"))
