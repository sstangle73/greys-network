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

    Beyond that the report is GRADED, because a flat list of edited pages is
    mostly noise. The scheduled run of 2026-08-23 named fifteen changed pages:
    five were vandalism that had already been reverted, so the text was
    byte-identical to the baseline, and not one of the fifteen moved a value in
    edges.csv. Fifteen pages to open, nothing to decide.

    So each edit is compared against the regions the parsers actually read --
    see classify_edit() -- and only a page where the parsed VALUES moved fails
    the job. The judgement call stays a human one; what changes is that the
    queue holds the edits that need judging instead of every edit.
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

from wiki_harvest import (UA, WIKI, CACHE as CHAR_CACHE, seeds, fetch_wikitext,
                          infobox_partners, romantic_sections, canonical,
                          infer_season, classify, EPISODE_REF)
import episode_harvest as ep
# Imported rather than reimplemented: if the citation checker's idea of "this
# page names this person" changes, this must change with it.
from verify_citations import mentions

STATE = "revision_baseline.json"
# Pages whose CURRENT revision has already been classified as harmless, so a
# run that changes nothing does not re-fetch and re-classify them forever.
# This lives in the cache directory and not the repo because it is an
# optimisation, not a record: losing it costs requests, never correctness.
# The drift job's cache is best-effort -- it was empty on the run that prompted
# all this -- so nothing here may depend on it surviving.
CLEARED = os.path.join(CHAR_CACHE, "revwatch_cleared.json")
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
    """Re-download one page into the cache. Returns the new wikitext."""
    text = ep.fetch(title) if kind == "episode" else fetch_wikitext(title)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


# --------------------------------------------------------------------------- #
# Grading an edit against what the dataset reads
# --------------------------------------------------------------------------- #
#
# The regions below are not restated from the parsers, they are IMPORTED from
# them. infobox_partners, romantic_sections, infer_season and classify are the
# same functions parse() calls, and SUMMARY is what the harvest reads off an
# episode page. Teaching the parser to read something new therefore teaches
# this at the same time, instead of leaving a classifier that quietly clears
# edits to a field that now matters.
#
#   CLEAR     the edit missed every region the parsers read -- trivia, images,
#             appearance tables, an infobox field nothing looks at. It cannot
#             reach edges.csv, so it is accepted without anyone reading it.
#   COPYEDIT  the edit landed inside a read region, but running the parsers
#             over both revisions produces identical values. Reported with the
#             wording change so it is visible, but it does not block.
#   REVIEW    the parsers disagree across the two revisions. The only tier that
#             fails the job.
#
# Anything unclassifiable is REVIEW: a page with no baseline revision, a fetch
# that failed, a revision that came back empty. Guessing CLEAR on a page that
# could not be read is the single mistake that would lose data silently, so it
# is the one case the code refuses to guess at.


