"""Revision grading.

revwatch.py decides, without a human, that an edit to the wiki cannot have
changed this dataset. That decision is only safe in one direction: clearing a
page that actually moved a value loses data silently, and nothing downstream
would ever notice. So the cases that must ESCALATE are the point of this file,
and the cases that must clear are here to stop the grader from escalating
everything and quietly becoming the flat alert it replaced.

The fixtures are structural. They are wiki MARKUP -- infobox partner fields,
the ==Relationships== / ===Romantic=== / ====Partner==== nesting, a
==Full Summary== block, an |episode= line -- wrapped around invented names and
placeholder sentences. None of it is copied from the wiki. That is deliberate:
.gitignore keeps wikicache/ and episodecache/ out of this repository because
they hold CC-BY-SA prose we read facts out of and never republish, and a test
fixture full of real article text would walk that straight back in through the
front door.

Structure is all the grader looks at anyway. It never reads for meaning, only
for which regions the parsers touch and what they extract from them.

    python tests/test_revwatch.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import revwatch as rw

# Invented. Any resemblance to a character on the wiki is a bug in this file.
PEOPLE = ["Aurelia Vane", "Bram Holloway", "Corin Ashby", "Dulcie Vane",
          "Edda Prynne"]

FILLER = ("Placeholder sentence written for this fixture, long enough that the "
          "summary counts as usable rather than a stub. ")

CHARACTER = """{{Character Infobox
|name = Aurelia Vane
|marital = *[[Bram Holloway]] ''(ex-husband)''
*[[Corin Ashby]] ''(husband)''
|children = *[[Dulcie Vane]]
}}
Aurelia Vane is a fixture, not an article.

==History==
===Early Life===
Placeholder narrative. Nothing reads this, including in 4x02.

===Later Years===
Placeholder narrative. Nothing reads this either.

==Relationships==
===Romantic===
====[[Bram Holloway]]====
They married in 2x05 and separated in 2x11.

====[[Corin Ashby]]====
They married in 6x08 and renewed their vows in 6x12.

====[[Fen Marlowe]]====
They dated during 8x03.

===Familial===
====[[Dulcie Vane]]====
Placeholder narrative. Familial, so not a romantic section.

==Notes and Trivia==
* Placeholder.
"""

EPISODE = """{{Episode Infobox
|title = A Fixture Episode
|season = 6
|episode = 8
}}
==Short Summary==
Placeholder.

==Full Summary==
Aurelia tells Corin she is leaving. They kissed in the elevator while Bram
watched. """ + FILLER * 4 + """

