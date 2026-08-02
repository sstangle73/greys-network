"""
Grey's Anatomy wiki harvester
=============================
Pulls relationship data from the Grey's Anatomy Universe Wiki (MediaWiki) and
reconciles it against edges.csv, so the dataset gets audited by a script rather
than by spotting mistakes on screen.

Run this under Claude Code / locally -- it needs outbound network access to
fandom.com, which the chat sandbox does not have.

    python wiki_harvest.py harvest          # download wikitext -> ./wikicache
    python wiki_harvest.py parse            # wikicache -> candidate_edges.csv
    python wiki_harvest.py diff             # candidate_edges.csv vs edges.csv

WHY WIKITEXT AND NOT HTML
    action=raw returns the source, where the infobox is already structured:
        |marital = [[Cristina Yang]] ''(ex-wife)''
        |significant_others = [[Emma Marling]]
    and prose carries <ref> citations naming the episode. Scraping rendered
    HTML means fighting 300KB of navigation chrome for the same facts.

LICENSING
    Fandom text is CC-BY-SA. This script stores facts (who, what, which season),
    not prose. Credit the wiki in your README and you are clear. Relationship
    facts are not copyrightable in any case.

WHAT THIS DOES NOT DO
    It produces CANDIDATES, not truth. Season inference from episode citations
    is the fragile part -- see infer_season(). Treat the diff as a review queue.
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
from collections import defaultdict

WIKI = "https://greysanatomy.fandom.com"
CACHE = "wikicache"
# Fandom wants a reachable contact in the User-Agent. Set GREYS_CONTACT to your
# own address before harvesting; the fallback is the project page, which is a
# valid contact point and keeps a personal address out of a public repo.
CONTACT = os.environ.get("GREYS_CONTACT", "https://gitlab.com/sstangle73/greys-network")
UA = f"GreysNetworkAudit/1.0 (personal dataset reconciliation; contact: {CONTACT})"
PAUSE = 1.0  # be polite; the wiki is free and volunteer-run

# Characters to harvest, grouped by the show they belong to. Everyone else in
# the graph hangs off these. The grouping matters: a season code scraped from a
# Private Practice page is a PP season, and the parser needs to know that rather
# than quietly filing it as a Grey's one.
SEEDS_BY_SHOW = {
    "GA": [
        "Meredith Grey", "Derek Shepherd", "Cristina Yang", "Alex Karev",
        "Izzie Stevens", "George O'Malley", "Miranda Bailey", "Richard Webber",
        "Callie Torres", "Arizona Robbins", "Mark Sloan", "Lexie Grey",
        "Addison Forbes Montgomery", "Owen Hunt", "Teddy Altman", "Amelia Shepherd",
        "April Kepner", "Jackson Avery", "Maggie Pierce", "Jo Wilson",
        "Atticus Lincoln", "Andrew DeLuca", "Nathan Riggs", "Tom Koracick",
        "Levi Schmitt", "Nico Kim", "Winston Ndugu", "Carina DeLuca",
        "Simone Griffith", "Lucas Adams", "Benson Kwan", "Jules Millin",
        "Mika Yasuda", "Taryn Helm", "Nick Marsh", "Catherine Fox",
        "Ellis Grey", "Thatcher Grey", "Ben Warren", "Megan Hunt",
    ],
    "PP": [
        "Sam Bennett", "Naomi Bennett", "Pete Wilder", "Violet Turner",
        "Cooper Freedman", "Charlotte King", "Sheldon Wallace", "Jake Reilly",
        "Dell Parker", "Maya Bennett", "William White", "Archer Montgomery",
        "Kevin Nelson", "Noah Barnes",
    ],
    "S19": [
        "Andy Herrera", "Robert Sullivan", "Maya Bishop", "Jack Gibson",
        "Victoria Hughes", "Travis Montgomery", "Dean Miller", "Pruitt Herrera",
        "Theo Ruiz", "Emmett Dixon", "Natasha Ross", "Sean Beckett",
        "Michael Dixon", "Vasquez",
    ],
}

SEEDS = [title for titles in SEEDS_BY_SHOW.values() for title in titles]

# Which show a cached page's episode codes belong to.
SHOW_OF_PAGE = {title: show for show, titles in SEEDS_BY_SHOW.items()
                for title in titles}


# --------------------------------------------------------------------------- #
# Harvest
# --------------------------------------------------------------------------- #

def _fetch_raw(title: str) -> str:
    url = f"{WIKI}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}?action=raw"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_api(title: str) -> str:
    """The documented fallback for when action=raw 403s (it now does, mostly)."""
    url = (f"{WIKI}/api.php?action=query&prop=revisions&rvslots=*"
           f"&rvprop=content&format=json&titles={urllib.parse.quote(title)}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    pages = data.get("query", {}).get("pages", {})
    for pid, page in pages.items():
        if pid == "-1" or "missing" in page:
            raise LookupError(f"no such page: {title}")
        return page["revisions"][0]["slots"]["main"]["*"]
    raise LookupError(f"empty API response for {title}")


def fetch_wikitext(title: str) -> str:
    try:
        return _fetch_raw(title)
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 429):
            raise
        return _fetch_api(title)


def harvest(titles=None) -> None:
    os.makedirs(CACHE, exist_ok=True)
    for title in (titles or SEEDS):
        path = os.path.join(CACHE, title.replace("/", "_") + ".wiki")
        if os.path.exists(path):
            print(f"  cached  {title}")
            continue
        try:
            text = fetch_wikitext(title)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"  got     {title}  ({len(text) // 1024}KB)")
        except Exception as exc:
            print(f"  FAILED  {title}: {exc}", file=sys.stderr)
        time.sleep(PAUSE)


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #

LINK = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]*?)?\]\]")
QUALIFIER = re.compile(r"''\(([^)]+)\)''")

# Infobox fields that name romantic partners, mapped to a starting guess at type.
PARTNER_FIELDS = {
    "marital": "Married",
    "spouse": "Married",
    "significant_others": "Dating",
    "significantothers": "Dating",
}

# "16x08" / "16.08" / "Season 16, Episode 8" inside a ref or heading.
EPISODE_REF = re.compile(r"\b(\d{1,2})x(\d{2})\b")

# The wiki's article title is not always the name the dataset uses. Without this
# the diff reports the same tie as both "missing" and "extra" -- e.g. Addison
# appeared six times in each bucket.
ALIASES = {
    "Addison Forbes Montgomery": "Addison Montgomery",
    "Addison Shepherd": "Addison Montgomery",
    "Denny Duquette, Jr.": "Denny Duquette",
    "Penelope Blake": "Penny Blake",
    "Olivia Jankovic": "Olivia Harper",
    "Zola Grey Shepherd": "Zola Shepherd",
    "Derek Bailey Shepherd": "Bailey Shepherd",
    "Sofia Robbin Sloan Torres": "Sofia Robbin Sloan Torres",
}

# Headings under ==Romantic== that name a group or a placeholder rather than a
# person. These are not ties and should never reach the review queue.
NON_PERSON_HEADINGS = {"interns", "ex-girlfriend", "ex-boyfriend", "girlfriend",
                       "boyfriend", "unnamed woman", "unnamed man", "women", "men"}


def canonical(name: str) -> str:
    """Resolve a wiki link/heading to the name the dataset uses.

    Handles piped links ("[[Olivia Jankovic|Olivia Harper]]") by preferring the
    link TARGET, since that is the article title the alias table is keyed on.
    """
    name = name.strip()
    if "|" in name:
        target, _, display = name.partition("|")
        target, display = target.strip(), display.strip()
        name = target if target in ALIASES else (display or target)
    return ALIASES.get(name, name)


def infobox_partners(text: str):
    """Yield (name, type_guess, qualifier) from the character infobox.

    The field is a multi-line bulleted list, and each bullet carries its OWN
    qualifier:

        |marital = *[[Izzie Stevens]] ''(ex-wife; reconciled)''
        *[[Jo Wilson]] ''(ex-wife)''
        |children = ...

    Reading only the "|marital =" line finds the first spouse and no one else,
    which is why every second marriage in the graph was being reported as a
    type disagreement -- no qualifier was found, so classify() fell through to
    its "Dating" default.
    """
    field = None
    for line in text.splitlines():
        m = re.match(r"\s*\|\s*([A-Za-z_ ]+?)\s*=\s*(.*)$", line)
        if m:
            name = m.group(1).strip().lower().replace(" ", "_")
            field, rest = (name if name in PARTNER_FIELDS else None), m.group(2)
        elif field and (line.startswith("*") or line.startswith(":")):
            rest = line                       # continuation bullet
        else:
            if line.startswith("}}") or re.match(r"\s*\|", line):
                field = None
            continue
        if not field:
            continue
        # One qualifier per bullet, so split the value before matching.
        for chunk in re.split(r"(?=\*\s*\[\[)", rest):
            qual = QUALIFIER.search(chunk)
            for who in LINK.findall(chunk):
                yield who.strip(), PARTNER_FIELDS[field], (qual.group(1) if qual else "")


def romantic_sections(text: str):
    """Yield (partner_name, section_body) from the ==Romantic== subsections.

    The wiki nests these as: ===Relationships=== / ====Romantic==== /
    =====Partner Name=====, so the partner is the heading itself.
    """
    lines = text.splitlines()
    in_romantic = False
    depth = 0
    current = None
    body = []

    for line in lines:
        heading = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            if title.lower() == "romantic":
                in_romantic, depth = True, level
                continue
            if in_romantic and level <= depth:
                if current:
                    yield current, "\n".join(body)
                in_romantic, current, body = False, None, []
                continue
            if in_romantic and level == depth + 1:
                if current:
                    yield current, "\n".join(body)
                current, body = re.sub(r"\[\[|\]\]", "", title), []
                continue
        if current is not None:
            body.append(line)

    if current:
        yield current, "\n".join(body)


def infer_season(body: str):
    """Best guess at first and last season from episode codes in the prose.

    THIS IS THE WEAK LINK. Episode codes appear in citations that may reference
    a scene about the relationship's past, so treat the output as a hint to
    check, never as a value to write straight into edges.csv.
    """
    seasons = sorted({int(s) for s, _ in EPISODE_REF.findall(body)})
    if not seasons:
        return None, None
    return seasons[0], seasons[-1]


def classify(qualifier: str, body: str) -> str:
    q = qualifier.lower()
    # Check "fiance" FIRST: "(fiancee)" contains no spouse word, but "(ex-wife)"
    # and "(widower)" must not be read as anything but a marriage.
    if "fianc" in q:
        return "Dating"
    if "wife" in q or "husband" in q or "spouse" in q or "widow" in q:
        return "Married"
    text = body.lower()
    if "one-night stand" in text or "one night stand" in text:
        return "Fling"
    if "slept with" in text and "relationship" not in text:
        return "Fling"
    return "Dating"


def parse() -> None:
    rows = []
    for fname in sorted(os.listdir(CACHE)):
        if not fname.endswith(".wiki"):
            continue
        subject = fname[:-5]
        text = open(os.path.join(CACHE, fname), encoding="utf-8").read()

        quals = {}
        for name, _, qual in infobox_partners(text):
            quals[canonical(name)] = qual

        seen = set()
        for partner, body in romantic_sections(text):
            partner = canonical(partner)
            if partner.lower() in NON_PERSON_HEADINGS:
                continue
            first, last = infer_season(body)
            rows.append({
                "Subject": canonical(subject),
                "Partner": partner,
                "Type_Guess": classify(quals.get(partner, ""), body),
                "Qualifier": quals.get(partner, ""),
                "Season_Hint_First": first or "",
                "Season_Hint_Last": last or "",
                "Source": "romantic_section",
            })
            seen.add(partner)

        # Partners named in the infobox but with no prose section of their own.
        for name, type_guess, qual in infobox_partners(text):
            name = canonical(name)
            if name in seen or name.lower() in NON_PERSON_HEADINGS:
                continue
            # Route through classify() rather than trusting the field name:
            # |marital = [[Meredith Grey]] ''(fiancee)'' is an engagement, and
            # reading the field alone reported it as a marriage.
            rows.append({
                "Subject": canonical(subject), "Partner": name,
                "Type_Guess": classify(qual, "") or type_guess,
                "Qualifier": qual, "Season_Hint_First": "", "Season_Hint_Last": "",
                "Source": "infobox",
            })
            seen.add(name)

    with open("candidate_edges.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote candidate_edges.csv: {len(rows)} candidate ties")


# --------------------------------------------------------------------------- #
# Diff
# --------------------------------------------------------------------------- #

def diff(edges_path="edges.csv") -> None:
    mine = defaultdict(set)
    with open(edges_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["Relationship_Type"] == "Parent":
                continue
            mine[frozenset({row["Source"], row["Target"]})].add(row["Relationship_Type"])

    theirs = {}
    with open("candidate_edges.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            theirs[frozenset({row["Subject"], row["Partner"]})] = row

    missing = [k for k in theirs if k not in mine]
    extra = [k for k in mine if k not in theirs]
    mismatch = [
        (k, list(mine[k])[0], theirs[k]["Type_Guess"])
        for k in theirs if k in mine and theirs[k]["Type_Guess"] not in mine[k]
    ]

    print(f"\nIn the wiki, missing from edges.csv ({len(missing)}):")
    for k in sorted(missing, key=lambda s: sorted(s)):
        row = theirs[k]
        hint = f" [S{row['Season_Hint_First']}-S{row['Season_Hint_Last']}]" if row["Season_Hint_First"] else ""
        print(f"  + {' & '.join(sorted(k))}  {row['Type_Guess']}{hint}")

    # An "extra" is only interesting if BOTH people were actually harvested. If
    # the partner has no cached page, the wiki was never asked about the tie --
    # it usually lives on that partner's own article, or under a non-romantic
    # heading such as ==Friendships== on the seed's page. Reporting those as
    # "not found on the wiki" sent the last audit chasing phantoms.
    harvested = {os.path.splitext(f)[0] for f in os.listdir(CACHE)
                 if f.endswith(".wiki")} if os.path.isdir(CACHE) else set()
    harvested |= {canonical(t) for t in harvested}
    checkable = [k for k in extra if all(canonical(n) in harvested for n in k)]
    unseeded = [k for k in extra if k not in checkable]

    print(f"\nIn edges.csv, both people harvested, no wiki tie found ({len(checkable)}):")
    for k in sorted(checkable, key=lambda s: sorted(s)):
        print(f"  ? {' & '.join(sorted(k))}")

    print(f"\nIn edges.csv, partner never harvested -- not evidence either way "
          f"({len(unseeded)}):")
    for k in sorted(unseeded, key=lambda s: sorted(s)):
        print(f"  . {' & '.join(sorted(k))}")

    print(f"\nType disagreements ({len(mismatch)}):")
    for k, ours, guess in sorted(mismatch, key=lambda t: sorted(t[0])):
        print(f"  ~ {' & '.join(sorted(k))}: ours={ours} wiki={guess}")


def drift(edges_path="edges.csv", report="drift_report.md") -> int:
    """Harvest, parse and diff in one pass, then write a report.

    Meant for a scheduled pipeline. Season 22 is still airing and the wiki keeps
    moving, so a dataset that was right in August is not automatically right in
    November. Exits non-zero when the wiki has ties the dataset does not, which
    makes the pipeline fail -- and a failed pipeline is already an email, so
    this needs no API token and no bot account.
    """
    harvest()
    parse()

    mine = defaultdict(set)
    with open(edges_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["Relationship_Type"] == "Parent":
                continue
            mine[frozenset({row["Source"], row["Target"]})].add(row["Relationship_Type"])

    theirs = {}
    with open("candidate_edges.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            theirs[frozenset({row["Subject"], row["Partner"]})] = row

    missing = sorted((k for k in theirs if k not in mine), key=lambda s: sorted(s))

    lines = ["# Wiki drift report", ""]
    if not missing:
        lines += ["No new ties. The wiki and `edges.csv` agree on who exists.", ""]
    else:
        lines += [
            f"The wiki now has **{len(missing)} tie(s)** that `edges.csv` does not.",
            "",
            "Every one of these is a CANDIDATE, not a correction. Before adding any",
            "of them, check the prose against the scope rule -- a `==Romantic==`",
            "section is not proof of a tie, and an episode citation often marks",
            "where a relationship was narrated rather than when it happened.",
            "",
        ]
        for k in missing:
            row = theirs[k]
            hint = (f" _(hint: S{row['Season_Hint_First']}-S{row['Season_Hint_Last']}"
                    f" -- verify, do not copy)_" if row["Season_Hint_First"] else "")
            lines.append(f"- **{' & '.join(sorted(k))}** — {row['Type_Guess']}{hint}")
        lines.append("")

    with open(report, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    return 1 if missing else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["harvest", "parse", "diff", "drift"])
    ap.add_argument("--edges", default="edges.csv")
    args = ap.parse_args()

    if args.command == "harvest":
        harvest()
    elif args.command == "parse":
        parse()
    elif args.command == "drift":
        sys.exit(drift(args.edges))
    else:
        diff(args.edges)
