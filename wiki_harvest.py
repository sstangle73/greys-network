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
    python wiki_harvest.py drift            # scheduled check; fails if the wiki moved
    python wiki_harvest.py accept           # record the wiki as reviewed, then COMMIT

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
        # "Vasquez" 404s -- the page is her full name, and the seed had been
        # failing on every harvest since it was written.
        "Michael Dixon", "Eva Vasquez",
    ],
}

BASE_SEEDS = [title for titles in SEEDS_BY_SHOW.values() for title in titles]


def seeds(edges_path="edges.csv"):
    """The hand-written hubs, plus everyone already in a romantic tie.

    The hand list alone was 68 pages against 187 people in the graph. That
    sounds worse than it measured -- 157 of 158 ties had a seed on one side, so
    a change would surface through that side's page -- but the one exception is
    the whole argument: Nicole Herman & Graham Maddox, neither of them a hub,
    invisible to the check. It is also the tie a character-page audit once
    recommended DELETING because it "appears nowhere in the cache". It was not
    in the cache because nobody had ever fetched either page.

    So the seed list is derived from the data it is meant to police. A tie
    between two recurring characters is exactly the kind the hand list misses,
    and exactly the kind nobody thinks to add to a hand list.

    Falls back to the hand list if edges.csv is not there yet (a fresh clone
    harvests before it can build).
    """
    out = list(BASE_SEEDS)
    seen = set(out)
    try:
        with open(edges_path, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if r["Relationship_Type"] != "Parent"]
    except OSError:
        return out
    # The dataset stores short forms; the wiki is keyed on article titles, so
    # go back through the alias table rather than requesting a page that 404s.
    #
    # Inverting ALIASES is ambiguous -- two titles map to Addison, and naively
    # taking the last one asked for "Addison Shepherd", a redirect that 404s on
    # action=raw, for someone already in the hand list under her real title.
    # So track who is covered by DATASET NAME, not by page title.
    to_title = {}
    for title, name in ALIASES.items():
        to_title.setdefault(name, title)
    covered = {ALIASES.get(t, t) for t in BASE_SEEDS}
    for row in rows:
        for name in (row["Source"], row["Target"]):
            if name in covered:
                continue
            covered.add(name)
            title = to_title.get(name, name)
            if title not in seen:
                seen.add(title)
                out.append(title)
    return out


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
        if exc.code == 404:
            # Distinct from a transport failure, and the callers must not
            # conflate them: "this article does not exist" is a permanent fact
            # about our seed list, while "the request failed" is about today.
            raise LookupError(f"no such page: {title}") from exc
        if exc.code not in (403, 429):
            raise
        return _fetch_api(title)


def harvest(titles=None, max_age_days=None):
    """Download the seed pages, skipping ones already cached.

    max_age_days re-fetches anything older than that; 0 means always.

    THE DRIFT CHECK MUST PASS THIS. Skip-if-present is right for local work --
    it is what makes re-running parse() free -- and it is catastrophic for a
    scheduled check, because a restored CI cache means nothing is ever
    re-downloaded and the job re-parses identical bytes forever. The first
    scheduled run did exactly that: 68 pages served from cache, 0 fetched, and
    a confident "Nothing changed on the wiki since the last run". A green light
    wired to nothing is worse than no light at all.

    Returns (fetched, reused, missing, failed). `missing` is 404s -- articles
    that do not exist, which is a fact about the seed list and not about the
    network. Keeping them apart matters: once the seeds are derived from the
    data, a batch of unknown article titles would otherwise look exactly like
    the wiki being down.
    """
    os.makedirs(CACHE, exist_ok=True)
    fetched, reused, missing, failed = 0, 0, [], []
    cutoff = None if max_age_days is None else time.time() - max_age_days * 86400
    for title in (titles if titles is not None else seeds()):
        path = os.path.join(CACHE, title.replace("/", "_") + ".wiki")
        if os.path.exists(path) and (cutoff is None or os.path.getmtime(path) > cutoff):
            print(f"  cached  {title}")
            reused += 1
            continue
        try:
            text = fetch_wikitext(title)
            # Written only on success, so a failed fetch leaves the previous
            # copy in place. Stale is a better failure than absent: a missing
            # page looks like every tie on it was deleted.
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            fetched += 1
            print(f"  got     {title}  ({len(text) // 1024}KB)")
        except LookupError as exc:
            missing.append(title)
            print(f"  NO PAGE {title}", file=sys.stderr)
        except Exception as exc:
            failed.append(title)
            print(f"  FAILED  {title}: {exc}", file=sys.stderr)
        time.sleep(PAUSE)
    return fetched, reused, missing, failed


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
    # The wiki puts the on-screen nickname inside the article title, so this
    # came back as a brand-new person who happened to be dating everyone
    # Victoria Hughes dates.
    'Victoria "Vic" Hughes': "Victoria Hughes",
    "Allison Robin Brown": "Allison Brown",
    # Two different men called Allan. This one is Adele's fellow resident at
    # Roseridge; plain "Allan" is Violet Turner's ex, who is married to Cami
    # Davis and appears in Private Practice. Without this they merge.
    "Allan (Grey's Anatomy)": "Allan (Roseridge)",
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


