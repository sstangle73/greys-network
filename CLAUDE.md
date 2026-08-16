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
| `episode_harvest.py` | Caches one wiki page per episode (681 across three shows) and scans summaries for when a pair actually got together. |
| `backfill_episodes.py` | Candidate generator for episode dates. **Report-only — its docstring explains why its output cannot be trusted unverified.** |
| `citations.csv` | The evidence behind each tie: which episode, and how far the evidence goes. |
| `audit_apply.py` | Re-reads verified pairs out of `edges.csv` into `audit_tracker.csv`, so `Verified` can't drift from the source of truth. |
| `audit_tracker.csv` | Romantic ties with a `Verified` column marking which are source-checked. |
| `tests/paintcheck.mjs` | Asserts the chart actually renders in all three code paths. |
| `tests/runtime.mjs` | Drives every UI control in jsdom, catches runtime errors. |
| `tests/crossshow.mjs` | Asserts each show's slider governs only its own dates. |
| `tests/table.mjs` | Table filters — and, more importantly, that the table is still complete and inert with scripting off. |

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

**Episode precision is per-tie, and `Episode_Known` says which.** All 158
romantic ties now carry a real start episode, and all but 2 carry a real end.
Anything still flagged `Episode_Known=0` is held back until its whole season has
been watched, which is the late end.

**Anchor a tie to the episode the viewer is shown or told about it — never to an
inferred origin.** This is the rule that closed the last of the unknowns, and it
sounds like it violates the date-late rule until you see why it cannot:

- An *inferred* start ("this probably began around here") can land before the
  viewer watched it. That is the unrecoverable direction.
- An *introduction* cannot. If `2x05` is where Bailey tells Derek the man at the
  glass is her husband, then dating the marriage `2x05` reveals nothing a viewer
  at `2x05` has not just seen.

So the anchor is the first sighting, not the first guess. Under Dana's scope
rule a tie cannot qualify without screen time, so a sighting almost always
exists — and where it doesn't, the season-close fallback stays.

Read the other way, the rule is a smell test: **a relationship whose start you
cannot anchor to any episode is a relationship you should check actually
happened on screen.** Three of the five last unknowns turned out to be dated to
the wrong season, and one was dated to a season the character never appears in.

`_end_episode_is_known()` is the mirror of `_episode_is_known()` and exists for
the same reason. Five ties genuinely did end in an episode 1 and were being
held to their season's close, because a `1` in the end column meant both "ended
in the premiere" and "we don't know" — and no amount of reading the data could
separate them.

That flag exists because `First_Episode: 1` used to mean two different things —
"the pilot" and "we have no idea" — and episode 1 is the *earliest* point in a
season, so every unknown was being asserted at the most spoiler-risky moment
available. The fallback was invisible on a static chart and obvious the moment
timeline playback landed. Worth remembering that a display feature can be the
thing that audits your data.

**Do not mine episode numbers.** Taking the earliest code in a section looks
safe and is not: for Owen & Teddy in season 14 it picks 14x02, where the prose
is Teddy *backing away* from a kiss, while the relationship starts at 14x17. A
`==Romantic==` section narrates the friendship and the near-misses first, so the
earliest code is routinely many episodes early — in the direction that spoils.
`backfill_episodes.py` keeps the full autopsy.

Citation density on the character pages starts around **Grey's season 9**.
Before that the Romantic sections are largely unreferenced, and most of the
codes `review.py` reports are image filenames rather than citations. That is
what `episode_harvest.py` is for: on an episode page the number is in the
infobox and the season is the category, so a fact found there arrives already
dated.

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
- **No tie renders as starting after it ends.** Compares the dates the chart will
  actually *draw*, not the ones stored, because the two differ whenever an
  episode is unknown. An unknown start is held to its season's close, so a tie
  with an unknown start that also ended inside that same season could never
  appear as a live relationship at any cutoff — only ever as a past one. Three
  ties were in that state and nothing complained, because each half is
  individually reasonable and only the combination is broken.

