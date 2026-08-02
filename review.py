"""Reviewer's companion to wiki_harvest.py.

Not part of the build. Dumps the Romantic-section prose (and infobox partner
fields) for a character so a tie can be checked against what the wiki actually
says, rather than against infer_season()'s citation scraping.

    python review.py headings "Taryn Helm"
    python review.py show "Meredith Grey" "Nick Marsh"
    python review.py infobox "Nick Marsh"
    python review.py grep "Kevin Nelson"
"""

import os
import re
import sys

CACHE = "wikicache"


def load(title):
    path = os.path.join(CACHE, title.replace("/", "_") + ".wiki")
    return open(path, encoding="utf-8").read()


def sections(text):
    """(partner, level, body) for every ===Romantic=== subsection."""
    out, in_rom, depth, cur, body = [], False, 0, None, []
    for line in text.splitlines():
        h = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", line)
        if h:
            level, title = len(h.group(1)), h.group(2)
            if title.strip().lower() == "romantic":
                in_rom, depth = True, level
                continue
            if in_rom and level <= depth:
                if cur:
                    out.append((cur, depth + 1, "\n".join(body)))
                in_rom, cur, body = False, None, []
                continue
            if in_rom and level == depth + 1:
                if cur:
                    out.append((cur, level, "\n".join(body)))
                cur, body = re.sub(r"\[\[|\]\]", "", title), []
                continue
        if cur is not None:
            body.append(line)
    if cur:
        out.append((cur, depth + 1, "\n".join(body)))
    return out


def strip(body):
    """Prose only: drop images, refs keep their episode code, collapse links."""
    body = re.sub(r"\[\[(?:Image|File):[^\]]*\]\]", "", body)
    body = re.sub(r"<ref>\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\],?\s*([0-9]+x[0-9]+)?[^<]*</ref>",
                  lambda m: f" [{m.group(2) or m.group(1)}]", body)
    body = re.sub(r"<ref[^>]*/?>", "", body)
    body = re.sub(r"</ref>", "", body)
    body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"'''?", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def cmd_headings(title):
    for name, level, body in sections(load(title)):
        codes = sorted({c for c in re.findall(r"\b\d{1,2}x\d{2}\b", body)},
                       key=lambda c: (int(c.split("x")[0]), int(c.split("x")[1])))
        print(f"  {name:38} {len(body):6}b  {' '.join(codes[:6])}"
              f"{' ...' if len(codes) > 6 else ''}")


def cmd_show(title, partner):
    for name, level, body in sections(load(title)):
        if partner.lower() in name.lower():
            print(f"===== {title} :: {name} =====")
            print(strip(body))
            print()


def cmd_infobox(title):
    for line in load(title).splitlines():
        m = re.match(r"\s*\|\s*([A-Za-z_ ]+?)\s*=\s*(.*)$", line)
        if m and m.group(1).strip().lower().replace(" ", "_") in (
                "marital", "spouse", "significant_others", "significantothers",
                "status", "family", "relationships"):
            print(line)


def cmd_grep(needle):
    for fname in sorted(os.listdir(CACHE)):
        if not fname.endswith(".wiki"):
            continue
        text = open(os.path.join(CACHE, fname), encoding="utf-8").read()
        for i, line in enumerate(text.splitlines()):
            if needle.lower() in line.lower():
                print(f"{fname[:-5]:26} :{i}: {strip(line)[:400]}")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    {"headings": cmd_headings, "show": cmd_show,
     "infobox": cmd_infobox, "grep": cmd_grep}[cmd](*rest)
