# Grey's Anatomy Universe — relationship network

An interactive chart of every romantic and parental tie across **Grey's Anatomy**
(22 seasons), **Station 19** (7) and **Private Practice** (6) — 231 connections
between 183 characters, modelled so it can be replayed at any point in any of
the three shows.

**[View the chart →](https://greys-network-4bb08f.gitlab.io/)**

<sub>Rebuilt from source by CI on every push, so the live page can never drift
from the data. The datasets are published alongside it:
[edges.csv](https://greys-network-4bb08f.gitlab.io/edges.csv) ·
[nodes.csv](https://greys-network-4bb08f.gitlab.io/nodes.csv) ·
[shows.csv](https://greys-network-4bb08f.gitlab.io/shows.csv)</sub>

## The point of it

A relationship chart is usually a snapshot: everyone married to whoever they
ended up with. This one is a *timeline*. Every tie knows when it started, when a
hookup became a relationship, when the wedding was, when the divorce was, and
when it ended — so the graph can be rewound to any episode and show you only
what a viewer at that point would know.

That makes it safe to look at mid-rewatch. Set the sliders to where you are and
nothing later is on screen.

### Trace a connection

Pick any two people and the chart finds the shortest route between them —
*Meredith → Derek → Addison → Mark → Amelia → Owen → Cristina* — and lights it
up on the graph.

It searches only the links **currently on screen**, which matters more than it
sounds: routing through the full graph and then hiding the result would leak
exactly what the cutoff exists to hide. "Three steps" tells you the steps are
there even if you can't see them.

Some people genuinely have no route. Miranda Bailey is unreachable from
Meredith — every one of her partners has no other tie in the dataset.

### Shareable views

The whole view lives in the URL: per-show cutoffs, filters, spacing, selection
and any traced route. Whatever is on your screen, the address bar will
reproduce for someone else — including their own spoiler cutoff, so you can
send a link without wrecking anyone's rewatch.

### Three shows, three clocks

The spinoffs each have their own season numbering, and conflating them is the
single biggest source of error in a dataset like this. A `3x05` citation on
Carina DeLuca's page is **Station 19** season 3 — which aired opposite Grey's
season 16, not Grey's season 3.

So every date here belongs to exactly one show, and each show gets its own
toggle and its own cutoff. A tie appears once the show you're watching has
actually revealed it: if Station 19 showed you a wedding that Grey's only
mentioned in passing, the chart knows the difference.

## Running it

```bash
python greys_network.py --outdir .          # data -> edges.csv, nodes.csv, shows.csv
python build_visualization.py --indir .     # CSVs -> greys_network.html
npm install && npm test                     # jsdom + d3; three suites, all must pass
```

`greys_network.html` is fully standalone — open it directly, no server needed.

| file | role |
|---|---|
| `greys_network.py` | Source of truth. All relationship data as Python literals. |
| `build_visualization.py` | CSVs → the standalone HTML page. |
| `wiki_harvest.py` | Harvests the wiki and diffs it against `edges.csv`. |
| `review.py` | Dumps a character's relationship prose for checking a tie by hand. |
| `audit_apply.py` | Keeps `audit_tracker.csv` in step with `edges.csv`. |
| `tests/` | Render check, UI driver, and cross-show date gating. |

## Data quality

All 162 romantic ties are source-checked against the wiki prose, tie by tie —
`audit_tracker.csv` records the state of each. Episode citations were **not**
trusted on their own: they routinely mark the episode where a past relationship
was *narrated* rather than when it happened, which is how one tie ended up dated
to a season its character never appears in.

Known-soft spots are documented in `CLAUDE.md` rather than hidden — the one
wedding with no citation anywhere, the pre-series marriages dated by convention,
and the partners deliberately excluded for never appearing on screen.

Where a date is genuinely uncertain it is dated **late** on purpose. A too-late
date hides something you have already seen; a too-early one spoils you.

## Sources & credit

**The idea came from Dana's "romantic web" infographic**
([itsdatadana.com](https://itsdatadana.com/)) — a hand-built chart of the
Grey's romantic network, accurate through Season 18. This project is a
descendant of it, and owes it more than inspiration: **Dana's scope rules are
the ones this dataset is built on.** A tie counts if the pair had sex or dated
beyond one date, *and* both people appear in a present-day storyline.

Those two clauses did most of the real work. They are why unrequited crushes,
single kisses and off-screen spouses are excluded, and they settled dozens of
judgement calls during the audit that the wiki alone left ambiguous — the wiki
files a one-sided crush under "Romantic" just the same as a marriage. Every
rejected tie in this dataset was rejected against Dana's rules.

Relationship facts come from the [Grey's Anatomy Universe
Wiki](https://greysanatomy.fandom.com/), which is licensed
**[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)** — full
credit to its contributors. This repository stores *facts* (who, what, which
season), not wiki prose; the harvester's local cache of article text is
gitignored and never published. A handful of Season 21 dates the wiki had not
yet covered were filled in from published episode recaps.

Character names and the underlying works are the property of their respective
rights holders. This is a non-commercial fan project with no affiliation to ABC,
Shondaland, or Disney.

Code is MIT licensed; see `LICENSE`.