## Parent edges: three conventions, not one

The stated rule is "dated to when the child appears", and that only covers
children born during a show. Two other rules are silently in play, and the
parent audit surfaced them:

- **Adult children who are cast members** are dated to when the *parentage is
  revealed*, not when the person appears. Jackson debuts in S6 and his edge to
  Catherine is S8; Addison debuts in PP S1 and her edge to The Captain is PP S3.
- **Children who never appear at all** are dated to the dialogue reveal. Eli and
  Alexis are S16 for that reason.

Both are defensible — a chart of what a viewer knows should move when the viewer
learns something — but they are different rules, so don't "fix" one to match
the other without deciding which you mean.

**A parent can join later than the other.** Owen fosters Leo alone at 14x20;
Teddy is not co-parenting until S16. Ben and Bailey take Pru in after Dean dies.
One date for both parents would have to be wrong for one of them.

## Node names are short forms, not wiki titles

`Bailey Shepherd` is *Derek Bailey Shepherd* on the wiki; `Tuck Jones` is
*William George Bailey Jones*; `Eli`/`Alexis Karev` are *Stevens*; `Molly Grey`
is *Molly Thompson*; `Scout Lincoln` is *Scout Derek Shepherd Lincoln*. The
short forms read better on a chart, but anything that joins this data back to
the wiki by name needs the alias table in `wiki_harvest.py`.

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

The audit is complete: **all 158 romantic ties across the three shows are
source-checked**, `audit_tracker.csv` has no unverified rows left, and every tie
carries a real start episode.

Where the remaining risk actually sits, for whoever picks this up:

- **Sullivan & Natasha Ross's wedding has no citation anywhere.** The marriage
  is asserted in three infoboxes and Sullivan's own "Romance with Natasha"
  heading is an empty stub. Dated to their last appearance (S19 7x10) under the
  date-late rule. This is the least defensible date in the dataset.
- **Pre-series relationships are dated to their first sighting**, per the rule
  above — Ellis & Thatcher, Richard & Adele, Bailey & Tucker, Sheldon & Laura,
  Michael & Kitty Dixon, Cristina & Colin Marlow. That is a convention, not a
  fact: it is when the viewer learns, not when it happened.
- **Four ties are visible for exactly one episode**, and that is correct rather
  than a degenerate span. Meredith & Hayes, Maggie & Dean, Jo & Chris Cleaver
  and Ellis & Thatcher are each revealed and closed inside a single hour — the
  relationship is narrated in the past tense the only time it is ever mentioned.
  There is no cutoff at which a viewer would think these couples are together,
  so they only ever draw under "show past ties". Don't "fix" them.
- **Evidence coverage: 131 cited, 15 inferred, 4 convention, 3 uncited, and 5
  with no `citations.csv` row at all.** Those last 5 are all Season 22 ties the
  wiki has not documented yet — they are audited but the reasoning was never
  written down, and they show as "Unrecorded" rather than pretending. That is
  the honest state; fill them in when the wiki catches up.
- **The two ties still lacking an end episode** are Thatcher & Danielle (she
  appears once, and nothing ever ends it) and Naomi & William White (his death
  is never dated anywhere in the cache). Both hold to their season's close,
  which is the safe reading. Ending them would assert a breakup that no episode
  shows.
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
- **The name autocomplete is hand-rolled, and has to stay that way.** It was a
  `<datalist>`, which is one attribute and behaves perfectly on a desktop. On
  Android Chrome the same markup renders as a *full-screen* list of all 187
  names, covering the chart, the rail and the text being typed — and nothing
  about a native datalist can be capped, styled or positioned. The replacement
  caps at 8 rows, flips above the field when there is no room below (the rail
  sits low on a phone, and the keyboard takes what is left), measures against
  `visualViewport` rather than `innerHeight` so an open keyboard counts, and
  grows its rows past 44px under `pointer: coarse`.
