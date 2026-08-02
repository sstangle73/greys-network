"""
Grey's Anatomy Relationship Network Generator
=============================================
Builds two CSV datasets suitable for graph tools (Gephi, Cytoscape, NetworkX,
D3, Obsidian Canvas, etc.):

    edges.csv  ->  Source, Target, Relationship_Type, First_Season, First_Episode
    nodes.csv  ->  Character, Status, Image_URL, Death_Season, Death_Episode

Relationship types:
    Married  - legally married at some point in canon
    Dating   - committed / recurring romantic relationship
    Fling    - one-night stand, affair, or short-lived hookup
    Parent   - Source is the parent of Target (biological or legal/adoptive)

SPOILER MODEL
-------------
First_Season / First_Episode mark when a relationship becomes visible to a
viewer -- roughly its first on-screen appearance, not when it was retroactively
explained. Death_Season / Death_Episode do the same for characters. The
visualizer uses these to hide anything past a chosen cutoff.

Episode precision is per-tie, not per-season. Where citations.csv carries a
code for the tie's first season, First_Episode is that episode; otherwise it
falls back to episode 1. That fallback used to be universal outside Season 22
and was invisible on a static chart -- timeline playback made it obvious,
because everything without a real episode pops in on the season boundary.

Where a date is uncertain the entry is deliberately dated LATE: a too-late
tag hides something you've already seen, while a too-early tag spoils you.
That rule also makes the fallback safe in the other direction: taking the
first cited code in a season can only ever land on or after the true episode.

Usage:
    python greys_network.py [--outdir .]
"""

import argparse
import os
from typing import List, Tuple

import pandas as pd

IMAGE_PLACEHOLDER = ""  # swap for "https://placehold.co/200x200" if you prefer

# Show, season and episode in which each character dies on screen. The show tag
# matters as much as the season: Station 19 season 3 is not Grey's season 3, and
# without it a spinoff death would black a character out thirteen years early.
DEATHS = {
    "Denny Duquette": ("GA", 2, 1),
    "Ellis Grey": ("GA", 3, 1),
    "Susan Grey": ("GA", 3, 1),
    "George O'Malley": ("GA", 6, 1),
    "Henry Burton": ("GA", 8, 1),
    "Lexie Grey": ("GA", 8, 1),
    "Mark Sloan": ("GA", 9, 1),
    "Adele Webber": ("GA", 9, 1),
    "Derek Shepherd": ("GA", 11, 1),
    "Thatcher Grey": ("GA", 14, 1),
    "Paul Stadler": ("GA", 14, 1),
    "Andrew DeLuca": ("GA", 17, 1),
    "Monica Beltran": ("GA", 22, 1),
    "Heather Parker": ("PP", 3, 10),
    "Dell Parker": ("PP", 3, 23),
    "Ryan Kerrigan": ("PP", 5, 8),
    "Pete Wilder": ("PP", 6, 1),
    "Ryan Tanner": ("S19", 3, 3),
    "Lucas Ripley": ("S19", 2, 15),
    "Pruitt Herrera": ("S19", 3, 12),
    "Dean Miller": ("S19", 5, 5),
    "Michael Dixon": ("S19", 6, 18),
}

# Explicit child roster. NOTE: deliberately hard-coded rather than "anyone who
# is the target of a Parent edge" -- Meredith, Maggie, Jackson and Molly are all
# Parent targets but are adult characters in the network.
CHILDREN = {
    "Zola Shepherd", "Bailey Shepherd", "Ellis Shepherd",
    "Sofia Robbin Sloan Torres", "Harriet Avery", "Tuck Jones",
    "Scout Lincoln", "Luna Wilson", "Leo Hunt", "Allison Hunt",
    "Farouk Hunt", "Eli Karev", "Alexis Karev", "Sloan Riley",
    "Peyton Lincoln", "Hattie Lincoln",
    # Private Practice
    "Olivia Davis", "Lucas Wilder", "Betsey Parker", "Georgia Freedman",
    "Caroline Freedman", "Rachel Freedman", "Henry Montgomery",
    "Christopher Shepherd",
    # Station 19
    "Pru Miller-Warren", "Liam DeLuca-Bishop",
}

DEFAULT_STATUS = "Alive"

# --------------------------------------------------------------------------- #
# SHOWS
# --------------------------------------------------------------------------- #
# Every date in this file is expressed in the numbering of ONE show. Forcing
# Private Practice and Station 19 dates into Grey's seasons is what produced the
# worst errors in the audit: a "3x05" citation on Carina's page is Station 19
# season 3, which aired opposite Grey's season 16, and the old data recorded it
# as Grey's season 3.
# "episodes" is the longest season in that show, so the episode slider knows how
# far to run. "start" is where each slider opens and "on" whether the show is
# toggled on -- the viewer's own watch position, and the one piece of this file
# that is about a person rather than about canon.
SHOWS = {
    "GA":  {"title": "Grey's Anatomy",   "seasons": 22, "episodes": 27,
            "start": (22, 2), "on": True},
    "S19": {"title": "Station 19",       "seasons": 7,  "episodes": 18,
            "start": (7, 18), "on": True},
    # Owner has watched very little Private Practice but asked for it open
    # anyway. Change "start" to (1, 1) to have it begin hidden instead.
    "PP":  {"title": "Private Practice", "seasons": 6,  "episodes": 23,
            "start": (6, 23), "on": True},
}
DEFAULT_SHOW = "GA"

# Ties whose home show is not Grey's. The home show is where the relationship
# actually plays out, and its stage dates below are in THAT show's numbering.
HOME_SHOW = {
    frozenset({"Carina DeLuca", "Maya Bishop"}): "S19",
}