def _content_at(revid):
    """The wikitext of one specific revision.

    From the API rather than the local cache on purpose. The "before" copy is
    exactly what a cold cache does not have -- the run this was written for
    logged `WARNING: Cache file does not exist` and re-downloaded all 155
    character pages -- whereas the baseline revision id is committed and always
    available. One extra request per changed page, and only per CHANGED page.
    """
    url = (f"{WIKI}/api.php?action=query&prop=revisions&revids={revid}"
           f"&rvprop=content&rvslots=main&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for _, page in data.get("query", {}).get("pages", {}).items():
        rev = (page.get("revisions") or [{}])[0]
        return rev.get("slots", {}).get("main", {}).get("*", "")
    return ""


def _norm(text):
    """Whitespace inside a read region cannot change what a parser extracts."""
    return re.sub(r"\s+", " ", text or "").strip()


def _char_regions(text):
    """The two things parse() reads off a character page."""
    box = {canonical(n): (t, q) for n, t, q in infobox_partners(text)}
    sec = {canonical(p): b for p, b in romantic_sections(text)}
    return box, sec


def _char_parsed(box, sec):
    """Per partner, the fields parse() would write to candidate_edges.csv.

    The episode codes are compared as a SET as well as through the season span
    infer_season() reduces them to. The span is lossy in the exact case this
    module says it cares most about: a body already citing 6x08 and 6x12 gains
    6x11, parse() writes the identical row, and a newly added citation would
    pass unmentioned. Comparing the codes costs a few more escalations and
    keeps "a citation being added" visible.
    """
    out = {}
    for partner, body in sec.items():
        qual = box.get(partner, ("", ""))[1]
        first, last = infer_season(body)
        out[partner] = (classify(qual, body), qual, first, last,
                        sorted(set(EPISODE_REF.findall(body))))
    for partner, (guess, qual) in box.items():
        out.setdefault(partner, (guess, qual, None, None, []))
    return out


def _ep_regions(text):
    m = SUMMARY.search(text)
    num = ep.EPISODE_NUM.search(text)
    return (m.group(1) if m else "").strip(), (num.group(1) if num else None)


def _people():
    """Dataset names, for the one episode-page check that needs them."""
    path = "nodes.csv"
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return [row["Character"] for row in csv.DictReader(fh)]


def _ep_parsed(summary, num, people):
    """Everything downstream reads out of an episode page.

    The named-people set is here because verify_citations asks whether a cited
    episode names both partners, and it matches on first names -- so a typo fix
    from "And" to "Andy" genuinely changes the answer. Without nodes.csv that
    check is skipped rather than faked, and the caller says so.
    """
    named = sorted(p for p in people if mentions(summary, p)) if people else None
    return (num,
            summary_len(summary) >= STUB_CHARS,
            sorted(set(EPISODE_REF.findall(summary))),
            sorted({m.lower() for m in ep.STARTS.findall(summary)}),
            named)


def classify_edit(kind, old_text, new_text, people=None):
    """Grade one page's before/after wikitext. Returns (tier, notes)."""
    if not old_text or not new_text:
        return "REVIEW", ["one of the two revisions came back empty -- "
                          "not classified rather than guessed at"]
    if old_text == new_text:
        return "CLEAR", ["net no-op: ends byte-identical to the baseline "
                         "(edited and reverted)"]

    if kind == "character":
        o_box, o_sec = _char_regions(old_text)
        n_box, n_sec = _char_regions(new_text)
        if (o_box == n_box and set(o_sec) == set(n_sec)
                and all(_norm(o_sec[k]) == _norm(n_sec[k])
                        for k in set(o_sec) & set(n_sec))):
            return "CLEAR", []
        o_par, n_par = _char_parsed(o_box, o_sec), _char_parsed(n_box, n_sec)
        if o_par == n_par:
            return "COPYEDIT", ["wording moved under ==Romantic== or in a "
                                "partner infobox field; parsed values did not"]
        notes = []
        for k in sorted(set(o_par) | set(n_par)):
            if o_par.get(k) != n_par.get(k):
                notes.append(f"{k}: {o_par.get(k)} -> {n_par.get(k)}")
        return "REVIEW", notes

    o_sum, o_num = _ep_regions(old_text)
    n_sum, n_num = _ep_regions(new_text)
    if o_num == n_num and _norm(o_sum) == _norm(n_sum):
        return "CLEAR", []
    o_par = _ep_parsed(o_sum, o_num, people)
    n_par = _ep_parsed(n_sum, n_num, people)
    if o_par == n_par:
        note = "wording moved in ==Full Summary==; parsed values did not"
        if people is None:
            note += " (no nodes.csv, so who the summary NAMES was not compared)"
        return "COPYEDIT", [note]
    labels = ["episode number", "has a usable summary", "episode codes cited",
              "relationship-start wording", "people named"]
    notes = [f"{lab}: {o!r} -> {n!r}"
             for lab, o, n in zip(labels, o_par, n_par) if o != n]
    return "REVIEW", notes


REPORT = "revwatch_report.md"


def _write_report(tiers, settled, gone, filled):
    """The graded result as a file, not only as job output.

    A failed pipeline is already an email, and that email links to artifacts.
    Until now the only artifact was drift_report.md, which covers ties and says
    nothing about edited pages -- so a run that failed BECAUSE a page needed
    reading pointed at a file whose first line was "Nothing changed on the wiki
    since the last run." The queue belongs somewhere readable without opening
    the job log.
    """
    review, copyedit, clear = tiers["REVIEW"], tiers["COPYEDIT"], tiers["CLEAR"]
    out = ["# Wiki revision report", ""]

    if review or gone:
        out += ["## Needs review", "",
                "Nothing in CI can clear these. Read the pages, then run "
                "`python revwatch.py accept` and commit revision_baseline.json.",
                ""]
        for title, kind, notes in sorted(review):
            out.append(f"- **{title}** _({kind})_")
            for note in notes:
                out.append(f"  - {note}")
        for title in sorted(gone):
            out.append(f"- **{title}** -- no longer found. Renamed? "
                       f"Check `ALIASES`.")
        out.append("")
    else:
        out += ["No page needs reading. Every edit either missed the regions "
                "the parsers read, or left what they extract unchanged.", ""]

    if filled:
        out += [f"## {len(filled)} episode page(s) gained a usable summary", "",
                "These may date a tie that could not be dated before.", ""]
        out += [f"- **{t}** -- {b} to {a} chars" for t, b, a in filled] + [""]

    out += ["## Graded automatically", "",
            f"- **{len(clear)}** cleared -- the edit missed every region the "
            f"parsers read",
            f"- **{len(copyedit)}** copyedit(s) -- landed in a read region, but "
            f"the parsed values are identical",
            f"- **{len(settled)}** already graded on an earlier run, not "
            f"re-fetched",
            ""]
    if copyedit:
        out += ["### Copyedits", ""]
        for title, kind, notes in sorted(copyedit):
            out.append(f"- **{title}** _({kind})_: {'; '.join(notes)}")
        out.append("")
    if clear:
        out += ["### Cleared", ""]
        for title, kind, notes in sorted(clear):
            out.append(f"- {title} _({kind})_" + (f" -- {notes[0]}" if notes else ""))
        out.append("")

    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def _load_cleared():
    if not os.path.exists(CLEARED):
        return {}
    try:
        with open(CLEARED, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # A corrupt optimisation file must not stop the check.
        return {}


def _save_cleared(state):
    try:
        os.makedirs(os.path.dirname(CLEARED) or ".", exist_ok=True)
        with open(CLEARED, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
            fh.write("\n")
    except OSError:
        pass


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

    # Only pages we actually ASKED about can be reported missing. The episode
    # cache is gitignored, so in CI watched() sees character pages only -- and
    # the first scheduled run under this script duly announced that all 681
    # episode pages had been deleted from the wiki. "We did not look" is not
    # "it is gone", and this is the second time that exact confusion has bitten
    # this project; the harvest outage guard exists for the same reason.
    scope = set(pages)
    changed = [t for t, r in now.items() if t in prior and prior[t] != r]
    added = [t for t in now if t not in prior]
    gone = [t for t in prior if t in scope and t not in now]
    unchecked = [t for t in prior if t not in scope]

    # Backstop for whatever the next version of that mistake looks like.
    if gone and len(gone) > max(5, len(scope) // 5):
        print(f"\nABORTING: {len(gone)} of {len(scope)} watched page(s) came back "
              f"missing. That is far more likely to be a bad watch list or an API "
              f"problem than the wiki deleting them, and reporting it as deletion "
              f"would be worse than reporting nothing.", file=sys.stderr)
        return 2

    # A page already graded harmless AT THIS EXACT REVISION is not fetched
    # again. Grading the next edit against that revision rather than against
    # the baseline is safe because the tiers are transitive: if the parsers
    # agreed across baseline -> A, and they agree across A -> B, then they
    # agree across baseline -> B.
    cleared = _load_cleared()
    settled = [t for t in changed if cleared.get(t) == now[t]]
    changed = [t for t in changed if cleared.get(t) != now[t]]
    people = _people()

    # Re-download only what moved, so the next parse reads the new text. This is
    # the entire point: the corpus stays current without re-fetching all of it.
    filled, failed = [], []
    tiers = {"CLEAR": [], "COPYEDIT": [], "REVIEW": []}

    for title in changed + added:
        kind, path = pages[title]
        # Grade against the last revision we cleared if there is one, and the
        # committed baseline otherwise. A page in `added` has neither.
        base_rev = cleared.get(title) or prior.get(title)
        try:
            old_text = _content_at(base_rev) if base_rev else ""
            new_text = refresh(title, kind, path)
        except Exception as exc:
            failed.append(f"{title} ({exc})")
            tiers["REVIEW"].append((title, kind, [f"re-download failed: {exc}"]))
            continue

        if not base_rev:
            tiers["REVIEW"].append(
                (title, kind, ["newly watched: no baseline revision to grade "
                               "it against"]))
        else:
            tier, notes = classify_edit(kind, old_text, new_text, people)
            tiers[tier].append((title, kind, notes))
            if tier != "REVIEW":
                cleared[title] = now[title]

        # An episode page that has gained a real summary may date a tie that
        # could not be dated before. The "before" length now comes from the
        # baseline REVISION rather than from a local file, so this finally
        # fires in CI too: the cache is usually cold there, which made the old
        # had_copy test false for every page every run.
        if kind == "episode" and base_rev:
            before, after = summary_len(old_text), summary_len(new_text)
            if before < STUB_CHARS <= after:
                filled.append((title, before, after))
        time.sleep(PAUSE)

    _save_cleared(cleared)
    _write_report(tiers, settled, gone, filled)

    print(f"\n  changed : {len(changed) + len(settled)}")
    print(f"  new     : {len(added)}")
    print(f"  gone    : {len(gone)}")
    print(f"  no page : {len(missing)}")
    if settled:
        print(f"  ({len(settled)} of those were graded harmless on an earlier "
              f"run and were not fetched again)")
    if unchecked:
        # Said out loud rather than silently narrowed: a watch list that has
        # quietly shrunk looks exactly like a wiki that has stopped changing.
        print(f"  NOT CHECKED: {len(unchecked)} page(s) in the baseline are not "
              f"available locally, so they were not looked at. On CI this is "
              f"normal for episode pages unless episodecache/index.csv is "
              f"present.")
    if failed:
        print(f"  re-download FAILED for {len(failed)}: {', '.join(failed[:5])}")

    print(f"\n  cleared automatically : {len(tiers['CLEAR'])}")
    print(f"  copyedits             : {len(tiers['COPYEDIT'])}")
    print(f"  NEEDS REVIEW          : {len(tiers['REVIEW'])}")

    # Loudest first: the queue is the point, the rest is the audit trail for
    # what was accepted on your behalf.
    for tier, label in (("REVIEW", "REVIEW  "),
                        ("COPYEDIT", "copyedit"),
                        ("CLEAR", "cleared ")):
        for title, kind, notes in sorted(tiers[tier]):
            print(f"    {label}  [{kind}] {title}")
            for note in notes:
                print(f"                {note}")
    for title in sorted(gone):
        print(f"    GONE      {title}  (renamed? check ALIASES)")

    if filled:
        print(f"\n{len(filled)} episode page(s) went from having NO usable summary "
              f"to having one. These may date a tie that could not be dated before:")
        for title, before, after in filled:
            print(f"    {title}   {before} -> {after} chars")

    if accept:
        with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(now, fh, indent=1, sort_keys=True)
            fh.write("\n")
        # The baseline now records every current revision, so the cleared-set
        # has nothing left to remember.
        if os.path.exists(CLEARED):
            os.remove(CLEARED)
        print(f"\n{STATE}: {len(now)} revision(s) recorded. Commit it -- that "
              f"commit is the record that these were reviewed.")
        return 0

    if tiers["REVIEW"] or gone:
        print("\nReview the pages above, then run `python revwatch.py accept` and "
              "commit revision_baseline.json. Nothing in CI can clear this.")
        return 1
    if tiers["CLEAR"] or tiers["COPYEDIT"] or settled:
        print("\nPages were edited, but nothing the dataset reads moved. Run "
              "`python revwatch.py accept` when convenient to fold these into "
              "the baseline; until then they are remembered in the cache and "
              "not re-fetched.")
        return 0
    print("\nNothing has been edited since the last check.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["check", "accept"])
    args = ap.parse_args()
    sys.exit(check(accept=args.command == "accept"))