- The table has filters too, and they are **progressive enhancement**: every row
  is in the HTML, filtering only sets `hidden`, and the controls stay
  `display:none` until the script has run far enough to prove it works — so with
  scripting off there are no dead widgets in the tab order. That page's reason
  for existing is the no-JS reading; don't regress it.
- **The two pages round-trip.** Every name in the table links to
  `greys_network.html#sel=<name>`, which selects that person *and centres on
  them* — fitting the whole graph instead would land you on a speck among 187
  nodes. The detail panel links back to `table.html#q=<name>`, which the filter
  reads. The chart answers "who is this connected to"; the table answers "and
  how do we know".

## The drift monitor alerts on movement, not on disagreement

It used to fail whenever the wiki had a tie `edges.csv` did not — which meant a
candidate you had already looked at and rejected failed *every* scheduled run
forever. An alert that always fires is one nobody reads.

It now keeps a snapshot (`wikicache/drift_state.json`, so CI's existing cache
carries it between pipelines with no commit and no artifact) and reports three
things against it: **new** on the wiki, **type changed**, and **no longer
found** — that last one usually meaning a rename, which is exactly when the
`ALIASES` table goes stale. It fails only when something actually moved.

Standing candidates are still listed, just below the fold and without failing
the job. Ties left out **on purpose** are filtered into their own section with
the reason attached — `EXCLUDED` in `wiki_harvest.py`. Delete a line there and
that tie comes back as new, which is what you want if you have changed your
mind about it. Nothing is dropped silently; the counts are always printed.

**The baseline is a committed file, `drift_baseline.json`.** The first attempt
kept it in the CI cache, and that does not work here: the self-hosted runner
uses the docker executor with a local cache volume, and two consecutive
scheduled runs showed one creating the cache and the next reporting *"cache
file does not exist"*. `cache: when: always` is still set — this job exists to
fail, and without it the harvested pages get re-downloaded from a free,
volunteer-run wiki every alerting run — but correctness no longer rests on it.

Committing it is the better design anyway, for a reason unrelated to
reliability: reviewing wiki drift is a judgement call, and a judgement call
belongs in a diff. Clearing the alert is an explicit act —
`python wiki_harvest.py accept`, then commit — rather than a side effect of a
job having run. **Nothing in CI writes it.** A job that could silence its own
alarm would make the alarm meaningless.

This whole class of bug only appears when you *run* the thing: everything
passed locally, because locally nothing fails.

**`drift` and `accept` must call `harvest(max_age_days=0)`.** `harvest()` skips
any page already in the cache — correct for local work, catastrophic for a
scheduled check. The first scheduled run restored the CI cache, served all 68
pages from it, fetched **zero**, and reported a confident *"Nothing changed on
the wiki since the last run."* It would have said that forever. A green light
wired to nothing is worse than no light: it actively tells you not to look.

Note the irony worth remembering — the earlier *cache flakiness was hiding
this*. While the cache failed to restore, every run re-downloaded and the check
worked by accident. Fixing the cache broke the checker. When you fix an
infrastructure problem, re-check the things that were silently depending on it
being broken.

Two guards go with it, because always-fetching introduces a failure mode that
skip-if-present did not have. A page is written only on success, so a failed
fetch leaves the older copy (stale beats absent — a missing page reads as
"every tie on it was deleted"). And if more than a fifth of the seeds fail,
`drift` exits 2 and refuses to diff at all rather than reporting a wiki outage
as mass deletion. `accept` is stricter still: it refuses on *any* failure,
since a baseline recorded from an incomplete harvest silently suppresses real
alerts later.

A scheduled run also rebuilds and redeploys the site. That is intentional — it
refreshes the portrait cache — and a drift failure does not block it, because
`pages` needs `build` and `test`, not `drift`. Verified: the run that surfaced
the cache bug still deployed.