# When a show OTHER than the home show put a tie on screen, and what stage it
# showed it at. This is what lets a Grey's-only viewer see exactly what Grey's
# told them -- no more, no less.
#
#   (pair, show) -> (season, episode, stage_revealed)
#
# Deliberately sparse: an entry is only added once the reveal has been checked
# against the prose, the same standard as every other date here.
REVEALS = {
    # Grey's carried the whole Jackson/Vic relationship; Station 19 showed it
    # exactly once, when Bailey learned of it at the baby shower.
    (frozenset({"Jackson Avery", "Victoria Hughes"}), "S19"): (3, 1, "Dating"),
    # Grey's never put Maya and Carina on screen together as a couple until
    # after the Station 19 finale. GA 16x14 is only the meet, not a reveal.
    (frozenset({"Carina DeLuca", "Maya Bishop"}), "GA"): (22, 17, "Married"),
    # Station 19 carried the Bailey/Warren sabbatical and its aftermath.
    (frozenset({"Miranda Bailey", "Ben Warren"}), "S19"): (2, 5, "Married"),
    # Addison's Private Practice marriage, referenced on Grey's.
    (frozenset({"Addison Montgomery", "Jake Reilly"}), "GA"): (18, 4, "Married"),
    # Amelia's Private Practice ties: one resolves on Grey's, one is referenced.
    (frozenset({"Amelia Shepherd", "James Peterson"}), "GA"): (10, 22, "Dating"),
    (frozenset({"Amelia Shepherd", "Ryan Kerrigan"}), "GA"): (13, 4, "Dating"),
}

# Ties that began as a hookup before becoming a relationship, and when they
# turned into one. Blank means it was a relationship from its first scene.
# Meredith and Derek are the canonical case: the pilot ends with a one-night
# stand, and she only learns he is her boss the next morning.
GOT_TOGETHER = {
    frozenset({"Meredith Grey", "Derek Shepherd"}): (1, 2),
    frozenset({"Owen Hunt", "Amelia Shepherd"}): (12, 1),
    frozenset({"Owen Hunt", "Teddy Altman"}): (15, 1),
    # Sex in her car in S12 ("At Last", 12x23); only a couple from 13x20 on.
    frozenset({"Meredith Grey", "Nathan Riggs"}): (13, 1),
    # One hookup as a new intern, then an actual relationship in S6.
    frozenset({"Alex Karev", "Lexie Grey"}): (6, 1),
    # The drunken night is S3; they only tried being a couple in S4.
    frozenset({"George O'Malley", "Izzie Stevens"}): (4, 1),
    frozenset({"April Kepner", "Jackson Avery"}): (9, 1),
}

# When each couple actually got married. Relationship_Type records where a tie
# ENDED UP, but a couple who marry in S7 spent six seasons dating first -- without
# this the chart shows them married from their first scene. Couples married before
# the pilot are dated to their first appearance.
WEDDINGS = {
    frozenset({"Meredith Grey", "Derek Shepherd"}): (7, 1),
    frozenset({"Derek Shepherd", "Addison Montgomery"}): (1, 9),
    frozenset({"Addison Montgomery", "Jake Reilly"}): (6, 13),
    frozenset({"Callie Torres", "George O'Malley"}): (3, 14),
    frozenset({"Callie Torres", "Arizona Robbins"}): (7, 1),
    frozenset({"Carina DeLuca", "Maya Bishop"}): (4, 16),
    frozenset({"Izzie Stevens", "Alex Karev"}): (5, 1),
    frozenset({"Alex Karev", "Jo Wilson"}): (14, 1),
    frozenset({"Jo Wilson", "Paul Stadler"}): (13, 1),
    frozenset({"Jo Wilson", "Atticus Lincoln"}): (21, 17),
    frozenset({"Amelia Shepherd", "Owen Hunt"}): (12, 1),
    frozenset({"Owen Hunt", "Cristina Yang"}): (7, 1),
    frozenset({"Owen Hunt", "Teddy Altman"}): (17, 1),
    frozenset({"Teddy Altman", "Henry Burton"}): (7, 1),
    frozenset({"April Kepner", "Jackson Avery"}): (10, 1),
    frozenset({"April Kepner", "Matthew Taylor"}): (14, 1),
    frozenset({"Maggie Pierce", "Winston Ndugu"}): (17, 1),
    frozenset({"Miranda Bailey", "Tucker Jones"}): (1, 1),
    frozenset({"Miranda Bailey", "Ben Warren"}): (9, 1),
    frozenset({"Richard Webber", "Adele Webber"}): (1, 1),
    frozenset({"Richard Webber", "Catherine Fox"}): (11, 1),
    frozenset({"Ellis Grey", "Thatcher Grey"}): (2, 1),
    frozenset({"Thatcher Grey", "Susan Grey"}): (2, 1),
    # Private Practice seasons below this line.
    frozenset({"Violet Turner", "Pete Wilder"}): (4, 1),
    frozenset({"Cooper Freedman", "Charlotte King"}): (4, 20),
    frozenset({"Sheldon Wallace", "Laura Wallace"}): (5, 21),
    frozenset({"Sam Bennett", "Naomi Bennett"}): (6, 13),
    frozenset({"Dell Parker", "Heather Parker"}): (3, 1),
    frozenset({"Maya Bennett", "Fillmore Davis"}): (3, 15),
    # Station 19 seasons below this line.
    frozenset({"Andy Herrera", "Robert Sullivan"}): (3, 12),
    frozenset({"Robert Sullivan", "Natasha Ross"}): (7, 10),
    frozenset({"Michael Dixon", "Kitty Dixon"}): (5, 14),
}

# Marriages that ended in divorce on screen, and when the split aired. Keyed by
# the unordered couple. A marriage ended by death is NOT a divorce -- those
# stay whole hearts, and the dagger on the partner's name tells that story.
DIVORCES = {
    frozenset({"Derek Shepherd", "Addison Montgomery"}): (3, 1),
    frozenset({"Ellis Grey", "Thatcher Grey"}): (2, 1),
    frozenset({"Callie Torres", "George O'Malley"}): (4, 1),
    frozenset({"Callie Torres", "Arizona Robbins"}): (11, 1),
    frozenset({"Izzie Stevens", "Alex Karev"}): (6, 1),
    frozenset({"Alex Karev", "Jo Wilson"}): (16, 1),
    frozenset({"Owen Hunt", "Cristina Yang"}): (9, 1),
    frozenset({"Amelia Shepherd", "Owen Hunt"}): (15, 1),
    frozenset({"Owen Hunt", "Teddy Altman"}): (22, 12),
    frozenset({"April Kepner", "Jackson Avery"}): (12, 1),
    frozenset({"Maggie Pierce", "Winston Ndugu"}): (19, 1),
    frozenset({"Miranda Bailey", "Tucker Jones"}): (6, 1),
    frozenset({"Andy Herrera", "Robert Sullivan"}): (5, 4),
}