==Notes and Trivia==
* Placeholder.
"""

STUB_EPISODE = EPISODE.replace(
    "Aurelia tells Corin she is leaving. They kissed in the elevator while Bram\n"
    "watched. " + FILLER * 4, "Placeholder.")

results = []


def case(label, kind, old, new, want, people=PEOPLE):
    tier, notes = rw.classify_edit(kind, old, new, people)
    results.append((tier == want, label, want, tier, notes))


def romantic(text, partner, body):
    """Replace one ====Partner==== body, so the edit lands where it is meant to."""
    head = f"===={partner}===="
    start = text.index(head) + len(head)
    end = text.index("\n\n", start)
    return text[:start] + "\n" + body + text[end:]


# --------------------------------------------------------------------------- #
# Must escalate
# --------------------------------------------------------------------------- #
case("a new ====Partner==== subsection appears", "character", CHARACTER,
     CHARACTER.replace("====[[Bram Holloway]]====",
                       "====[[Edda Prynne]]====\nThey dated in 3x04.\n\n"
                       "====[[Bram Holloway]]===="), "REVIEW")

case("a ====Partner==== subsection disappears", "character", CHARACTER,
     CHARACTER.replace("====[[Corin Ashby]]====\n"
                       "They married in 6x08 and renewed their vows in 6x12.\n",
                       ""), "REVIEW")

# The season span is (2, 2) before and after, so only comparing the span would
# call this a copyedit and an added citation would pass unmentioned.
case("a citation is added INSIDE the existing season span", "character",
     CHARACTER,
     romantic(CHARACTER, "[[Bram Holloway]]",
              "They married in 2x05, argued in 2x08, and separated in 2x11."),
     "REVIEW")

case("a citation is added outside the span", "character", CHARACTER,
     romantic(CHARACTER, "[[Bram Holloway]]",
              "They married in 2x05 and separated in 11x04."), "REVIEW")

case("an infobox qualifier changes the classification", "character", CHARACTER,
     CHARACTER.replace("''(ex-husband)''", "''(ex-fiance)''"), "REVIEW")

# Fen Marlowe is in no infobox field, so classify() has no qualifier to go on
# and reads the body instead. Same citation, same season -- only the type moves,
# which is the path a qualifier would otherwise mask.
case("a romantic body gains one-night-stand wording", "character", CHARACTER,
     romantic(CHARACTER, "[[Fen Marlowe]]",
              "It was a one-night stand during 8x03."), "REVIEW")

case("|episode= is renumbered", "episode", EPISODE,
     re.sub(r"(\|episode = )\d+", r"\g<1>99", EPISODE), "REVIEW")

case("a citation is added to the Full Summary", "episode", EPISODE,
     EPISODE.replace("They kissed in the elevator",
                     "They kissed in the elevator in 7x13"), "REVIEW")

case("someone new is named in the Full Summary", "episode", EPISODE,
     EPISODE.replace("while Bram", "while Edda Prynne and Bram"), "REVIEW")

case("a stub summary becomes a real one", "episode", STUB_EPISODE, EPISODE,
     "REVIEW")

# --------------------------------------------------------------------------- #
# Must clear
# --------------------------------------------------------------------------- #
case("a trivia section is edited", "character", CHARACTER,
     CHARACTER.replace("* Placeholder.", "* Placeholder, reworded."), "CLEAR")

case("a History section is rewritten", "character", CHARACTER,
     CHARACTER.replace("Placeholder narrative. Nothing reads this, including "
                       "in 4x02.",
                       "An entirely different sentence citing 9x09 and 1x01."),
     "CLEAR")

case("a familial subsection is edited", "character", CHARACTER,
     CHARACTER.replace("Familial, so not a romantic section.",
                       "Rewritten, and citing 5x05."), "CLEAR")

case("whitespace shifts inside a romantic body", "character", CHARACTER,
     CHARACTER.replace("They married in 2x05 and separated in 2x11.",
                       "They  married in 2x05\nand separated in 2x11."),
     "CLEAR")

case("the page is edited and reverted", "character", CHARACTER, CHARACTER,
     "CLEAR")

case("an episode's Notes and Trivia is edited", "episode", EPISODE,
     EPISODE.replace("* Placeholder.", "* Placeholder, reworded."), "CLEAR")

# --------------------------------------------------------------------------- #
# Landed in a read region, but nothing the parsers extract moved
# --------------------------------------------------------------------------- #
case("punctuation is fixed inside a romantic body", "character", CHARACTER,
     CHARACTER.replace("separated in 2x11.", "separated in 2x11"), "COPYEDIT")

case("punctuation is fixed inside a Full Summary", "episode", EPISODE,
     EPISODE.replace("she is leaving.", "she is leaving"), "COPYEDIT")

# Without nodes.csv the named-people comparison cannot run. It must degrade to
# a stated gap, never to a silent pass.
case("no nodes.csv: a copyedit still grades, and says what it skipped",
     "episode", EPISODE, EPISODE.replace("she is leaving.", "she is leaving"),
     "COPYEDIT", people=None)

# --------------------------------------------------------------------------- #
# Guards -- unreadable is never clear
# --------------------------------------------------------------------------- #
case("the baseline revision came back empty", "character", "", CHARACTER,
     "REVIEW")
case("the new revision came back empty", "episode", EPISODE, "", "REVIEW")


# --------------------------------------------------------------------------- #
extra = []
_, notes = rw.classify_edit("episode", EPISODE,
                            EPISODE.replace("she is leaving.", "she is leaving"),
                            None)
if "nodes.csv" not in " ".join(notes):
    extra.append("a run without nodes.csv did not say the name check was skipped")

_, notes = rw.classify_edit("character", CHARACTER, CHARACTER, PEOPLE)
if not any("no-op" in n for n in notes):
    extra.append("an edit-and-revert was cleared without saying it was a no-op")

failed = [r for r in results if not r[0]]
for ok, label, want, got, notes in results:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    print(f"          expected {want}, got {got}")
    for note in notes:
        print(f"          {note}")
for problem in extra:
    print(f"  FAIL  {problem}")

print(f"\n  {len(results) - len(failed)}/{len(results)} graded as expected")
if failed or extra:
    print(f"\n{len(failed) + len(extra)} failing. A grader that clears an edit it "
          f"should escalate loses data silently.")
    sys.exit(1)
print("\nThe grader escalates what it must and clears what it may.")
