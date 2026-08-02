# Grey's Anatomy Universe relationship network

A dataset and interactive chart of every romantic and parental tie across the
whole universe — Grey's Anatomy (22 seasons), Station 19 (7) and Private
Practice (6) — modelled so it can be replayed at any point in any of them.

**Every date belongs to exactly one show's numbering.** A `3x05` on Carina's
page is Station 19 season 3, which aired opposite Grey's season 16. Collapsing
the three shows onto one season axis is what caused the worst errors in the
first audit; `Show` on every edge is the fix.

## ⚠️ Spoiler rule — read this first

**The owner is watching at Season 22, Episode 2.** Anything after that point is
a spoiler for them.

- Never volunteer plot details past S22 E02 in conversation.
- Data files may contain later events — that's intended; the chart hides them.
- When discussing a correction past their cutoff, say *"a S22 change I won't
  detail"* rather than describing it.
- When a date is uncertain, **date it LATE**. A too-late tag hides something
  they've already seen (mildly annoying). A too-early tag spoils them (not
  recoverable).

## Files

| file | role |
|---|---|
| `greys_network.py` | Source of truth. All relationship data lives here as Python literals. Emits `edges.csv` + `nodes.csv` + `shows.csv`. |
| `build_visualization.py` | Reads the CSVs, emits the standalone `greys_network.html`. |
| `wiki_harvest.py` | Harvests the Grey's Anatomy Universe Wiki and diffs it against `edges.csv`. **Needs network — this is why the project moved to Claude Code.** |
| `review.py` | Reviewer's companion: dumps the `==Romantic==` prose for a character so a tie can be checked by hand. Not part of the build. |
| `audit_apply.py` | Re-reads verified pairs out of `edges.csv` into `audit_tracker.csv`, so `Verified` can't drift from the source of truth. |
| `audit_tracker.csv` | Romantic ties with a `Verified` column marking which are source-checked. |
| `tests/paintcheck.mjs` | Asserts the chart actually renders in all three code paths. |
| `tests/runtime.mjs` | Drives every UI control in jsdom, catches runtime errors. |
| `tests/crossshow.mjs` | Asserts each show's slider governs only its own dates. |

## Build

```bash
python greys_network.py --outdir .          # data -> edges.csv, nodes.csv, shows.csv
python build_visualization.py --indir .     # CSVs -> greys_network.html
npm install                                 # jsdom + d3, for the tests
npm test                                    # all three suites
```

Run the tests after **any** change to `build_visualization.py`. They exist
because of real regressions: a `let` accessed before its declaration (temporal
dead zone) that broke the page entirely, a freeze refactor that left every node
stacked at the origin because nothing painted the first frame, and a readout
that counted links the filters had already removed.

`build_visualization.py` writes with `newline="\n"` on purpose. Python's text
mode would emit CRLF on Windows, and both older suites match on
`<script>\n(const DATA` — without it the tests cannot pass on a clean Windows
checkout.

## Data model

A tie is not one state — it moves through stages, and the chart renders whichever
stage applies at the viewer's cutoff.

```
Show                    which show's numbering every date below is in
First_Season/Episode    when the pair first got involved
Dating_Season/Episode   when a hookup became a relationship (blank = always was)
Married_Season/Episode  the wedding
Outcome_Season/Episode  the divorce, if any
Last_Season/Episode     when it ended (blank = still together)
Reveals                 what OTHER shows showed, e.g. "GA:16x14:Dating"
```

`Show` is the tie's home show and every stage date is in that show's seasons.
`Reveals` is how a tie reaches a viewer who doesn't watch the home show: a tie
is on screen once its home show has reached it **or** any other enabled show has
revealed it, and it renders at the furthest-along stage any of them has shown.
That's what lets a Grey's-only viewer see exactly what Grey's told them.

So Meredith & Derek read: **Fling S1E01 → Dating S1E02 → Married S7 → ends S11.**
`Relationship_Type` records where a tie *ended up*; the stage dates decide what
shows on screen. Getting this wrong is what made S1E01 display three marriages
that hadn't happened yet.

Nodes carry `Death_Season`/`Death_Episode`, so status is also point-in-time.

### Invariants (enforced by `validate()` in `greys_network.py`)

- A relationship can't end before it starts
- A wedding can't predate the couple getting together
- A divorce can't predate the wedding
- Every `Married` tie needs a wedding date
- Every `Divorced` outcome needs a matching `Married` edge
- Timeline is monotonic: nothing appears then vanishes as you watch forward

## Sources, in order of trust

1. **Grey's Anatomy Universe Wiki** (greysanatomy.fandom.com) — structured
   relationship sections with episode citations. CC-BY-SA; credit it in the
   README. Relationship facts aren't copyrightable regardless.
2. **Dana's infographic** (itsdatadana.com, "romantic web", accurate to S18) —
   good for catching missing minor partners. Her scope rules: a tie counts if
   the pair had sex or dated beyond one date, and both people appear in a
   present-day storyline.
