"""
Accessible table view
=====================
Emits table.html: every tie as plain HTML, no JavaScript, no SVG.

The chart is a force-directed graph. That is fine for browsing and useless to a
screen reader, to a text browser, or to anyone with scripting off -- so the same
data gets a second face that is just a table. It doubles as the readable form of
the audit: each row carries its own evidence and how far that evidence goes.

    python build_table.py --indir . --out table.html
"""

import argparse
import csv
import html
import os

CONFIDENCE_BLURB = {
    "cited": ("Cited", "An episode citation sits on the sentence describing the event."),
    "inferred": ("Inferred", "No citation on the event itself; derived from surrounding evidence."),
    "convention": ("Convention", "Pre-series. Dated to the pair's first on-screen appearance."),
    "uncited": ("Uncited", "No evidence found. The value is a deliberate late estimate."),
    "unrecorded": ("Unrecorded", "Checked against the wiki, but the citation was not written down."),
}

SHOW_NAME = {"GA": "Grey's Anatomy", "PP": "Private Practice", "S19": "Station 19"}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def when(row, show):
    """A human span, in the show's own numbering."""
    def tag(s, e):
        if not s:
            return ""
        return f"S{s}" + (f"&thinsp;E{int(float(e)):02d}" if e and int(float(e)) > 1 else "")
    start = tag(row["First_Season"], row["First_Episode"])
    end = tag(row["Last_Season"], row["Last_Episode"])
    if not end:
        return f"{start} &ndash; present"
    return start if start == end else f"{start} &ndash; {end}"


def build(indir):
    edges = read(os.path.join(indir, "edges.csv"))
    cites = {}
    cpath = os.path.join(indir, "citations.csv")
    if os.path.exists(cpath):
        cites = {frozenset({r["Source"], r["Target"]}): r for r in read(cpath)}

    romantic = [e for e in edges if e["Relationship_Type"] != "Parent"]
    family = [e for e in edges if e["Relationship_Type"] == "Parent"]

    def rows_for(items, kind):
        out = []
        for e in sorted(items, key=lambda r: (r["Show"], r["Source"], r["Target"])):
            c = cites.get(frozenset({e["Source"], e["Target"]}), {})
            conf = c.get("Confidence", "unrecorded")
            label, _ = CONFIDENCE_BLURB.get(conf, (conf.title(), ""))
            outcome = e.get("Outcome") or ""
            type_cell = html.escape(e["Relationship_Type"])
            if outcome:
                type_cell += f' <span class="tag">{html.escape(outcome.lower())}</span>'
            out.append(f"""      <tr>
        <th scope="row">{html.escape(e['Source'])}</th>
        <td>{html.escape(e['Target'])}</td>
        <td>{type_cell}</td>
        <td><abbr title="{html.escape(SHOW_NAME.get(e['Show'], e['Show']))}">{html.escape(e['Show'])}</abbr></td>
        <td>{when(e, e['Show'])}</td>
        <td>{html.escape(c.get('Citation', '')) or '<span class="none">&mdash;</span>'}</td>
        <td><span class="conf conf-{conf}">{html.escape(label)}</span></td>
      </tr>""")
        return "\n".join(out)

    legend = "\n".join(
        f'      <div><span class="conf conf-{k}">{html.escape(v[0])}</span> {html.escape(v[1])}</div>'
        for k, v in CONFIDENCE_BLURB.items())

    return TEMPLATE.format(
        romantic=rows_for(romantic, "romantic"),
        family=rows_for(family, "family"),
        legend=legend,
        n_romantic=len(romantic),
        n_family=len(family),
        n_cited=sum(1 for e in romantic
                    if cites.get(frozenset({e["Source"], e["Target"]}), {})
                    .get("Confidence") == "cited"),
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Grey's Anatomy Universe &mdash; every relationship</title>
<style>
  :root {{
    color-scheme: dark light;
    --ground: #0B2B2E; --panel: #10393D; --rule: #1F5457;
    --bone: #E8EDE9; --muted: #7FA3A0; --gold: #E8B84B; --cyan: #4FC3D9;
    --magenta: #E0576E; --violet: #9B8CE0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 28px 20px 64px; background: var(--ground); color: var(--bone);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.55;
  }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; letter-spacing: .02em; }}
  h2 {{ font-size: 15px; margin: 34px 0 10px; text-transform: uppercase;
       letter-spacing: .12em; color: var(--muted); font-weight: 600; }}
  p {{ margin: 0 0 12px; max-width: 66ch; }}
  a {{ color: var(--cyan); }}
  .lede {{ color: var(--muted); font-size: 14px; }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
  caption {{ text-align: left; color: var(--muted); font-size: 12.5px; padding-bottom: 8px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--rule);
           vertical-align: top; white-space: nowrap; }}
  thead th {{ position: sticky; top: 0; background: var(--panel); font-size: 11px;
             text-transform: uppercase; letter-spacing: .1em; color: var(--muted); }}
  tbody th {{ font-weight: 600; }}
  tbody tr:hover {{ background: rgba(255,255,255,.035); }}
  .none {{ color: var(--muted); }}
  .tag {{ font-size: 11px; color: var(--magenta); }}
  abbr {{ text-decoration: none; border-bottom: 1px dotted var(--muted); cursor: help; }}
  /* Confidence is text first. Colour only reinforces it, and the four hues are
     ~90 degrees apart with no red-green pair. */
  .conf {{ font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
          border-left: 3px solid var(--muted); padding-left: 6px; }}
  .conf-cited {{ border-color: var(--cyan); }}
  .conf-inferred {{ border-color: var(--gold); }}
  .conf-convention {{ border-color: var(--violet); }}
  .conf-uncited {{ border-color: var(--magenta); color: var(--magenta); }}
  .conf-unrecorded {{ border-color: var(--muted); color: var(--muted); }}
  .legend {{ font-size: 12.5px; color: var(--muted); display: grid; gap: 5px; }}
  footer {{ margin-top: 40px; font-size: 12px; color: var(--muted); }}