# --------------------------------------------------------------------------- #
# EDGE DATA  --  (source, target, type, season[, episode])
# --------------------------------------------------------------------------- #

def _romantic_edges() -> List[Tuple]:
    """(source, target, type, start, end) where start/end are (season, episode).

    end=None means the pair were still together as of the most recent episode.
    Flings end where they start. Marriages end at the divorce or at a death.
    Episode precision only exists for Season 22; earlier entries use episode 1.
    """
    return [
        # --- Meredith Grey ---------------------------------------------------
        ("Meredith Grey", "Derek Shepherd", "Married", (1, 1), (11, 1)),
        ("Meredith Grey", "Finn Dandridge", "Dating", (2, 1), (3, 1)),
        ("Meredith Grey", "George O'Malley", "Fling", (2, 12), (2, 1)),
        ("Meredith Grey", "Steve Murphy", "Fling", (2, 1), (2, 1)),
        ("Meredith Grey", "William Thorpe", "Dating", (12, 13), (12, 1)),
        ("Meredith Grey", "Nathan Riggs", "Dating", (12, 23), (14, 1)),
        ("Meredith Grey", "Andrew DeLuca", "Dating", (15, 1), (16, 1)),
        ("Meredith Grey", "Cormac Hayes", "Dating", (18, 1), (18, 1)),
        ("Meredith Grey", "Nick Marsh", "Dating", (18, 1), None),

        # --- Derek / Addison / Mark ------------------------------------------
        ("Derek Shepherd", "Addison Montgomery", "Married", (1, 9), (3, 1)),
        ("Derek Shepherd", "Rose", "Dating", (4, 1), (5, 1)),
        ("Addison Montgomery", "Mark Sloan", "Fling", (2, 1), (3, 1)),
        ("Addison Montgomery", "Alex Karev", "Fling", (3, 1), (3, 1)),
        ("Mark Sloan", "Lexie Grey", "Dating", (5, 1), (8, 1)),
        ("Mark Sloan", "Callie Torres", "Fling", (3, 1), (7, 1)),
        ("Mark Sloan", "Reed Adamson", "Fling", (6, 1), (6, 1)),
        ("Mark Sloan", "Teddy Altman", "Fling", (6, 22), (6, 1)),
        ("Nicole Herman", "Graham Maddox", "Fling", (11, 1), (11, 1)),
        ("Nicole Herman", "Tom Koracick", "Fling", (14, 1), (14, 1)),
        ("Mark Sloan", "Julia Canner", "Dating", (8, 1), (9, 1)),
        ("Mark Sloan", "Amelia Shepherd", "Fling", (7, 3), (7, 1)),

        # --- Callie / Arizona -------------------------------------------------
        ("Callie Torres", "George O'Malley", "Married", (2, 1), (4, 1)),
        ("Callie Torres", "Erica Hahn", "Dating", (4, 17), (5, 1)),
        ("Callie Torres", "Arizona Robbins", "Married", (5, 14), (12, 1)),
        ("Callie Torres", "Penny Blake", "Dating", (12, 17), (12, 1)),
        ("Arizona Robbins", "Lauren Boswell", "Fling", (9, 23), (9, 1)),
        ("Arizona Robbins", "Leah Murphy", "Fling", (10, 4), (10, 1)),
        ("Arizona Robbins", "Eliza Minnick", "Dating", (13, 1), (13, 1)),
        ("Arizona Robbins", "Carina DeLuca", "Dating", (14, 1), (14, 1)),
        ("Carina DeLuca", "Maya Bishop", "Married", (3, 5), None),

        # --- George / Izzie / Alex --------------------------------------------
        ("George O'Malley", "Olivia Harper", "Dating", (2, 1), (2, 1)),
        ("George O'Malley", "Izzie Stevens", "Dating", (3, 25), (4, 1)),
        ("Izzie Stevens", "Denny Duquette", "Dating", (2, 27), (2, 1)),
        ("Izzie Stevens", "Alex Karev", "Married", (2, 1), (6, 1)),
        ("Alex Karev", "Olivia Harper", "Fling", (2, 1), (2, 1)),
        ("Alex Karev", "Rebecca Pope", "Dating", (4, 1), (4, 1)),
        ("Alex Karev", "Lexie Grey", "Dating", (5, 1), (6, 1)),
        ("Alex Karev", "Reed Adamson", "Fling", (6, 1), (6, 1)),
        ("Alex Karev", "Lucy Fields", "Dating", (7, 1), (7, 1)),
        ("Alex Karev", "Callie Torres", "Fling", (6, 13), (6, 1)),
        ("Alex Karev", "Laurel Pinson", "Fling", (7, 12), (7, 1)),
        ("Alex Karev", "Jo Wilson", "Married", (9, 1), (16, 1)),

        # --- Jo Wilson / Link -------------------------------------------------
        ("Jo Wilson", "Jason Myers", "Dating", (9, 18), (9, 1)),
        ("Jo Wilson", "Paul Stadler", "Married", (13, 12), (14, 1)),
        ("Jo Wilson", "Levi Schmitt", "Fling", (16, 1), (16, 1)),
        ("Jo Wilson", "Todd Eames", "Dating", (18, 1), (18, 1)),
        ("Jo Wilson", "Chris Cleaver", "Dating", (14, 15), (14, 1)),
        ("Jo Wilson", "Atticus Lincoln", "Married", (19, 1), None),
        ("Atticus Lincoln", "Amelia Shepherd", "Dating", (15, 17), (18, 1)),

        # --- Amelia / Owen / Teddy / Cristina ---------------------------------
        ("Amelia Shepherd", "Owen Hunt", "Married", (11, 1), (15, 1)),
        ("Amelia Shepherd", "Tom Koracick", "Fling", (14, 6), (14, 1)),
        ("Amelia Shepherd", "Kai Bartley", "Dating", (18, 8), (19, 1)),
        ("Amelia Shepherd", "Toni Wright", "Dating", (22, 11), (22, 18)),
        ("Amelia Shepherd", "Cass Beckman", "Fling", (22, 18), (22, 18)),
        ("Owen Hunt", "Beth Whitman", "Dating", (5, 1), (5, 1)),
        ("Owen Hunt", "Cristina Yang", "Married", (5, 6), (9, 1)),
        ("Owen Hunt", "Emma Marling", "Dating", (10, 4), (10, 1)),
        ("Owen Hunt", "Teddy Altman", "Married", (14, 1), None),
        ("Owen Hunt", "Carina DeLuca", "Fling", (14, 6), (14, 1)),
        ("Owen Hunt", "Nora", "Fling", (21, 13), (21, 13)),
        ("Teddy Altman", "Henry Burton", "Married", (7, 10), (8, 1)),
        ("Teddy Altman", "Andrew Perkins", "Dating", (7, 1), (7, 1)),
        ("Teddy Altman", "Tom Koracick", "Dating", (15, 12), (17, 1)),
        ("Teddy Altman", "Cass Beckman", "Dating", (21, 6), (21, 18)),
        ("Cristina Yang", "Colin Marlow", "Dating", (2, 1), (2, 1)),
        ("Cristina Yang", "Preston Burke", "Dating", (2, 3), (3, 1)),
        ("Cristina Yang", "Shane Ross", "Fling", (10, 1), (10, 1)),
        ("Cristina Yang", "Darren Parker", "Fling", (9, 3), (9, 1)),

        # --- April / Jackson / Maggie -----------------------------------------
        ("April Kepner", "Robert Stark", "Dating", (7, 1), (7, 1)),
        ("April Kepner", "Jackson Avery", "Married", (8, 22), None),
        ("April Kepner", "Matthew Taylor", "Married", (9, 1), (17, 1)),
        ("April Kepner", "Tom Koracick", "Fling", (14, 15), (14, 1)),
        ("April Kepner", "Vikram Roy", "Fling", (14, 10), (14, 1)),
        ("Jackson Avery", "Lexie Grey", "Dating", (7, 20), (8, 1)),
        ("Jackson Avery", "Mara Keaton", "Fling", (8, 17), (8, 1)),
        ("Jackson Avery", "Stephanie Edwards", "Dating", (9, 10), (10, 1)),
        ("Jackson Avery", "Priya", "Dating", (14, 1), (14, 1)),
        ("Jackson Avery", "Jo Wilson", "Fling", (17, 1), (17, 1)),
        ("Jackson Avery", "Maggie Pierce", "Dating", (14, 14), (16, 1)),
        ("Jackson Avery", "Victoria Hughes", "Dating", (16, 3), (16, 1)),
        ("Maggie Pierce", "Ethan Boyd", "Dating", (11, 1), (12, 1)),
        ("Maggie Pierce", "Dean", "Dating", (11, 10), (11, 1)),
        ("Maggie Pierce", "Andrew DeLuca", "Dating", (12, 3), (12, 1)),
        ("Maggie Pierce", "Clive Johnson", "Dating", (14, 9), (14, 1)),
        ("Maggie Pierce", "Winston Ndugu", "Married", (16, 19), (19, 1)),
        ("Andrew DeLuca", "Sam Bello", "Dating", (14, 1), (14, 1)),

        # --- Bailey / Webber / the older generation ---------------------------
        ("Miranda Bailey", "Tucker Jones", "Married", (1, 1), (6, 1)),
        ("Miranda Bailey", "Eli Lloyd", "Dating", (7, 1), (8, 1)),
        ("Miranda Bailey", "Ben Warren", "Married", (6, 14), None),
        ("Richard Webber", "Adele Webber", "Married", (1, 1), (9, 1)),
        ("Richard Webber", "Ellis Grey", "Fling", (2, 1), (3, 1)),
        ("Richard Webber", "Catherine Fox", "Married", (8, 23), None),
        ("Ellis Grey", "Thatcher Grey", "Married", (2, 1), (2, 1)),
        ("Thatcher Grey", "Susan Grey", "Married", (2, 22), (3, 1)),
        ("Thatcher Grey", "Danielle", "Dating", (7, 14), (7, 1)),

        # --- Riggs / Megan ----------------------------------------------------
        ("Nathan Riggs", "Megan Hunt", "Dating", (14, 5), (18, 1)),

        # --- Residents (S19-S22) ----------------------------------------------
        ("Levi Schmitt", "Nico Kim", "Dating", (15, 6), (18, 1)),
        ("Levi Schmitt", "James Morgan", "Dating", (21, 1), None),
        ("Nico Kim", "Jason Shaheen", "Dating", (20, 3), None),
        ("Atticus Lincoln", "Jules Millin", "Fling", (19, 1), (19, 1)),
        ("Jules Millin", "Mika Yasuda", "Dating", (21, 1), (21, 1)),
        ("Benson Kwan", "Molly Tran", "Dating", (21, 2), (21, 1)),
        ("Lucas Adams", "Cara Ford", "Fling", (19, 10), (19, 1)),
        ("Lucas Adams", "Dani Spencer", "Fling", (22, 16), (22, 16)),
        ("Simone Griffith", "Trey Delgado", "Dating", (19, 1), (19, 1)),
        ("Simone Griffith", "Lucas Adams", "Dating", (19, 9), (22, 2)),
        ("Simone Griffith", "Wes Bryant", "Fling", (21, 17), None),
        ("Lucas Adams", "Katie Rogers", "Dating", (22, 8), None),
        ("Taryn Helm", "Mika Yasuda", "Dating", (19, 9), (20, 1)),
        ("Benson Kwan", "Jules Millin", "Fling", (19, 3), (19, 1)),
        ("Benson Kwan", "Kavita Mohanty", "Dating", (22, 7), (22, 16)),
        ("Winston Ndugu", "Monica Beltran", "Fling", (20, 10), (20, 10)),
        ("Winston Ndugu", "Iris", "Dating", (22, 8), (22, 15)),
        ("Jules Millin", "Winston Ndugu", "Dating", (22, 15), None),
    ]