# Committed to the repo, NOT kept in the CI cache.
#
# The first attempt put this in wikicache/ and let CI's cache carry it between
# pipelines. It does not: the self-hosted runner uses the docker executor with
# a local cache volume, so a run can create the cache and the next run can be
# told "cache file does not exist". Two consecutive scheduled runs proved it.
#
# Committing it is better than making the cache work, for a reason that has
# nothing to do with reliability: reviewing wiki drift is a judgement call, and
# a judgement call belongs in a diff where someone can see it. Clearing the
# alert is now an explicit act -- `python wiki_harvest.py accept`, then commit
# the change -- rather than a side effect of a job having run. Still no token,
# still no bot account.
STATE = "drift_baseline.json"

# Ties the wiki has, that this dataset leaves out ON PURPOSE. Without this the
# first real run reported thirty-odd "candidates", most of them decisions that
# had already been made and written down -- and a list where the known items
# outnumber the new ones is a list nobody reads to the bottom of.
#
# Every entry needs a reason, because the point is that someone already thought
# about it. If you disagree with one, delete the line and it comes back.
EXCLUDED = {
    # A partner who never appears in a present-day storyline. Same rule Dana
    # used, and the reason CLAUDE.md gives for each of these.
    frozenset({"Tom Koracick", "Dana Hamilton"}): "never in a present-day storyline",
    frozenset({"Teddy Altman", "Allison Brown"}): "never in a present-day storyline",
    frozenset({"Travis Montgomery", "Michael Williams"}): "never in a present-day storyline",
    frozenset({"Travis Montgomery", "Michael Cooper Williams"}): "duplicate of Michael Williams",
    frozenset({"Robert Sullivan", "Claire Sullivan"}): "never in a present-day storyline",
    frozenset({"Pete Wilder", "Anna Wilder"}): "never in a present-day storyline",
    # Pre-series marriages with no in-show dates at all, left out rather than
    # given a degenerate one-episode span.
    frozenset({"Charlotte King", "Billy Douglas"}): "pre-series, no in-show dates",
    frozenset({"Catherine Fox", "Robert Avery"}): "pre-series, no in-show dates",
    # Removed during the audit for failing the scope rule: no sex, and no more
    # than one date.
    frozenset({"Alex Karev", "Reed Adamson"}): "fails the scope rule -- propositioned, not consummated",
    frozenset({"April Kepner", "Robert Stark"}): "fails the scope rule",
    frozenset({"Amelia Shepherd", "Cass Beckman"}): "fails the scope rule",
    frozenset({"Lucas Adams", "Katie Rogers"}): "fails the scope rule",
}

# Not people. The parser picks these out of infobox rows that describe a partner
# rather than naming one, and they can never resolve to a character page.
PLACEHOLDERS = {"Others", "Exes", "Unnamed", "Unknown", "Wrecking Ball"}

# A generic role where a name should be. The wiki uses these in infobox rows
# for partners it will not name, and they arrive looking exactly like people.
ROLE_WORDS = re.compile(
    r"^(ex[- ])?(wife|husband|fianc|girlfriend|boyfriend|partner|spouse|"
    r"past girlfriend|past boyfriend|high school (girl|boy)friend)",
    re.IGNORECASE)


def _is_placeholder(pair) -> bool:
    for n in pair:
        if n in PLACEHOLDERS or " and " in n or ROLE_WORDS.match(n):
            return True
    return False