</style>
</head>
<body>
<main>
  <h1>Grey's Anatomy Universe &mdash; every relationship</h1>
  <p class="lede">
    A plain-text view of the same dataset behind <a href="index.html">the chart</a>:
    {n_romantic} romantic ties and {n_family} parent links across three shows.
    {n_cited} romantic ties carry a direct episode citation.
  </p>
  <p class="lede">
    Every date is in <strong>its own show's numbering</strong>. A season 3 on a
    Station&nbsp;19 row is not Grey's season 3 &mdash; the two aired thirteen
    seasons apart.
  </p>

  <h2>How far the evidence goes</h2>
  <div class="legend">
{legend}
  </div>

  <h2>Romantic ties</h2>
  <div class="scroll">
  <table>
    <caption>Sorted by show, then by name. Spans are inclusive.</caption>
    <thead>
      <tr><th scope="col">Person</th><th scope="col">Partner</th><th scope="col">Type</th>
          <th scope="col">Show</th><th scope="col">When</th>
          <th scope="col">Citation</th><th scope="col">Evidence</th></tr>
    </thead>
    <tbody>
{romantic}
    </tbody>
  </table>
  </div>

  <h2>Parents and children</h2>
  <div class="scroll">
  <table>
    <caption>Blood and legal relationships. Dated to when the child appears.</caption>
    <thead>
      <tr><th scope="col">Parent</th><th scope="col">Child</th><th scope="col">Type</th>
          <th scope="col">Show</th><th scope="col">When</th>
          <th scope="col">Citation</th><th scope="col">Evidence</th></tr>
    </thead>
    <tbody>
{family}
    </tbody>
  </table>
  </div>

  <footer>
    Inspired by <a href="https://itsdatadana.com/">Dana's romantic web</a>, whose
    scope rules this dataset follows. Facts from the
    <a href="https://greysanatomy.fandom.com/">Grey's Anatomy Universe Wiki</a> (CC&nbsp;BY-SA).
    <a href="https://gitlab.com/sstangle73/greys-network">Source &amp; data</a>.
  </footer>
</main>
</body>
</html>
"""


def main(indir, out):
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build(indir))
    print(f"Wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the accessible table view.")
    ap.add_argument("--indir", default=".")
    ap.add_argument("--out", default="table.html")
    args = ap.parse_args()
    main(args.indir, args.out)