def _parent_edges() -> List[Tuple]:
    """(parent_a, parent_b, child, season[, episode]) -- season the child appears."""
    pairs = [
        ("Meredith Grey", "Derek Shepherd", "Zola Shepherd", 7),
        ("Meredith Grey", "Derek Shepherd", "Bailey Shepherd", 9),
        ("Meredith Grey", "Derek Shepherd", "Ellis Shepherd", 12),
        ("Callie Torres", "Mark Sloan", "Sofia Robbin Sloan Torres", 7),
        ("Arizona Robbins", None, "Sofia Robbin Sloan Torres", 7),
        ("Mark Sloan", None, "Sloan Riley", 6),
        ("Izzie Stevens", "Alex Karev", "Eli Karev", 16),
        ("Izzie Stevens", "Alex Karev", "Alexis Karev", 16),
        ("Jo Wilson", None, "Luna Wilson", 17),
        ("Amelia Shepherd", "Atticus Lincoln", "Scout Lincoln", 17),
        ("Jo Wilson", "Atticus Lincoln", "Peyton Lincoln", 22, 6),
        ("Jo Wilson", "Atticus Lincoln", "Hattie Lincoln", 22, 6),
        ("Owen Hunt", "Teddy Altman", "Allison Hunt", 16),
        ("Owen Hunt", "Teddy Altman", "Leo Hunt", 15),
        ("April Kepner", "Jackson Avery", "Harriet Avery", 13),
        ("Miranda Bailey", "Tucker Jones", "Tuck Jones", 2),
        ("Richard Webber", "Ellis Grey", "Maggie Pierce", 10),
        ("Ellis Grey", "Thatcher Grey", "Meredith Grey", 1),
        ("Thatcher Grey", "Susan Grey", "Molly Grey", 3),
        ("Thatcher Grey", None, "Lexie Grey", 3),
        ("Catherine Fox", None, "Jackson Avery", 8),
        ("Megan Hunt", "Nathan Riggs", "Farouk Hunt", 14),
    ]

    edges: List[Tuple] = []
    for entry in pairs:
        parent_a, parent_b, child, season = entry[:4]
        episode = entry[4] if len(entry) > 4 else 1
        edges.append((parent_a, child, "Parent", season, episode))
        if parent_b:
            edges.append((parent_b, child, "Parent", season, episode))
    return edges