3. Episode recaps for Season 22, where the wiki is thinner.

**Do not ingest episode transcripts.** Facts extracted from them are fine, but
full scripts must not land in the repo — and in practice they're a poor source
here, since nobody says "we are now dating" on camera.

## Current task

The audit is complete: **all 162 romantic ties across the three shows are
source-checked**, and `audit_tracker.csv` has no unverified rows left.

Where the remaining risk actually sits, for whoever picks this up:

- **Sullivan & Natasha Ross's wedding has no citation anywhere.** The marriage
  is asserted in three infoboxes and Sullivan's own "Romance with Natasha"
  heading is an empty stub. Dated to their last appearance (S19 7x10) under the
  date-late rule. This is the least defensible date in the dataset.
- **Several pre-series marriages are dated to a first on-screen appearance**,
  per the convention above — Ellis & Thatcher, Richard & Adele, Sheldon &
  Laura, Michael & Kitty Dixon. That is a convention, not a fact.
- **Deliberately excluded**, all for the same reason — a partner who never
  appears in a present-day storyline: Koracick's Dana Hamilton, Teddy's Allison
  Brown, Travis's Michael Williams, Sullivan's Claire, Pete's Anna Wilder.
  Charlotte & Billy Douglas and Catherine & Robert Avery are pre-series
  marriages with no in-show dates at all; both are left out rather than given a
  degenerate one-episode span.
- The wiki has **numbering errors** in Station 19 seasons 5-6: two different
  titles both cited `6x10`, one episode cited as both `5x10` and `5x20`, and a
  `610` missing its `x`. Treat S19 S5-S6 episode numbers with suspicion.

To re-run the harvest:

```bash
python wiki_harvest.py harvest   # ~40 pages -> ./wikicache (1s pause each)
python wiki_harvest.py parse     # -> candidate_edges.csv
python wiki_harvest.py diff      # three buckets against edges.csv
```

Then reconcile the diff by hand. **`infer_season()` is the weak link** — it
scrapes `16x08`-style codes from prose, but citations often reference a scene
*about* a relationship's past rather than when it happened. Treat season hints
as "go check," never as values to write straight in.

Failure modes it has actually produced, all confirmed against prose:

- **A citation about something else entirely.** Levi & Nico were dated to S19
  from a citation about Nico *leaving the hospital* — in a season he never
  appears in.
- **Cross-show numbering.** "3x05" on Carina's page is Station 19; "5x01 (PP)"
  on Addison's is Private Practice. Both were being read as Grey's seasons.
- **Backstory narrated in the present.** Chris Cleaver, Molly Tran and Dean are
  all pre-series relationships cited to the episode that *mentions* them.
- **Quotation blocks.** The bottom of a page carries episode codes belonging to
  no relationship at all.
- **A `==Romantic==` section is not proof of a tie.** The wiki files unrequited
  crushes there too. Apply Dana's scope rule: sex, or more than one date.

Put your email in `UA` in `wiki_harvest.py` before running. If `action=raw` is
blocked, switch to `/api.php?action=query&prop=revisions&rvslots=*&rvprop=content&format=json`.

## Known-uncertain, deliberately left out

Named on Dana's chart, no wiki confirmation found: Cathy Nelson, Hockey Hank,
Dana Seabury, Laurel Pinson, Nurse Colleen, Noelle, Vikram Roy.

Estimated rather than sourced (both past the owner's cutoff): the end dates for
Kwan & Mohanty and Amelia & Toni.

Excluded on purpose: Koracick's late wife Dana Hamilton — never appears in a
present-day storyline, which is the same rule Dana used to exclude her.

## Chart behaviour worth knowing

- Layout freezes after the initial solve. Nothing moves unless dragged; there's
  an 8px drag threshold so a tap doesn't nudge nodes, and multi-touch passes
  through to zoom.
- Two node tiers: degree ≥ 3 gets a card, everyone else is a bare name.
  `Image_URL` in `nodes.csv` is empty by design — fill it in and cards become
  circular portraits automatically on the next build.
- Markers ride the middle of each edge: ♥ married, broken ♥ divorced, ••• relationship,
  1 one-time. Blood relations are dotted lines with no marker.
- **Colour is never the only cue.** Every type carries a dash pattern and a
  glyph as well, and the four hues (gold / cyan / magenta / violet) sit roughly
  90° apart with no red-green pair. Parent was mint green until it was pointed
  out that it paired with the red Fling into the commonest confusion there is.
  If you restyle, keep two non-colour cues per type.
- One cutoff block per show in the rail. Grey's keeps the bare `season` /
  `episode` element ids and is the primary control; spinoffs are suffixed
  (`season-PP`, `on-S19`). A show switched off fades but keeps its position.
- Label density keys off on-screen pixel gap, not zoom level. Keying it to zoom
  meant spreading the graph out perversely *hid* labels.
