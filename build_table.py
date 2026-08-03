"""
Accessible table view
=====================
Emits table.html: every tie as plain HTML, no SVG.

The chart is a force-directed graph. That is fine for browsing and useless to a
screen reader, to a text browser, or to anyone with scripting off -- so the same
data gets a second face that is just a table. It doubles as the readable form of
the audit: each row carries its own evidence and how far that evidence goes.

The filters are the one piece of script on the page, and they are strictly an
enhancement: every row is in the HTML, filtering only ever sets `hidden`, and
the controls stay display:none until the script has run far enough to prove it
works. With scripting off this is still the complete table it was before, with
no dead widgets in the tab order. Do not let that slip -- the no-JS reading is
the reason this file exists.

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
    """A human span, in the show's own numbering.

    Episode 1 used to be suppressed here, on the assumption that a `1` was
    always the "we don't know" placeholder. That stopped being true once the
    known-flags were filled in: a genuine premiere now renders as a bare season
    and reads as less precise than it is. Trust the flag, not the value.
    """
    def tag(season, episode, known):
        if not season:
            return ""
        if not known:
            # Say so rather than printing an episode and letting it pass for
            # precision we do not have.
            return f'S{season}<span class="none">&thinsp;E??</span>'
        return f"S{season}&thinsp;E{int(float(episode or 1)):02d}"

    start = tag(row["First_Season"], row["First_Episode"],
                row.get("Episode_Known") != "0")
    end = tag(row["Last_Season"], row["Last_Episode"],
              row.get("End_Episode_Known") != "0")
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
            # Everything the filter matches on rides the row, so filtering never
            # has to re-read the cells. Searching covers the citation too, so
            # "18x01" finds every tie anchored there.
            hay = " ".join((e["Source"], e["Target"], c.get("Citation", ""),
                            SHOW_NAME.get(e["Show"], e["Show"]),
                            e["Relationship_Type"], outcome)).lower()
            out.append(f"""      <tr data-show="{html.escape(e['Show'])}"
          data-type="{html.escape(e['Relationship_Type'])}"
          data-conf="{html.escape(conf)}"
          data-names="{html.escape(hay)}">
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

    def group(name, title, values, labels=None):
        """One fieldset of checkboxes, built from the data that is actually here.

        Derived rather than hardcoded so a new show or relationship type cannot
        quietly become unfilterable.
        """
        boxes = []
        for v in values:
            text = (labels or {}).get(v, v)
            ident = f"f-{name}-{v}".replace(" ", "-").lower()
            boxes.append(
                f'        <label for="{ident}"><input type="checkbox" id="{ident}"'
                f' name="{name}" value="{html.escape(v)}" />'
                f' {html.escape(str(text))}</label>')
        return (f'      <fieldset>\n        <legend>{html.escape(title)}</legend>\n'
                + "\n".join(boxes) + "\n      </fieldset>")

    shows = sorted({e["Show"] for e in edges}, key=lambda s: (s != "GA", s))
    types = sorted({e["Relationship_Type"] for e in edges})
    confs = [k for k in CONFIDENCE_BLURB
             if any(cites.get(frozenset({e["Source"], e["Target"]}), {})
                    .get("Confidence", "unrecorded") == k for e in edges)]

    filters = "\n".join([
        group("show", "Show", shows, SHOW_NAME),
        group("type", "Type", types),
        group("conf", "Evidence", confs,
              {k: v[0] for k, v in CONFIDENCE_BLURB.items()}),
    ])

    return TEMPLATE.format(
        romantic=rows_for(romantic, "romantic"),
        family=rows_for(family, "family"),
        legend=legend,
        filters=filters,
        script=SCRIPT,
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

  /* Filtering is an ENHANCEMENT. This page's whole point is that it works with
     no scripting, so the controls stay hidden until the script proves it ran.
     With JS off you get every row and no dead widgets to tab through. */
  .filters {{ display: none; }}
  [data-js] .filters {{
    display: flex; flex-wrap: wrap; gap: 10px 22px; align-items: flex-start;
    background: var(--panel); border: 1px solid var(--rule); border-radius: 8px;
    padding: 14px 16px; margin-top: 10px;
  }}
  .filters fieldset {{ border: 0; margin: 0; padding: 0; display: flex;
                      flex-wrap: wrap; gap: 4px 14px; align-items: center; }}
  .filters legend {{ float: left; width: 100%; font-size: 11px; color: var(--muted);
                    text-transform: uppercase; letter-spacing: .1em; padding: 0 0 4px; }}
  .filters label {{ font-size: 13px; display: inline-flex; align-items: center;
                   gap: 5px; cursor: pointer; white-space: nowrap; }}
  .filters input {{ accent-color: var(--cyan); width: 15px; height: 15px; margin: 0; }}
  .search {{ display: flex; flex-direction: column; gap: 4px; flex: 1 1 210px; }}
  .search label {{ font-size: 11px; color: var(--muted);
                  text-transform: uppercase; letter-spacing: .1em; }}
  .search input {{ font: inherit; font-size: 13px; padding: 6px 9px; width: 100%;
                  color: var(--bone); background: var(--ground);
                  border: 1px solid var(--rule); border-radius: 5px; }}
  .search input:focus-visible, .filters input:focus-visible,
  .reset:focus-visible {{ outline: 2px solid var(--cyan); outline-offset: 2px; }}
  .reset {{ font: inherit; font-size: 12px; color: var(--bone); cursor: pointer;
           background: transparent; border: 1px solid var(--rule);
           border-radius: 5px; padding: 6px 12px; align-self: center; }}
  .reset:hover {{ border-color: var(--cyan); color: var(--cyan); }}
  .count {{ font-variant-numeric: tabular-nums; }}
  /* Not colour alone: the empty state is a sentence. */
  [data-empty] td {{ color: var(--muted); font-style: italic; white-space: normal; }}
</style>
</head>
<body>
<main>
  <h1>Grey's Anatomy Universe &mdash; every relationship</h1>
  <p class="lede">
    A plain-text view of the same dataset behind
    <a href="greys_network.html">the chart</a>:
    {n_romantic} romantic ties and {n_family} parent links across three shows.
    {n_cited} romantic ties carry a direct episode citation.
  </p>
  <p class="lede">
    Every date is in <strong>its own show's numbering</strong>. A season 3 on a
    Station&nbsp;19 row is not Grey's season 3 &mdash; the two aired thirteen
    seasons apart.
  </p>

  <h2>Filter</h2>
  <form class="filters" id="filters" role="search" aria-label="Filter relationships">
      <div class="search">
        <label for="q">Search name, citation or type</label>
        <input type="search" id="q" name="q" autocomplete="off"
               placeholder="Bailey, 18x01, divorced&hellip;" />
      </div>
{filters}
      <button type="button" class="reset" id="reset">Clear filters</button>
  </form>

  <h2>How far the evidence goes</h2>
  <div class="legend">
{legend}
  </div>

  <h2>Romantic ties</h2>
  <div class="scroll">
  <table data-table="romantic">
    <caption>Sorted by show, then by name. Spans are inclusive.
      <span class="count" data-count aria-live="polite"></span></caption>
    <thead>
      <tr><th scope="col">Person</th><th scope="col">Partner</th><th scope="col">Type</th>
          <th scope="col">Show</th><th scope="col">When</th>
          <th scope="col">Citation</th><th scope="col">Evidence</th></tr>
    </thead>
    <tbody>
{romantic}
      <tr data-empty hidden><td colspan="7">No romantic ties match these filters.</td></tr>
    </tbody>
  </table>
  </div>

  <h2>Parents and children</h2>
  <div class="scroll">
  <table data-table="family">
    <caption>Blood and legal relationships. Dated to when the child appears.
      <span class="count" data-count aria-live="polite"></span></caption>
    <thead>
      <tr><th scope="col">Parent</th><th scope="col">Child</th><th scope="col">Type</th>
          <th scope="col">Show</th><th scope="col">When</th>
          <th scope="col">Citation</th><th scope="col">Evidence</th></tr>
    </thead>
    <tbody>
{family}
      <tr data-empty hidden><td colspan="7">No parent links match these filters.</td></tr>
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
<script>
{script}
</script>
</body>
</html>
"""


# Kept out of TEMPLATE so it needs no brace-doubling -- str.format would other-
# wise require every { in the JS to be written {{, which is exactly the kind of
# edit that silently breaks a page the tests then have to catch.
SCRIPT = r"""
(function () {
  'use strict';
  var root = document.documentElement;
  var form = document.getElementById('filters');
  var q = document.getElementById('q');
  var reset = document.getElementById('reset');
  var tables = [].slice.call(document.querySelectorAll('table[data-table]'));
  if (!form || !q || !tables.length) return;
  // Only now do the controls appear. If anything above threw or the script
  // never ran, the page stays exactly what it is without JS: every row shown.
  root.setAttribute('data-js', '');

  var boxes = [].slice.call(form.querySelectorAll('input[type=checkbox]'));

  function chosen(group) {
    var on = boxes.filter(function (b) { return b.name === group && b.checked; });
    // Nothing ticked means "no constraint on this axis", NOT "match nothing" --
    // otherwise a fresh page would open with an empty table.
    return on.length ? on.map(function (b) { return b.value; }) : null;
  }

  function apply() {
    var text = (q.value || '').trim().toLowerCase();
    var shows = chosen('show'), types = chosen('type'), confs = chosen('conf');
    tables.forEach(function (table) {
      var rows = [].slice.call(table.tBodies[0].rows);
      var empty = null, shown = 0, total = 0;
      rows.forEach(function (row) {
        if (row.hasAttribute('data-empty')) { empty = row; return; }
        total++;
        var d = row.dataset;
        var ok = (!shows || shows.indexOf(d.show) >= 0)
              && (!types || types.indexOf(d.type) >= 0)
              && (!confs || confs.indexOf(d.conf) >= 0)
              && (!text || (d.names || '').indexOf(text) >= 0);
        row.hidden = !ok;
        if (ok) shown++;
      });
      if (empty) empty.hidden = shown > 0;
      var count = table.querySelector('[data-count]');
      if (count) {
        count.textContent = shown === total
          ? 'Showing all ' + total + '.'
          : 'Showing ' + shown + ' of ' + total + '.';
      }
    });
    save();
  }

  // A filtered view should be linkable, the same way the chart's is. Wrapped
  // because a file:// or sandboxed document can refuse replaceState outright,
  // and losing the URL is not worth losing the filters over.
  function save() {
    try {
      var parts = [];
      if (q.value.trim()) parts.push('q=' + encodeURIComponent(q.value.trim()));
      ['show', 'type', 'conf'].forEach(function (g) {
        var on = chosen(g);
        if (on) parts.push(g + '=' + on.map(encodeURIComponent).join(','));
      });
      history.replaceState(null, '', parts.length ? '#' + parts.join('&') : '#');
    } catch (e) { /* no URL sync, filters still work */ }
  }

  function restore() {
    var hash = '';
    try { hash = (location.hash || '').replace(/^#/, ''); } catch (e) { return; }
    if (!hash) return;
    hash.split('&').forEach(function (pair) {
      var i = pair.indexOf('=');
      if (i < 0) return;
      var key = pair.slice(0, i), val = decodeURIComponent(pair.slice(i + 1));
      if (key === 'q') { q.value = val; return; }
      var want = val.split(',');
      boxes.forEach(function (b) {
        if (b.name === key && want.indexOf(b.value) >= 0) b.checked = true;
      });
    });
  }

  form.addEventListener('input', apply);
  form.addEventListener('submit', function (e) { e.preventDefault(); });
  reset.addEventListener('click', function () {
    q.value = '';
    boxes.forEach(function (b) { b.checked = false; });
    apply();
    q.focus();
  });

  restore();
  apply();
})();
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