def _pp_edges() -> List[Tuple]:
    """Private Practice ties. Dates are PP seasons, never Grey's.

    PP ran six seasons opposite Grey's 4-9. Nothing in here is convertible to a
    Grey's season and nothing should be: that conversion is the bug.
    """
    return [
        # --- Addison ---------------------------------------------------------
        # S1 is meeting only -- he asks her out in 1x07 and she declines, then
        # stands her up at 2x01. The tie starts when they actually sleep together.
        ("Addison Montgomery", "Kevin Nelson", "Dating", (2, 4), (2, 13)),
        ("Addison Montgomery", "Pete Wilder", "Dating", (3, 1), (3, 23)),
        ("Addison Montgomery", "Sam Bennett", "Dating", (4, 1), (5, 22)),
        ("Addison Montgomery", "Jake Reilly", "Married", (4, 22), None),

        # --- Violet / Pete ---------------------------------------------------
        ("Violet Turner", "Pete Wilder", "Married", (2, 1), (6, 1)),
        ("Violet Turner", "Sheldon Wallace", "Dating", (2, 8), (2, 22)),
        ("Violet Turner", "The Captain Montgomery", "Fling", (3, 9), (3, 9)),
        ("Violet Turner", "Scott Becker", "Dating", (5, 11), (5, 17)),
        ("Violet Turner", "Allan", "Dating", (1, 5), (1, 5)),
        ("Pete Wilder", "Meg Porter", "Dating", (1, 1), (2, 1)),
        ("Pete Wilder", "Lisa King", "Dating", (2, 1), (2, 22)),

        # --- Cooper / Charlotte ----------------------------------------------
        ("Cooper Freedman", "Charlotte King", "Married", (1, 8), None),
        ("Charlotte King", "Sheldon Wallace", "Fling", (3, 16), (3, 22)),
        ("Charlotte King", "Archer Montgomery", "Fling", (2, 17), (2, 17)),

        # --- Sheldon ---------------------------------------------------------
        ("Sheldon Wallace", "Laura Wallace", "Married", (5, 21), (6, 9)),
        ("Sheldon Wallace", "Miranda", "Dating", (6, 9), None),

        # --- Sam / Naomi -----------------------------------------------------
        # Married before the series, divorced before it too; the on-screen arc
        # is the rekindling at 1x07 through to remarrying in the finale.
        ("Sam Bennett", "Naomi Bennett", "Married", (1, 7), None),
        ("Sam Bennett", "Sonya Nichols", "Dating", (2, 12), (2, 22)),
        ("Sam Bennett", "Stephanie Kemp", "Dating", (6, 1), (6, 13)),
        ("Naomi Bennett", "Archer Montgomery", "Fling", (2, 7), (4, 14)),
        ("Naomi Bennett", "William White", "Dating", (3, 14), (4, 1)),
        ("Naomi Bennett", "Gabriel Fife", "Dating", (4, 22), (6, 13)),

        # --- Dell / Maya -----------------------------------------------------
        ("Dell Parker", "Heather Parker", "Married", (3, 10), (3, 10)),
        ("Maya Bennett", "Fillmore Davis", "Married", (3, 9), None),

        # --- Amelia's Private Practice years ---------------------------------
        ("Amelia Shepherd", "Ryan Kerrigan", "Dating", (5, 6), (5, 8)),
        # Starts here and resolves on Grey's (10x22 engagement, 10x23 breakup).
        # The model carries stage dates in ONE show, so the PP end is the last
        # PP episode they are together in; the Grey's side is a reveal.
        ("Amelia Shepherd", "James Peterson", "Dating", (6, 1), (6, 13)),
    ]


