"""Apply verification results to audit_tracker.csv.

Reconciliation is done by hand against the wiki; this just keeps the tracker in
step with greys_network.py so the Verified column stays trustworthy. Rows are
matched on the unordered pair, because the tracker and the edge list do not
always agree on which name is Source.

    python audit_apply.py verify "Meredith Grey" "Nathan Riggs" ...

Every named pair is re-read from edges.csv (so the tracker cannot drift from the
source of truth) and marked Verified=yes.
"""

import csv
import os
import sys

TRACKER = "audit_tracker.csv"
EDGES = "edges.csv"
CITATIONS = "citations.csv"


def load_citations():
    """Evidence per tie, keyed by the unordered pair.

    Kept in its own file rather than in greys_network.py so the reasoning is
    reviewable next to the data without wading through Python literals. A tie
    with no row here is not a failure -- it means nobody has recorded why yet,
    and the tracker says so instead of implying the value is sourced.
    """
    if not os.path.exists(CITATIONS):
        return {}
    with open(CITATIONS, encoding="utf-8") as fh:
        return {frozenset({r["Source"], r["Target"]}): r
                for r in csv.DictReader(fh)}


def load_edges():
    out = {}
    with open(EDGES, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["Relationship_Type"] == "Parent":
                continue
            out[frozenset({row["Source"], row["Target"]})] = row
    return out


def num(value):
    """edges.csv writes ints; the tracker has historically used 3.0-style floats."""
    return "" if value in ("", None) else f"{float(value):.1f}"


def main(names):
    if len(names) % 2:
        sys.exit("expects pairs of names")
    wanted = {frozenset({names[i], names[i + 1]}) for i in range(0, len(names), 2)}

    edges = load_edges()
    unknown = wanted - set(edges)
    if unknown:
        sys.exit(f"not in edges.csv: {[sorted(k) for k in unknown]}")

    with open(TRACKER, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames, list(reader)

    # A tie the reconciliation removed from greys_network.py should not linger in
    # the tracker as a permanently unverifiable row.
    dropped = [r for r in rows
               if frozenset({r["Source"], r["Target"]}) not in edges]
    rows = [r for r in rows if r not in dropped]

    # Ties the reconciliation ADDED are not in the tracker yet; append them.
    tracked = {frozenset({r["Source"], r["Target"]}) for r in rows}
    for key in wanted - tracked:
        edge = edges[key]
        rows.append({"Source": edge["Source"], "Target": edge["Target"],
                     "Verified": "no", **{f: "" for f in fields
                                          if f not in ("Source", "Target", "Verified")}})

    seen, changed = set(), []
    for row in rows:
        key = frozenset({row["Source"], row["Target"]})
        if key not in wanted:
            continue
        seen.add(key)
        edge = edges[key]
        before = dict(row)
        row["Relationship_Type"] = edge["Relationship_Type"]
        row["First_Season"] = edge["First_Season"]
        row["First_Episode"] = edge["First_Episode"]
        row["Last_Season"] = num(edge["Last_Season"])
        row["Last_Episode"] = num(edge["Last_Episode"])
        row["Married_Season"] = num(edge["Married_Season"])
        row["Outcome"] = edge["Outcome"]
        row["Verified"] = "yes"
        if any(before[f] != row[f] for f in fields):
            changed.append((sorted(key), {f: (before[f], row[f])
                                          for f in fields if before[f] != row[f]}))

    missing = wanted - seen
    if missing:
        sys.exit(f"not in {TRACKER}: {[sorted(k) for k in missing]}")

    with open(TRACKER, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    for row in dropped:
        print(f"  DROPPED {row['Source']} & {row['Target']} (no longer in edges.csv)")
    for pair, diffs in changed:
        print(f"  {' & '.join(pair)}")
        for field, (was, now) in diffs.items():
            print(f"      {field}: {was!r} -> {now!r}")

    done = sum(1 for r in rows if r["Verified"] == "yes")
    print(f"\n{TRACKER}: {done} verified, {len(rows) - done} to go")


def sync(verify_shows=()):
    """Add every romantic edge missing from the tracker.

    New rows land as Verified=no unless their show is named in verify_shows --
    used when a whole show has just been audited in one pass.
    """
    edges = load_edges()
    with open(TRACKER, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames, list(reader)

    tracked = {frozenset({r["Source"], r["Target"]}) for r in rows}
    added = 0
    for key, edge in edges.items():
        if key in tracked:
            continue
        rows.append({
            "Source": edge["Source"], "Target": edge["Target"],
            "Relationship_Type": edge["Relationship_Type"],
            "First_Season": edge["First_Season"],
            "First_Episode": edge["First_Episode"],
            "Last_Season": num(edge["Last_Season"]),
            "Last_Episode": num(edge["Last_Episode"]),
            "Married_Season": num(edge["Married_Season"]),
            "Outcome": edge["Outcome"],
            "Verified": "yes" if edge.get("Show") in verify_shows else "no",
        })
        added += 1

    with open(TRACKER, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    done = sum(1 for r in rows if r["Verified"] == "yes")
    print(f"added {added} ties; {TRACKER}: {done} verified, {len(rows) - done} to go")


def check():
    """Fail if the tracker no longer matches edges.csv.

    `verify` refreshes only the pairs you name and `sync` only appends, so a
    tracker can be perfectly valid on the day it is written and quietly wrong
    forever after. This one had drifted for thirty commits: four rows for ties
    that had been deleted, and almost every episode still reading 1 from before
    the episode numbers were filled in. The Verified column stayed true the
    whole time, which is exactly what made it hard to notice -- the file looked
    finished.

    Cheap enough to run on every build, so the answer is never "nobody checked".
    """
    edges = load_edges()
    with open(TRACKER, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    problems = []
    tracked = set()
    for row in rows:
        key = frozenset({row["Source"], row["Target"]})
        tracked.add(key)
        edge = edges.get(key)
        if not edge:
            problems.append(f"{row['Source']} & {row['Target']}: not in edges.csv")
            continue
        for field, want in (("Relationship_Type", edge["Relationship_Type"]),
                            ("First_Season", edge["First_Season"]),
                            ("First_Episode", edge["First_Episode"]),
                            ("Last_Season", num(edge["Last_Season"])),
                            ("Last_Episode", num(edge["Last_Episode"])),
                            ("Married_Season", num(edge["Married_Season"])),
                            ("Outcome", edge["Outcome"])):
            if row.get(field, "") != want:
                problems.append(f"{row['Source']} & {row['Target']}: "
                                f"{field} is {row.get(field, '')!r}, edges.csv says {want!r}")
    for key in set(edges) - tracked:
        problems.append(f"{' & '.join(sorted(key))}: in edges.csv, missing from the tracker")

    if problems:
        print(f"{TRACKER} has drifted from edges.csv ({len(problems)} problem(s)):")
        for p in problems[:20]:
            print("  " + p)
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more")
        print("\nFix: python audit_apply.py reconcile")
        sys.exit(1)
    print(f"{TRACKER}: in step with edges.csv ({len(rows)} ties)")


def reconcile():
    """Re-read every current tie from edges.csv, and drop the ones that are gone."""
    names = []
    for edge in load_edges().values():
        names += [edge["Source"], edge["Target"]]
    main(names)


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["sync"]:
        sync(verify_shows=tuple(sys.argv[2:]))
    elif cmd == ["check"]:
        check()
    elif cmd == ["reconcile"]:
        reconcile()
    else:
        main(sys.argv[2:] if cmd == ["verify"] else sys.argv[1:])