# A disambiguation suffix means the wiki has TWO people with one name, which is
# the opposite of a placeholder -- it is the wiki being precise. Filtering these
# as noise was a mistake caught immediately: "Allan (Grey's Anatomy)" is Adele
# Webber's companion at Roseridge, an entirely different person from "Allan",
# Violet Turner's ex. canonical() was collapsing both to "Allan" and merging two
# people into one node, and filtering the suffixed form would have hidden the
# evidence of it. Give them an ALIASES entry with a readable short form instead.


def _key(pair) -> str:
    """A frozenset is unordered and unserialisable; JSON needs a stable string."""
    return " & ".join(sorted(pair))


def _load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # A missing or corrupt snapshot must not take the run down -- the report
        # just says "first run" and rebuilds it.
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(CACHE, exist_ok=True)
    with open(STATE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)


def drift(edges_path="edges.csv", report="drift_report.md", refresh=True) -> int:
    """Harvest, parse and diff in one pass, then write a report.

    Meant for a scheduled pipeline. Season 22 is still airing and the wiki keeps
    moving, so a dataset that was right in August is not automatically right in
    November. Exits non-zero when the wiki has ties the dataset does not, which
    makes the pipeline fail -- and a failed pipeline is already an email, so
    this needs no API token and no bot account.
    """
    # Always re-fetch. See harvest(): a restored cache otherwise means this
    # diffs the same bytes against themselves week after week.
    all_seeds = seeds(edges_path)
    # refresh=False is for the pipeline, where revwatch.py has already asked the
    # API which pages moved and re-downloaded exactly those. Re-fetching all 155
    # again here would be the same 2.6 minutes of requests the revision check
    # exists to avoid.
    fetched, reused, missing, failed = harvest(
        all_seeds, max_age_days=0 if refresh else None)
    # A wiki outage must not read as mass deletion. If a chunk of the seeds did
    # not come back, every tie on those pages would vanish from the parse and
    # the report would claim they were removed -- so refuse to diff at all.
    # Only TRANSPORT failures count here; a 404 is a naming problem, reported
    # further down, and must not be able to mask an outage or fake one.
    if failed and len(failed) > max(3, len(all_seeds) // 5):
        print(f"ABORTING: {len(failed)} of {len(all_seeds)} pages failed to fetch "
              f"({', '.join(failed[:5])}...). Diffing now would report every tie "
              f"on them as removed.", file=sys.stderr)
        return 2
    if failed:
        print(f"NOTE: {len(failed)} page(s) failed and are being read from an "
              f"older copy: {', '.join(failed)}")
    # A 404 means the dataset's name for someone is not the wiki's article
    # title. Harmless to the diff -- that person simply is not watched -- but
    # it is a silent hole unless it is said out loud, so it goes in the report
    # with the fix named: add them to ALIASES.
    if missing:
        print(f"NOTE: {len(missing)} name(s) have no wiki article and are not "
              f"being watched. Add an ALIASES entry if the article exists under "
              f"another title: {', '.join(missing)}")
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

    all_missing = [k for k in theirs if k not in mine]
    known = [k for k in all_missing if k in EXCLUDED]
    junk = [k for k in all_missing if k not in EXCLUDED and _is_placeholder(k)]
    missing = sorted((k for k in all_missing if k not in EXCLUDED
                      and not _is_placeholder(k)), key=lambda s: sorted(s))

    # A standing difference is not news. On the second run the report said the
    # same thing as the first, so "the pipeline failed" stopped meaning "the wiki
    # moved" and started meaning "it is still Tuesday". The snapshot is what
    # turns this from a status into an alert: it can say what changed SINCE LAST
    # TIME, which is the only part anyone needs to act on.
    #
    # It lives in the cache directory on purpose -- CI already caches that, so
    # the memory persists between pipelines without a commit or an artifact.
    prior = _load_state()
    # Excluded ties are kept out of the snapshot as well, so removing a line
    # from EXCLUDED makes that tie reappear as NEW -- which is what you want if
    # you have changed your mind about it.
    now = {_key(k): theirs[k]["Type_Guess"] for k in theirs
           if k not in EXCLUDED and not _is_placeholder(k)}
    fresh = sorted(k for k in now if k not in prior)
    retyped = sorted(k for k in now if k in prior and prior[k] != now[k])
    gone = sorted(k for k in prior if k not in now)

    lines = ["# Wiki drift report", ""]

    if prior and (fresh or retyped or gone):
        lines += [f"## Changed since the last run", ""]
        for k in fresh:
            lines.append(f"- **NEW on the wiki**: {k} — {now[k]}")
        for k in retyped:
            lines.append(f"- **TYPE CHANGED**: {k} — was {prior[k]}, now {now[k]}")
        for k in gone:
            # Usually a rename or a page reorganisation rather than a deletion,
            # but it is exactly the case where our alias table goes stale.
            lines.append(f"- **NO LONGER FOUND**: {k} — was {prior[k]}. "
                         f"Check for a rename, and check `ALIASES`.")
        lines.append("")
    elif prior:
        lines += ["Nothing changed on the wiki since the last run.", ""]
    else:
        lines += ["_No `drift_baseline.json` in the repo, so there is nothing "
                  "to compare against. Run `python wiki_harvest.py accept` and "
                  "commit the result to set the baseline._", ""]

    lines += ["## Standing candidates", ""]
    if not missing:
        lines += ["No new ties. The wiki and `edges.csv` agree on who exists.", ""]
    else:
        lines += [
            f"The wiki has **{len(missing)} tie(s)** that `edges.csv` does not.",
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
            mark = " **[new]**" if _key(k) in fresh else ""
            lines.append(f"- **{' & '.join(sorted(k))}**{mark} — {row['Type_Guess']}{hint}")
        lines.append("")

    # Say what was filtered out. A report that quietly drops things reads as
    # "the wiki agrees with us" when what it means is "we stopped looking".
    if known or junk:
        lines += ["## Filtered out", ""]
        if known:
            lines.append(f"{len(known)} tie(s) the wiki has and this dataset "
                         f"leaves out deliberately:")
            for k in sorted(known, key=lambda s: sorted(s)):
                lines.append(f"- {' & '.join(sorted(k))} — _{EXCLUDED[k]}_")
            lines.append("")
        if junk:
            lines.append(f"{len(junk)} parsed as a description rather than a "
                         f"person, so they can never resolve to a character page:")
            for k in sorted(junk, key=lambda s: sorted(s)):
                lines.append(f"- {' & '.join(sorted(k))}")
            lines.append("")

    with open(report, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))

    # Fail only on genuine movement. A standing candidate that has already been
    # looked at and rejected must not fail every scheduled run forever -- an
    # alert that always fires is one nobody reads.
    if prior and not (fresh or retyped or gone):
        return 0
    if prior:
        print("\nReview the changes above. If they are all understood, run "
              "`python wiki_harvest.py accept` and commit drift_baseline.json "
              "to clear this. Nothing in CI can clear it -- a job that could "
              "silence its own alarm would make the alarm meaningless.")
    return 1


def accept(edges_path="edges.csv") -> int:
    """Record the wiki's current state as reviewed.

    Run this after reading a drift report and deciding the changes are
    understood, then commit drift_baseline.json. That commit is the record of
    the decision -- which is the point. Nothing in CI writes this file; if a job
    could clear its own alert, the alert would mean nothing.
    """
    fetched, reused, missing, failed = harvest(seeds(edges_path), max_age_days=0)
    if failed:
        print(f"REFUSING to set a baseline: {len(failed)} page(s) failed to "
              f"fetch ({', '.join(failed)}). A baseline recorded from an "
              f"incomplete harvest would suppress real alerts later.",
              file=sys.stderr)
        return 2
    parse()
    theirs = {}
    with open("candidate_edges.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = frozenset({row["Subject"], row["Partner"]})
            if key in EXCLUDED or _is_placeholder(key):
                continue
            theirs[_key(key)] = row["Type_Guess"]
    before = _load_state()
    _save_state(theirs)
    added = len(set(theirs) - set(before))
    removed = len(set(before) - set(theirs))
    print(f"{STATE}: {len(theirs)} ties recorded "
          f"(+{added} / -{removed} vs the previous baseline)")
    print("Commit it -- that commit is the record that these were reviewed.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command",
                    choices=["harvest", "parse", "diff", "drift", "accept"])
    ap.add_argument("--edges", default="edges.csv")
    ap.add_argument("--no-refresh", action="store_true",
                    help="use the cache as-is; revwatch.py has already "
                         "refreshed whatever changed")
    args = ap.parse_args()

    if args.command == "harvest":
        harvest()
    elif args.command == "parse":
        parse()
    elif args.command == "drift":
        sys.exit(drift(args.edges, refresh=not args.no_refresh))
    elif args.command == "accept":
        sys.exit(accept(args.edges))
    else:
        diff(args.edges)