def _s19_edges() -> List[Tuple]:
    """Station 19 ties. Dates are Station 19 seasons, never Grey's.

    S19 ran seven seasons opposite Grey's 14-20. Several pages here cite episode
    TITLES with no code, and a few carry outright numbering errors, so anything
    uncertain is dated late and flagged rather than guessed precisely.
    """
    return [
        # --- Andy / Sullivan -------------------------------------------------
        ("Andy Herrera", "Ryan Tanner", "Fling", (1, 7), (2, 10)),
        ("Andy Herrera", "Jack Gibson", "Dating", (1, 1), (1, 5)),
        ("Andy Herrera", "Robert Sullivan", "Married", (2, 17), (5, 4)),
        ("Andy Herrera", "Sean Beckett", "Fling", (5, 2), (5, 2)),
        # The wedding is asserted in three places and cited in none -- Sullivan's
        # own "Romance with Natasha" heading is an empty stub. Dated to their
        # last appearance, which is the latest defensible point.
        ("Robert Sullivan", "Natasha Ross", "Married", (5, 11), None),

        # --- Maya / Jack -----------------------------------------------------
        ("Maya Bishop", "Charlotte Dearborn", "Fling", (1, 10), (1, 10)),
        ("Maya Bishop", "Jack Gibson", "Dating", (2, 10), (3, 15)),
        ("Jack Gibson", "Inara", "Dating", (4, 16), (4, 16)),
        ("Jack Gibson", "Eva Vasquez", "Fling", (6, 10), (6, 10)),

        # --- Victoria Hughes -------------------------------------------------
        ("Victoria Hughes", "David Mayhorn", "Fling", (2, 3), (2, 8)),
        ("Victoria Hughes", "Lucas Ripley", "Dating", (2, 5), (2, 15)),
        ("Victoria Hughes", "Theo Ruiz", "Dating", (4, 8), (6, 18)),

        # --- Travis ----------------------------------------------------------
        ("Travis Montgomery", "Grant", "Dating", (1, 9), (2, 8)),
        ("Travis Montgomery", "Emmett Dixon", "Dating", (3, 7), (7, 2)),
        ("Travis Montgomery", "Eli Stern", "Dating", (6, 13), (7, 3)),

        # --- Dean ------------------------------------------------------------
        ("Dean Miller", "Tiffany", "Fling", (1, 1), (1, 1)),
        ("Dean Miller", "JJ Lau", "Dating", (1, 5), (3, 7)),
        ("Dean Miller", "Nikki", "Dating", (2, 14), (2, 17)),
        ("Dean Miller", "Sasha Bennett", "Dating", (3, 16), (4, 2)),

        # --- others ----------------------------------------------------------
        ("Emmett Dixon", "Alicia", "Dating", (3, 11), (3, 15)),
        ("Theo Ruiz", "Blanca", "Dating", (7, 10), None),
        ("Michael Dixon", "Kitty Dixon", "Married", (5, 14), (6, 18)),
    ]


def _pp_parent_edges() -> List[Tuple]:
    """(parent_a, parent_b, child, season, episode) in PRIVATE PRACTICE seasons."""
    pairs = [
        ("Sam Bennett", "Naomi Bennett", "Maya Bennett", 1, 1),
        ("Maya Bennett", "Fillmore Davis", "Olivia Davis", 3, 23),
        ("Pete Wilder", "Violet Turner", "Lucas Wilder", 2, 22),
        ("Cooper Freedman", "Charlotte King", "Georgia Freedman", 6, 8),
        ("Cooper Freedman", "Charlotte King", "Caroline Freedman", 6, 12),
        ("Cooper Freedman", "Charlotte King", "Rachel Freedman", 6, 12),
        ("Dell Parker", "Heather Parker", "Betsey Parker", 1, 1),
        ("Addison Montgomery", "Jake Reilly", "Henry Montgomery", 5, 22),
        ("Amelia Shepherd", "Ryan Kerrigan", "Christopher Shepherd", 5, 22),
        ("The Captain Montgomery", None, "Addison Montgomery", 3, 9),
        ("The Captain Montgomery", None, "Archer Montgomery", 3, 9),
    ]
    edges: List[Tuple] = []
    for parent_a, parent_b, child, season, episode in pairs:
        edges.append((parent_a, child, "Parent", season, episode))
        if parent_b:
            edges.append((parent_b, child, "Parent", season, episode))
    return edges


def _s19_parent_edges() -> List[Tuple]:
    """(parent_a, parent_b, child, season, episode) in STATION 19 seasons."""
    pairs = [
        ("Dean Miller", "JJ Lau", "Pru Miller-Warren", 3, 6),
        ("Pruitt Herrera", None, "Andy Herrera", 1, 5),
        ("Maya Bishop", "Carina DeLuca", "Liam DeLuca-Bishop", 7, 2),
        ("Michael Dixon", "Kitty Dixon", "Emmett Dixon", 3, 4),
    ]
    edges: List[Tuple] = []
    for parent_a, parent_b, child, season, episode in pairs:
        edges.append((parent_a, child, "Parent", season, episode))
        if parent_b:
            edges.append((parent_b, child, "Parent", season, episode))
    return edges


def _show_of(source: str, target: str) -> str:
    return HOME_SHOW.get(frozenset({source, target}), DEFAULT_SHOW)


def _reveals_of(source: str, target: str, home: str) -> str:
    """Pack the cross-show reveals into one field: 'GA:16x14:Dating;...'.

    One column rather than three-per-show keeps nodes.csv/edges.csv readable in
    Gephi and friends, and the visualizer only has to split on two characters.
    """
    pair = frozenset({source, target})
    parts = []
    for show in SHOWS:
        if show == home:
            continue
        hit = REVEALS.get((pair, show))
        if hit:
            parts.append(f"{show}:{hit[0]}x{hit[1]:02d}:{hit[2]}")
    return ";".join(parts)


def build_edges() -> pd.DataFrame:
    """Assemble the full edge list, normalizing the optional episode field."""
    records = []
    # A tie's show comes from the list it is declared in. HOME_SHOW only covers
    # the handful of cross-show ties that sit in the Grey's list for historical
    # reasons; new spinoff ties go straight into _pp_edges()/_s19_edges().
    sources = [(_romantic_edges(), None), (_pp_edges(), "PP"), (_s19_edges(), "S19")]
    for rows, forced in sources:
        for source, target, rtype, start, end in rows:
            show = forced or _show_of(source, target)
            records.append((source, target, rtype, show, start[0], start[1],
                            end[0] if end else "", end[1] if end else "",
                            _reveals_of(source, target, show)))
    parent_sources = [(_parent_edges(), DEFAULT_SHOW), (_pp_parent_edges(), "PP"),
                      (_s19_parent_edges(), "S19")]
    for rows, show in parent_sources:
        for source, target, rtype, season, episode in rows:
            # Parenthood has no end date.
            records.append((source, target, rtype, show, season, episode,
                            "", "", ""))

    df = pd.DataFrame(
        records,
        columns=["Source", "Target", "Relationship_Type", "Show",
                 "First_Season", "First_Episode", "Last_Season", "Last_Episode",
                 "Reveals"],
    )
    df = df.drop_duplicates().reset_index(drop=True)

    def outcome(row, field):
        split = DIVORCES.get(frozenset({row.Source, row.Target}))
        if not split or row.Relationship_Type != "Married":
            return ""
        return {"label": "Divorced", "season": split[0], "episode": split[1]}[field]

    def steady(row, idx):
        if row.Relationship_Type not in ("Dating", "Married"):
            return ""
        date = GOT_TOGETHER.get(frozenset({row.Source, row.Target}))
        return date[idx] if date else ""

    def wedding(row, idx):
        if row.Relationship_Type != "Married":
            return ""
        date = WEDDINGS.get(frozenset({row.Source, row.Target}))
        return date[idx] if date else ""

    df["Dating_Season"] = [steady(r, 0) for r in df.itertuples()]
    df["Dating_Episode"] = [steady(r, 1) for r in df.itertuples()]
    df["Married_Season"] = [wedding(r, 0) for r in df.itertuples()]
    df["Married_Episode"] = [wedding(r, 1) for r in df.itertuples()]
    df["Outcome"] = [outcome(r, "label") for r in df.itertuples()]
    df["Outcome_Season"] = [outcome(r, "season") for r in df.itertuples()]
    df["Outcome_Episode"] = [outcome(r, "episode") for r in df.itertuples()]
    return df


# --------------------------------------------------------------------------- #
# NODE DATA
# --------------------------------------------------------------------------- #

def classify_status(character: str) -> str:
    """Present-day status. Point-in-time status is derived by the visualizer."""
    if character in DEATHS:
        return "Deceased"
    if character in CHILDREN:
        return "Child"
    return DEFAULT_STATUS


def build_nodes(edges: pd.DataFrame) -> pd.DataFrame:
    names = pd.unique(edges[["Source", "Target"]].values.ravel())
    df = pd.DataFrame({"Character": sorted(names)})
    df["Status"] = df["Character"].apply(classify_status)
    # Left blank on purpose. Portraits are a LOCAL presentation asset, not data:
    # baking cache paths in here would make the published nodes.csv depend on
    # whether someone had run fetch_portraits.py. build_visualization.py reads
    # the manifest at render time instead.
    df["Image_URL"] = IMAGE_PLACEHOLDER
    # A death is an event in one show, so it needs the same show tag an edge
    # does -- otherwise Station 19 season 3 would black out a Grey's character.
    df["Death_Show"] = df["Character"].map(lambda c: DEATHS.get(c, ("", "", ""))[0])
    df["Death_Season"] = df["Character"].map(lambda c: DEATHS.get(c, ("", "", ""))[1])
    df["Death_Episode"] = df["Character"].map(lambda c: DEATHS.get(c, ("", "", ""))[2])
    return df


# --------------------------------------------------------------------------- #
# VALIDATION + EXPORT
# --------------------------------------------------------------------------- #

def validate(edges: pd.DataFrame, nodes: pd.DataFrame) -> None:
    assert not edges.isnull().values.any(), "Null value found in edges"

    began = edges[edges["Dating_Season"] != ""]
    assert (began["Dating_Season"].astype(int) >= began["First_Season"]).all(), \
        "A relationship is dated before the pair first got involved"

    weds = edges[edges["Relationship_Type"] == "Married"]
    assert (weds["Married_Season"] != "").all(), "A marriage with no wedding date"
    assert (weds["Married_Season"].astype(int) >= weds["First_Season"]).all(), \
        "A wedding is dated before the couple got together"

    # Built once. This used to be rebuilt inside the loop below, and it compared
    # against EVERY edge rather than the married ones -- so a wedding recorded
    # against a Dating or Fling edge slipped through the check that exists to
    # catch exactly that.
    married_pairs = {frozenset(p) for p in zip(weds["Source"], weds["Target"])}
    for couple in WEDDINGS:
        assert couple in married_pairs, \
            f"Wedding recorded for a couple with no Married edge: {set(couple)}"

    ongoing = edges["Last_Season"] == ""
    ends = edges[~ongoing]
    assert (ends["Last_Season"].astype(int) >= ends["First_Season"]).all(), \
        "A relationship ends before it starts"

    allowed = {"Married", "Dating", "Fling", "Parent"}
    bad = set(edges["Relationship_Type"]) - allowed
    assert not bad, f"Unexpected relationship type(s): {bad}"

    bad_show = set(edges["Show"]) - set(SHOWS)
    assert not bad_show, f"Unknown show(s): {bad_show}"
    # Each show has its own season count, so a single 1-22 check would wave
    # through a Private Practice tie dated to season 9.
    for show, meta in SHOWS.items():
        rows = edges[edges["Show"] == show]
        assert rows["First_Season"].between(1, meta["seasons"]).all(), \
            f"{show} season out of range 1-{meta['seasons']}"
    assert edges["First_Episode"].between(1, 27).all(), "Episode out of range"

    # Read the home show off the edge itself. HOME_SHOW only covers the few
    # cross-show ties that still live in the Grey's list; anything declared in
    # _pp_edges()/_s19_edges() is tagged by the list it came from, and looking
    # it up here instead reported every PP tie's Grey's reveal as self-referential.
    home_of = {frozenset({s, t}): show for s, t, show in
               zip(edges["Source"], edges["Target"], edges["Show"])}
    for (pair, show), value in REVEALS.items():
        assert show in SHOWS, f"Reveal on unknown show {show}: {set(pair)}"
        assert pair in home_of, f"Reveal for a pair with no edge: {set(pair)}"
        assert show != home_of[pair], \
            f"Reveal recorded on a tie's own home show: {set(pair)}"
        assert value[0] <= SHOWS[show]["seasons"], \
            f"Reveal season out of range for {show}: {set(pair)}"

    missing = (set(edges["Source"]) | set(edges["Target"])) - set(nodes["Character"])
    assert not missing, f"Characters missing from nodes.csv: {missing}"

    unknown = set(DEATHS) - set(nodes["Character"])
    assert not unknown, f"Death recorded for someone not in the network: {unknown}"

    # A character can't die before they first show up in a relationship -- but
    # the comparison has to happen WITHIN one show. Someone who dies on Station
    # 19 in season 3 has not "died before appearing" merely because their only
    # other tie is a Grey's season 16 one.
    first_seen = (
        pd.concat([
            edges[["Source", "Show", "First_Season"]].rename(columns={"Source": "c"}),
            edges[["Target", "Show", "First_Season"]].rename(columns={"Target": "c"}),
        ])
        .groupby(["c", "Show"])["First_Season"].min()
    )
    for name, (show, season, _) in DEATHS.items():
        if (name, show) not in first_seen.index:
            # Their only ties are in another show; nothing to contradict.
            continue
        assert season >= first_seen[(name, show)], \
            f"{name} dies ({show} S{season}) before first appearing in {show}"

    split = edges[edges["Outcome"] == "Divorced"]
    assert (split["Outcome_Season"] >= split["Married_Season"]).all(), \
        "A divorce is dated before the wedding"
    for couple in DIVORCES:
        assert couple in married_pairs, \
            f"Divorce recorded for a couple with no Married edge: {set(couple)}"

    # GOT_TOGETHER only reaches the CSV for Dating/Married rows, so an entry
    # against a Fling is silently discarded -- which looks like the date simply
    # failed to apply. Nothing caught this before.
    steady_pairs = {frozenset(p) for p in
                    zip(edges.loc[edges["Relationship_Type"].isin(("Dating", "Married")), "Source"],
                        edges.loc[edges["Relationship_Type"].isin(("Dating", "Married")), "Target"])}
    for couple in GOT_TOGETHER:
        assert couple in steady_pairs, \
            f"Got-together date on a couple with no Dating/Married edge: {set(couple)}"

    # One romantic edge per pair. drop_duplicates() only catches rows that match
    # exactly, so when the Private Practice ties were moved into _pp_edges() and
    # the originals were left behind in the Grey's list, three couples were drawn
    # twice with different dates and nothing complained.
    romantic = edges[edges["Relationship_Type"] != "Parent"]
    pairs = [frozenset(p) for p in zip(romantic["Source"], romantic["Target"])]
    twice = {tuple(sorted(p)) for p in pairs if pairs.count(p) > 1}
    assert not twice, f"Pair with more than one romantic edge: {sorted(twice)}"

    parented = set(edges.loc[edges["Relationship_Type"] == "Parent", "Target"])
    orphans = CHILDREN - parented
    if orphans:
        print(f"  ! Warning - child with no Parent edge: {sorted(orphans)}")


def build_shows() -> pd.DataFrame:
    """The show registry, so the visualizer does not have to redeclare it."""
    return pd.DataFrame([
        {"Key": key, "Title": meta["title"], "Seasons": meta["seasons"],
         "Episodes": meta["episodes"], "Start_Season": meta["start"][0],
         "Start_Episode": meta["start"][1], "Enabled": int(meta["on"])}
        for key, meta in SHOWS.items()
    ])


def export(edges: pd.DataFrame, nodes: pd.DataFrame, outdir: str = ".") -> None:
    os.makedirs(outdir, exist_ok=True)
    edges.to_csv(os.path.join(outdir, "edges.csv"), index=False)
    nodes.to_csv(os.path.join(outdir, "nodes.csv"), index=False)
    build_shows().to_csv(os.path.join(outdir, "shows.csv"), index=False)


def main(outdir: str = ".") -> None:
    edges = build_edges()
    nodes = build_nodes(edges)
    validate(edges, nodes)
    export(edges, nodes, outdir)

    print(f"Wrote {len(edges)} edges and {len(nodes)} nodes to {os.path.abspath(outdir)}")
    print("\nEdges by type:")
    print(edges["Relationship_Type"].value_counts().to_string())
    married = (edges["Relationship_Type"] == "Married").sum()
    print(f"\nMarriages: {married}, of which {(edges['Outcome'] == 'Divorced').sum()} ended in divorce")
    live = (edges["Last_Season"] == "") & (edges["Relationship_Type"] != "Parent")
    print(f"\nRomantic ties still going as of the latest episode: {live.sum()}")
    print("\nVisible through S22 E02:")
    cut = edges[(edges["First_Season"] < 22) |
                ((edges["First_Season"] == 22) & (edges["First_Episode"] <= 2))]
    print(f"  {len(cut)} of {len(edges)} edges ({len(edges) - len(cut)} hidden as spoilers)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Grey's Anatomy network CSVs.")
    parser.add_argument("--outdir", default=".", help="Directory for the CSV output")
    args = parser.parse_args()
    main(args.outdir)
