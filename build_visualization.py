"""
Grey's Anatomy Network Visualizer
=================================
Reads nodes.csv + edges.csv and emits a single self-contained HTML file with a
force-directed graph (D3 v7 from CDN, everything else inlined).

The CSVs stay the source of truth -- edit them (or greys_network.py), re-run
this, and the visualization updates. Image_URL values, once you fill them in,
are rendered as circular node portraits automatically.

Usage:
    python build_visualization.py --indir . --out greys_network.html
"""

import argparse
import json
import os

import pandas as pd

D3_CDN = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"


# --------------------------------------------------------------------------- #
# Data prep
# --------------------------------------------------------------------------- #

def load_graph(indir: str) -> dict:
    """Read the CSVs and shape them into the JSON payload the page expects."""
    nodes = pd.read_csv(os.path.join(indir, "nodes.csv")).fillna("")
    edges = pd.read_csv(os.path.join(indir, "edges.csv")).fillna("")
    shows = pd.read_csv(os.path.join(indir, "shows.csv")).fillna("")

    # Portraits are a local cache, not part of the dataset -- nodes.csv stays
    # portable and the page picks them up only where they actually exist.
    manifest = os.path.join(indir, "portraits", "manifest.csv")
    faces = {}
    if os.path.exists(manifest):
        faces = dict(pd.read_csv(manifest).fillna("")
                     [["Character", "File"]].itertuples(index=False, name=None))

    # Degree drives node size, so the network's gravitational centers are obvious.
    degree = (
        pd.concat([edges["Source"], edges["Target"]])
        .value_counts()
        .to_dict()
    )

    def as_int(value):
        """Death_Season/Episode are blank for the living."""
        return int(value) if str(value).strip() not in ("", "nan") else None

    node_payload = [
        {
            "id": row.Character,
            "status": row.Status,
            "image": row.Image_URL or faces.get(row.Character, ""),
            "degree": int(degree.get(row.Character, 0)),
            "dshow": row.Death_Show or "GA",
            "ds": as_int(row.Death_Season),
            "de": as_int(row.Death_Episode),
        }
        for row in nodes.itertuples()
    ]

    def unpack(field):
        """'S19:3x05:Dating;GA:16x14:Married' -> [{show, s, e, stage}, ...]"""
        out = []
        for chunk in str(field).split(";"):
            if not chunk.strip():
                continue
            show, code, stage = chunk.split(":")
            season, _, episode = code.partition("x")
            out.append({"show": show, "s": int(season), "e": int(episode),
                        "stage": stage})
        return out

    link_payload = [
        {
            "source": row.Source,
            "target": row.Target,
            "type": row.Relationship_Type,
            "show": row.Show,
            "reveals": unpack(row.Reveals),
            "ek": int(row.Episode_Known),
            "eek": int(row.End_Episode_Known),
            "s": int(row.First_Season),
            "e": int(row.First_Episode),
            "ls": as_int(row.Last_Season),
            "le": as_int(row.Last_Episode),
            "gs": as_int(row.Dating_Season),
            "ge": as_int(row.Dating_Episode),
            "ms": as_int(row.Married_Season),
            "me": as_int(row.Married_Episode),
            "split": row.Outcome == "Divorced",
            "ss": as_int(row.Outcome_Season),
            "se": as_int(row.Outcome_Episode),
        }
        for row in edges.itertuples()
    ]

    show_payload = [
        {"key": row.Key, "title": row.Title, "seasons": int(row.Seasons),
         "episodes": int(row.Episodes), "s": int(row.Start_Season),
         "e": int(row.Start_Episode), "on": bool(int(row.Enabled))}
        for row in shows.itertuples()
    ]

    return {"nodes": node_payload, "links": link_payload, "shows": show_payload}


# --------------------------------------------------------------------------- #
# Page template
# --------------------------------------------------------------------------- #

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Grey Sloan Relationship Chart</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700&family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<script src="__D3_CDN__"></script>
<style>
  :root {
    --ground:   #0B2B2E;
    --panel:    #10393D;
    --rule:     #1F5457;
    --bone:     #E8EDE9;
    --muted:    #7FA3A0;
    /* Four hues roughly 90 degrees apart, chosen so the categories survive
       red-green colour blindness and stay distinct in greyscale. Parent used
       to be mint green, which paired with the red Fling into the single most
       common confusion there is. Every type also carries a second cue -- a
       dash pattern and a mid-edge glyph -- so colour is never load-bearing. */
    --married:  #E8B84B;   /* gold    solid,  heart  */
    --dating:   #4FC3D9;   /* cyan    solid,  ...    */
    --fling:    #E0576E;   /* magenta dashed, 1      */
    --parent:   #9B8CE0;   /* violet  dotted, no glyph */
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; height: 100%;
    background: var(--ground);
    color: var(--bone);
    font-family: 'Source Sans 3', system-ui, sans-serif;
    overflow: hidden;
  }
  #chart {
    position: fixed; inset: 0;
    width: 100%; height: 100%;   /* <svg> is a replaced element -- without an
                                    explicit size it falls back to its intrinsic
                                    300x150 and clips everything outside it */
    display: block; touch-action: none;
  }

  /* --- masthead ---------------------------------------------------------- */
  header {
    position: fixed; top: 0; left: 0; right: 0; z-index: 5;
    padding: 18px 24px 14px;
    background: linear-gradient(to bottom, rgba(11,43,46,.96), rgba(11,43,46,0));
    pointer-events: none;
  }
  h1 {
    margin: 0; font-family: 'Archivo', sans-serif; font-weight: 700;
    font-size: 20px; letter-spacing: .22em; text-transform: uppercase;
  }
  .sub {
    margin-top: 5px; font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: var(--muted); letter-spacing: .06em;
  }
  .trace { display: block; margin-top: 10px; height: 14px; width: min(420px, 60vw); }
  /* In the masthead rather than buried in the credits: the table is the
     accessible form of this page, so it has to be reachable without first
     operating an SVG force graph to find it.

     pointer-events must be re-enabled explicitly. The header sets
     pointer-events:none on purpose, so that dragging the graph still works in
     the strip underneath it -- which meant this link rendered perfectly and
     silently swallowed every click. */
  .alt-view {
    color: var(--dating); text-decoration: none;
    border-bottom: 1px solid currentColor;
    pointer-events: auto;
  }
  .alt-view:hover { color: var(--bone); }

  /* --- controls ---------------------------------------------------------- */
  .rail {
    position: fixed; left: 24px; bottom: 24px; z-index: 5;
    width: 232px; padding: 16px;
    background: rgba(16,57,61,.92); border: 1px solid var(--rule);
    backdrop-filter: blur(6px);
    /* The rail is anchored to its BOTTOM edge and grows upward. With enough
       content its top -- including the collapse button -- rises past the top of
       the viewport, where nothing can reach it and you are stranded inside the
       panel. Going from one cutoff block to three, plus the trace form, was
       enough to cross that line. Cap the height and scroll the body instead. */
    display: flex; flex-direction: column;
    max-height: calc(100vh - 48px);
  }
  /* Never scrolls away: it is the only way back out. */
  .rail-toggle { flex: 0 0 auto; }
  /* Three groups plus a reference sheet, rather than one very tall column.
     Only one is mounted at a time, which is what keeps the rail short enough
     that its top -- and its collapse button -- stay on screen. */
  .tabs { display: flex; gap: 4px; flex: 0 0 auto; margin-bottom: 12px; }
  .tabs button {
    flex: 1; padding: 7px 4px;
    background: none; border: 1px solid var(--rule); color: var(--muted);
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    letter-spacing: .12em; text-transform: uppercase; cursor: pointer;
  }
  .tabs button[data-tab="key"] { flex: 0 0 32px; letter-spacing: 0; }
  .tabs button[aria-selected="true"] {
    background: var(--rule); color: var(--bone);
  }
  .rail.collapsed .tabs { display: none; }
  .play-form { display: flex; gap: 6px; margin-bottom: 14px; }
  .play-form select {
    flex: 1; min-width: 0; padding: 7px 8px;
    background: var(--ground); border: 1px solid var(--rule); color: var(--bone);
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  }
  .play-form button {
    flex: 0 0 66px; background: var(--rule); color: var(--bone); border: 0;
    border-radius: 3px; font-family: 'Archivo', sans-serif; font-size: 11px;
    letter-spacing: .06em; text-transform: uppercase; cursor: pointer;
  }
  .play-form button[aria-pressed="true"] { background: var(--fling); color: var(--ground); }
  /* Transport sits top-centre: the rail owns bottom-left, the fit button
     bottom/top-right, and the masthead top-left. */
  .transport {
    position: fixed; top: 92px; left: 50%; transform: translateX(-50%); z-index: 5;
    display: flex; align-items: center; gap: 10px;
    padding: 7px 12px 7px 8px;
    background: rgba(16,57,61,.92); border: 1px solid var(--rule);
    backdrop-filter: blur(6px);
  }
  .transport button {
    flex: 0 0 auto; width: 26px; height: 26px; padding: 0;
    background: var(--rule); border: 0; border-radius: 50%; color: var(--bone);
    font-size: 11px; line-height: 1; cursor: pointer;
  }
  .transport button[aria-pressed="true"] { background: var(--fling); color: var(--ground); }
  .transport-read {
    display: flex; gap: 12px;
    font-family: 'Archivo', sans-serif; font-weight: 700; font-size: 14px;
    letter-spacing: .08em; white-space: nowrap;
  }
  .transport-read .unit { display: flex; align-items: baseline; gap: 5px; }
  .transport-read .who {
    font-family: 'IBM Plex Mono', monospace; font-weight: 400; font-size: 9px;
    letter-spacing: .12em; color: var(--muted); text-transform: uppercase;
  }
  .transport-read .idle { color: var(--muted); }
  @media (max-width: 720px) {
    .transport { top: auto; bottom: 12px; left: 12px; right: 12px; transform: none; }
    .rail.collapsed ~ .transport { bottom: 64px; }
    .rail:not(.collapsed) ~ .transport { display: none; }
    .transport-read { font-size: 12px; gap: 8px; overflow-x: auto; }
  }
  .rail-body {
    overflow-y: auto; min-height: 0;
    overscroll-behavior: contain;      /* don't scroll the page behind it */
    -webkit-overflow-scrolling: touch;
  }
  .rail h2 {
    margin: 0 0 10px; font-family: 'IBM Plex Mono', monospace; font-weight: 500;
    font-size: 10px; letter-spacing: .18em; text-transform: uppercase; color: var(--muted);
  }
  .rail-toggle {
    display: none; width: 100%; padding: 9px;
    background: none; border: 1px solid var(--rule); color: var(--bone);
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    letter-spacing: .16em; text-transform: uppercase; cursor: pointer;
  }
  .rail.collapsed .rail-body { display: block; }
  /* Lives inside the transport. It used to float independently, which meant
     three separately-positioned things competing for the bottom of a phone
     screen -- and the fit button landed on top of the transport. One cluster
     cannot overlap itself. */
  .btn-fit {
    flex: 0 0 auto; margin-left: 2px;
    padding: 6px 10px; background: none;
    border: 1px solid var(--rule); border-radius: 3px; color: var(--bone);
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    letter-spacing: .14em; text-transform: uppercase; cursor: pointer;
  }
  .btn-fit:hover { border-color: var(--bone); }
  .cutoff { margin-bottom: 16px; }
  /* One block per show. A show that is toggled off keeps its sliders visible
     but faded, so you can see where you left it without turning it back on. */
  .show-block { margin-bottom: 12px; }
  .show-block + .show-block {
    border-top: 1px solid var(--rule); padding-top: 10px;
  }
  .show-block.off { opacity: .42; }
  .show-block.off input[type=range] { pointer-events: none; }
  .show-head {
    display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px;
    cursor: pointer;
  }
  .show-head input { accent-color: var(--dating); margin: 0; align-self: center; }
  .show-title {
    font-family: 'Source Sans 3', sans-serif; font-size: 12px; color: var(--muted);
  }
  .cutoff-read {
    font-family: 'Archivo', sans-serif; font-weight: 700; font-size: 19px;
    letter-spacing: .1em; margin-bottom: 8px;
  }
  .show-head .cutoff-read { margin: 0 0 0 auto; font-size: 15px; }
  .slider-row {
    display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--muted);
  }
  .slider-row span { width: 52px; flex: none; }
  .slider-row input { flex: 1; accent-color: var(--fling); min-width: 0; }
  .cutoff-note {
    margin-top: 7px; font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; line-height: 1.5; color: var(--fling);
  }
  #search, .trace-form input {
    width: 100%; margin-bottom: 14px; padding: 8px 10px;
    background: var(--ground); border: 1px solid var(--rule); color: var(--bone);
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
  }
  .trace-form input { margin-bottom: 0; }
  .to-table {
    display: block; margin-top: 16px; padding-top: 12px;
    border-top: 1px solid var(--rule); color: var(--dating);
    font-size: 11px; letter-spacing: .04em; text-decoration: none;
  }
  .to-table:hover, .to-table:focus-visible { text-decoration: underline; }
  .linkish {
    display: block; margin-top: 8px; padding: 0;
    background: none; border: 0; color: var(--dating); cursor: pointer;
    font-family: inherit; font-size: inherit; text-decoration: underline;
  }
  #report {
    width: min(440px, calc(100vw - 32px)); padding: 20px; border: 1px solid var(--rule);
    background: var(--panel); color: var(--bone);
  }
  #report::backdrop { background: rgba(4,20,22,.72); }
  #report h2 {
    margin: 0 0 8px; font-family: 'Archivo', sans-serif; font-size: 16px;
    letter-spacing: .04em; text-transform: none; color: var(--bone);
  }
  .report-intro { margin: 0 0 14px; font-size: 12.5px; line-height: 1.5; color: var(--muted); }
  #report label {
    display: block; margin: 0 0 5px;
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    letter-spacing: .14em; text-transform: uppercase; color: var(--muted);
  }
  #report select, #report textarea {
    width: 100%; margin-bottom: 14px; padding: 8px 10px;
    background: var(--ground); border: 1px solid var(--rule); color: var(--bone);
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; resize: vertical;
  }
  #report select:focus, #report textarea:focus {
    outline: 2px solid var(--dating); outline-offset: 1px;
  }
  /* Off-screen rather than display:none -- a bot reading the DOM still finds it,
     which is the point, but no human or screen reader is offered it. */
  .hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
  .report-context { margin-bottom: 14px; font-size: 11px; color: var(--muted); }
  .report-context summary { cursor: pointer; }
  .report-context pre {
    margin: 8px 0 0; padding: 8px; max-height: 130px; overflow: auto;
    background: var(--ground); border: 1px solid var(--rule);
    font-family: 'IBM Plex Mono', monospace; font-size: 10px; white-space: pre-wrap;
  }
  .report-actions { display: flex; gap: 8px; }
  .report-actions button {
    padding: 9px 14px; background: none; border: 1px solid var(--rule);
    color: var(--bone); cursor: pointer;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    letter-spacing: .1em; text-transform: uppercase;
  }
  .report-actions .primary { background: var(--dating); color: var(--ground); border-color: var(--dating); }
  .report-note { margin-top: 10px; font-size: 11px; line-height: 1.6; color: var(--muted); }
  .report-note a { color: var(--dating); }
  .stats { margin-bottom: 16px; display: grid; gap: 6px; }
  .stat {
    display: flex; align-items: baseline; gap: 8px;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--muted);
  }
  .stat b {
    font-family: 'Archivo', sans-serif; font-size: 15px; color: var(--bone);
    min-width: 34px;
  }
  .stat .who { color: var(--bone); }
  .credit {
    margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--rule);
    font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; line-height: 1.7;
    color: var(--muted);
  }
  /* Deliberately ABOVE the credits and a size up from them: the credits are
     legal small print nobody reads, and burying an ask in small print is how
     you get neither read. Still quiet -- one line, no button, no colour block. */
  .coffee {
    margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--rule);
    font-size: 11px; line-height: 1.6; color: var(--bone);
  }
  .coffee a {
    color: var(--married); font-weight: 600; text-decoration: none;
    border-bottom: 1px solid var(--married);
  }
  .coffee a:hover, .coffee a:focus-visible { color: var(--bone); border-color: var(--bone); }
  .credit a { color: var(--dating); text-decoration: none; }
  .credit a:hover { text-decoration: underline; }
  .trace-form input:focus { outline: 2px solid var(--dating); outline-offset: 1px; }
  .trace-form input::placeholder { color: var(--muted); }
  #search:focus { outline: 2px solid var(--dating); outline-offset: 1px; }
  #search::placeholder { color: var(--muted); }
  .key { display: flex; flex-direction: column; gap: 7px; }
  .key label {
    display: flex; align-items: center; gap: 9px; cursor: pointer;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    user-select: none;
  }
  .key input { accent-color: var(--dating); margin: 0; }
  .key .swatch { width: 22px; height: 0; border-top-width: 2px; border-top-style: solid; }
  .key .count { margin-left: auto; color: var(--muted); font-size: 11px; }
  .glyphkey {
    display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--muted);
  }
  .glyphkey span { display: flex; align-items: center; gap: 9px; }
  .glyphkey svg { width: 18px; height: 18px; flex: none; }
  .past-toggle {
    display: flex; align-items: center; gap: 9px; margin-top: 10px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; cursor: pointer;
  }
  .past-toggle input { accent-color: var(--dating); margin: 0; }
  .statuses {
    margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--rule);
    display: flex; flex-direction: column; gap: 6px;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--muted);
  }
  .statuses span { display: flex; align-items: center; gap: 9px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; flex: none; }

  /* --- detail panel ------------------------------------------------------ */
  .detail {
    position: fixed; top: 0; right: 0; bottom: 0; z-index: 6;
    width: 320px; max-width: 84vw; padding: 26px 22px;
    background: var(--panel); border-left: 1px solid var(--rule);
    transform: translateX(100%); transition: transform .28s ease;
    overflow-y: auto;
  }
  .detail.open { transform: none; }
  .detail .close {
    position: absolute; top: 16px; right: 16px;
    background: none; border: none; color: var(--muted);
    font-size: 22px; line-height: 1; cursor: pointer; padding: 4px;
  }
  .detail .close:hover { color: var(--bone); }
  .detail h3 {
    margin: 0 0 4px; font-family: 'Archivo', sans-serif; font-size: 21px;
    font-weight: 700; letter-spacing: .02em; padding-right: 28px;
  }
  .detail .meta {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
    padding-bottom: 16px; border-bottom: 1px solid var(--rule);
  }
  .detail .group { margin-top: 18px; }
  .detail .group h4 {
    margin: 0 0 8px; font-family: 'IBM Plex Mono', monospace; font-weight: 500;
    font-size: 10px; letter-spacing: .18em; text-transform: uppercase;
  }
  .detail ul { margin: 0; padding: 0; list-style: none; }
  .detail li {
    padding: 6px 0 6px 12px; font-size: 14px;
    border-left: 2px solid var(--rule); cursor: pointer;
    display: flex; flex-direction: column; gap: 2px;
  }
  .detail li:hover { border-left-color: var(--bone); }
  .detail li.over .who { color: #A9C4C1; }
  .detail .when {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    color: var(--muted); letter-spacing: .04em;
  }
  .detail .portrait {
    width: 100%; aspect-ratio: 1; object-fit: cover;
    margin-bottom: 14px; border: 1px solid var(--rule); filter: grayscale(.25);
  }

  /* --- graph ------------------------------------------------------------- */
  .node { cursor: pointer; }
  .card { fill: #10393D; stroke: #2E6A6D; stroke-width: 1.5px; }
  .node.gone .card { fill: #0E3033; stroke: #24565A; stroke-dasharray: 3 3; }
  .card-label {
    font-family: 'Archivo', sans-serif; font-weight: 500; font-size: 12px;
    fill: var(--bone); pointer-events: none; letter-spacing: .02em;
  }
  .node.gone .card-label { fill: #8FAEAC; }
  .pip { fill: #6E9A98; }
  .node.gone .pip { fill: none; stroke: #55807E; stroke-width: 1.5px; }
  .leaf-label {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    fill: #B9CFCB; pointer-events: none;
    paint-order: stroke; stroke: var(--ground); stroke-width: 3px;
  }
  .marker { pointer-events: none; }
  .dimmed { opacity: .08; }
  .hint {
    position: fixed; bottom: 24px; right: 24px; z-index: 4;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--muted);
  }
  @media (max-width: 720px) {
    .rail {
      left: 12px; right: 12px; bottom: 12px; width: auto; padding: 12px;
      max-height: calc(100vh - 24px);
    }
    .rail-toggle { display: block; }
    .rail.collapsed .rail-body { display: none; }
    .rail.collapsed { padding: 12px; }
    .rail-body { margin-top: 12px; }
    .hint { display: none; }
    h1 { font-size: 16px; letter-spacing: .16em; }
    /* Nothing to position: it rides inside the transport now. */
  }
  .trace-form { display: flex; gap: 6px; flex-wrap: wrap; }
  .trace-form input { width: 100%; min-width: 0; }
  .trace-form .ac { flex: 1 1 96px; min-width: 0; }

  /* Suggestions, replacing <datalist>. Chrome on Android renders a native
     datalist as a FULL-SCREEN list of every option -- 187 names covering the
     chart, the rail and the text you were typing. It is unusable on a phone and
     there is no way to style or cap it, so the list has to be ours. */
  .ac { position: relative; }
  .ac-list {
    position: absolute; left: 0; right: 0; top: calc(100% - 12px); z-index: 40;
    margin: 0; padding: 0; list-style: none; max-height: 190px; overflow-y: auto;
    background: var(--panel); border: 1px solid var(--rule);
    box-shadow: 0 10px 26px rgba(0,0,0,.5);
  }
  .trace-form .ac-list { top: 100%; }
  /* On a phone the rail sits low, so a list anchored downward opens off the
     bottom of the screen -- and the keyboard takes what is left. Flipped by
     script when the space below is not enough. */
  .ac-list.above { top: auto; bottom: calc(100% - 12px); }
  .trace-form .ac-list.above { top: auto; bottom: 100%; }
  .ac-list li {
    padding: 9px 10px; cursor: pointer; font-size: 12px;
    font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid var(--rule);
  }
  .ac-list li:last-child { border-bottom: 0; }
  /* A finger is not a mouse pointer. 34px rows are comfortable to click and
     easy to mis-tap, so on touch they grow past the 44px minimum. */
  @media (pointer: coarse) {
    .ac-list li { padding: 13px 12px; font-size: 13px; }
  }
  /* The active row is marked by a bar and a background, not by hue alone. */
  .ac-list li[aria-selected="true"] {
    background: var(--rule); box-shadow: inset 3px 0 0 var(--dating);
  }
  .ac-list b { color: var(--dating); font-weight: 600; }
  .trace-form button {
    flex: 0 0 auto; padding: 0 12px;
    background: var(--rule); color: var(--bone); border: 0; border-radius: 3px;
    font-family: 'Archivo', sans-serif; font-size: 11px; letter-spacing: .06em;
    text-transform: uppercase; cursor: pointer;
  }
  .trace-form button:hover { background: var(--dating); color: var(--ground); }
  .trace-out {
    margin-top: 8px; font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px; line-height: 1.7; color: var(--muted);
  }
  .trace-out .hop { color: var(--bone); }
  .trace-out .via { color: var(--muted); }
  .trace-out .miss { color: var(--fling); }
  /* The traced route outranks search dimming, so the path stays legible. */
  .link.on-path { stroke-opacity: 1 !important; stroke-width: 3.4px !important; }
  .node.on-path .card, .node.on-path circle { stroke: var(--bone); stroke-width: 2px; }
  .marker.on-path { opacity: 1 !important; }
  @media (prefers-reduced-motion: reduce) {
    .detail { transition: none; }
    /* The camera flight on fit/cutoff changes is the only other motion here. */
    .link, .node { transition: none !important; }
  }
</style>
</head>
<body>

<svg id="chart"></svg>

<header>
  <h1>Grey Sloan Memorial</h1>
  <div class="sub">Relationship chart &middot; <span id="tally">__NODE_COUNT__ people, __LINK_COUNT__ connections</span>
    &middot; <a class="alt-view" href="table.html">Table view</a></div>
  <svg class="trace" viewBox="0 0 420 14" preserveAspectRatio="none" aria-hidden="true">
    <path d="M0 7 H84 l6 -6 l7 12 l6 -9 l5 3 H186 l6 -6 l7 12 l6 -9 l5 3 H420"
          fill="none" stroke="#1F5457" stroke-width="1.4"/>
  </svg>
</header>

<div class="rail collapsed" id="rail">
  <button class="rail-toggle" id="rail-toggle" aria-expanded="false">Search &amp; filters</button>
  <div class="tabs" role="tablist">
    <button role="tab" data-tab="when" aria-selected="true">When</button>
    <button role="tab" data-tab="find" aria-selected="false">Find</button>
    <button role="tab" data-tab="show" aria-selected="false">Show</button>
    <button role="tab" data-tab="key" aria-selected="false" title="What the symbols mean">?</button>
  </div>
  <div class="rail-body">

    <section data-panel="when">
      <h2>Watched through</h2>
      <div class="cutoff" id="cutoffs"></div>
      <div class="cutoff-note" id="cutoff-note"></div>
      <h2>Play the timeline</h2>
      <div class="play-form">
        <select id="play-show" aria-label="Show to play"></select>
        <button id="play" type="button" aria-pressed="false">Play</button>
      </div>
      <label class="past-toggle">
        <input type="checkbox" id="past" checked />
        Include past relationships<span class="count" id="past-count"></span>
      </label>
    </section>

    <section data-panel="find" hidden>
      <h2>Find a character</h2>
      <div class="ac">
        <input id="search" type="search" placeholder="e.g. Meredith" autocomplete="off"
               role="combobox" aria-expanded="false" aria-autocomplete="list"
               aria-controls="ac-search" spellcheck="false" />
        <ul class="ac-list" id="ac-search" role="listbox" aria-label="Matching characters" hidden></ul>
      </div>
      <h2>Trace a connection</h2>
      <div class="trace-form">
        <div class="ac">
          <input id="from" type="search" placeholder="From" autocomplete="off"
                 role="combobox" aria-expanded="false" aria-autocomplete="list"
                 aria-controls="ac-from" spellcheck="false" />
          <ul class="ac-list" id="ac-from" role="listbox" aria-label="Matching characters" hidden></ul>
        </div>
        <div class="ac">
          <input id="to" type="search" placeholder="To" autocomplete="off"
                 role="combobox" aria-expanded="false" aria-autocomplete="list"
                 aria-controls="ac-to" spellcheck="false" />
          <ul class="ac-list" id="ac-to" role="listbox" aria-label="Matching characters" hidden></ul>
        </div>
        <button id="trace-go" type="button">Trace</button>
      </div>
      <div class="trace-out" id="trace-out"></div>
    </section>

    <section data-panel="show" hidden>
      <h2>Connection type</h2>
      <div class="key" id="key"></div>
      <h2>Spacing</h2>
      <label class="slider-row">
        <span id="spacing-read">1.0&times;</span>
        <input type="range" id="spacing" min="6" max="22" value="10" />
      </label>
    </section>

    <section data-panel="key" hidden>
    <h2>At this point in the show</h2>
    <div class="stats" id="stats"></div>
    <h2>Markers</h2>
    <div class="glyphkey">
      <span><svg viewBox="-10 -10 20 20"><circle r="8" fill="none" stroke="#E8B84B" stroke-width="1.4"/><text y="3.2" text-anchor="middle" fill="#E8B84B" font-size="9">&#9829;</text></svg> Married</span>
      <span><svg viewBox="-10 -10 20 20"><circle r="8" fill="none" stroke="#8A7F5E" stroke-width="1.4"/><text y="3.2" text-anchor="middle" fill="#8A7F5E" font-size="9">&#9829;</text><path d="M0,-6 L-1.8,-1.5 L1.8,0.8 L0,6" fill="none" stroke="#0B2B2E" stroke-width="1.7"/></svg> Divorced</span>
      <span><svg viewBox="-10 -10 20 20"><circle r="8" fill="none" stroke="#4FC3D9" stroke-width="1.4"/><text y="2.8" text-anchor="middle" fill="#4FC3D9" font-size="7">&#8226;&#8226;&#8226;</text></svg> Relationship</span>
      <span><svg viewBox="-10 -10 20 20"><circle r="8" fill="none" stroke="#E0576E" stroke-width="1.4"/><text y="3.2" text-anchor="middle" fill="#E0576E" font-size="9">1</text></svg> One-time</span>
      <span><svg viewBox="-10 -10 20 20"><line x1="-9" y1="0" x2="9" y2="0" stroke="#9B8CE0" stroke-width="1.4" stroke-dasharray="2 3"/></svg> Blood relative</span>
    </div>
    <div class="statuses">
      <span><i class="dot" style="background:#E8EDE9"></i> Alive</span>
      <span><i class="dot" style="background:transparent;border:2px solid #7FA3A0"></i> Deceased</span>
      <span><i class="dot" style="background:#4FC3D9;width:7px;height:7px"></i> Child</span>
    </div>
    <div class="coffee">
      The chart and the data stay free. If it settled an argument about who
      dated whom, you can
      <a href="https://buymeacoffee.com/stevenstorie" target="_blank" rel="noopener noreferrer">buy me a coffee</a> &#9749;
    </div>
    <div class="credit">
      Inspired by <a href="https://itsdatadana.com/" target="_blank" rel="noopener noreferrer">Dana&rsquo;s romantic web</a>,
      whose scope rules this dataset follows.
      Facts from the <a href="https://greysanatomy.fandom.com/" target="_blank" rel="noopener noreferrer">Grey&rsquo;s Anatomy Universe Wiki</a> (CC BY-SA).
      Character images are screencaps from <i>Grey&rsquo;s Anatomy</i>,
      <i>Station&nbsp;19</i> and <i>Private Practice</i>, &copy;&nbsp;ABC
      Studios / Shondaland, used here to identify the characters they depict.
      No claim of ownership is made.
      <a href="https://gitlab.com/sstangle73/greys-network" target="_blank" rel="noopener noreferrer">Source &amp; data</a>.
      <button type="button" id="report-open" class="linkish">Report a problem</button>
    </div>
    </section>

  </div>
</div>

<dialog id="report" aria-labelledby="report-title">
  <form method="dialog" id="report-form">
    <h2 id="report-title">Report a problem</h2>
    <p class="report-intro">
      Wrong date, missing relationship, something broken? Your current view is
      attached automatically &mdash; which is the part that makes a report about
      a spoiler-aware chart actually actionable.
    </p>

    <label for="report-kind">What sort of problem?</label>
    <select id="report-kind">
      <option value="Wrong data">A relationship or date looks wrong</option>
      <option value="Missing relationship">A relationship is missing</option>
      <option value="Spoiler leak">Something showed that should have been hidden</option>
      <option value="Display bug">The chart looks or behaves wrongly</option>
      <option value="Something else">Something else</option>
    </select>

    <label for="report-body">What did you see?</label>
    <textarea id="report-body" rows="5" required
      placeholder="e.g. Owen and Teddy show as married at S21, but they separate before that."></textarea>

    <!-- Honeypot: a real person never sees this, so anything in it is a bot.
         Only meaningful once a relay endpoint is configured; the GitLab and
         email paths are already gated by GitLab's own auth and spam handling. -->
    <div class="hp" aria-hidden="true">
      <label for="report-website">Website</label>
      <input type="text" id="report-website" name="website" tabindex="-1" autocomplete="off" />
    </div>

    <details class="report-context">
      <summary>What gets attached</summary>
      <pre id="report-preview"></pre>
    </details>

    <div class="report-actions">
      <button type="button" id="report-send" class="primary">Send report</button>
      <button type="button" id="report-cancel">Cancel</button>
    </div>
    <div class="report-note" id="report-note"></div>
  </form>
</dialog>

<div class="transport" id="transport">
  <button id="play-mini" type="button" aria-pressed="false" aria-label="Play the timeline">&#9654;</button>
  <div class="transport-read" id="transport-read"></div>
  <button class="btn-fit" id="fit" title="Fit the whole chart on screen">Fit</button>
</div>

<aside class="detail" id="detail" aria-live="polite">
  <button class="close" id="close" aria-label="Close panel">&times;</button>
  <div id="detail-body"></div>
</aside>

<div class="hint">Drag to rearrange &middot; scroll to zoom &middot; click a node</div>

<script>
const DATA = __GRAPH_DATA__;

const TYPES = {
  Married: { color: '#E8B84B', dash: null },
  Dating:  { color: '#4FC3D9', dash: null },
  Fling:   { color: '#E0576E', dash: '5 4' },
  Parent:  { color: '#9B8CE0', dash: '1 4' }
};

// Blood relations recede into the background, so they are drawn in a darker
// tone of the same violet rather than a different hue. Keeping this in step
// with TYPES.Parent.color matters: the legend swatch reads TYPES, so when this
// was a teal constant the key showed one colour and the chart drew another.
const PARENT_INK = '#6B5FA8';

const active = new Set(Object.keys(TYPES));
let showPast = true;

/* ---- legend ------------------------------------------------------------- */
d3.select('#key').selectAll('label')
  .data(Object.keys(TYPES))
  .join('label')
  .html(t => `
    <input type="checkbox" checked data-type="${t}" />
    <i class="swatch" style="border-top-color:${TYPES[t].color};
       border-top-style:${TYPES[t].dash ? 'dashed' : 'solid'}"></i>
    ${t}<span class="count" data-count="${t}">0</span>`);

/* ---- svg scaffolding ---------------------------------------------------- */
const svg = d3.select('#chart');
const root = svg.append('g');
let width = window.innerWidth, height = window.innerHeight;
const isPhone = () => window.innerWidth <= 720;

function sizeSvg() {
  width = window.innerWidth;
  height = window.innerHeight;
  svg.attr('width', width).attr('height', height);
}
sizeSvg();

const zoom = d3.zoom()
  .scaleExtent([0.15, 4])
  // Declare the extent rather than letting d3 infer it from the SVG's
  // width/height attributes -- that inference is what silently sized the
  // interaction area to 300x150.
  .extent(() => [[0, 0], [width, height]])
  .on('zoom', e => {
  root.attr('transform', e.transform);
  curK = e.transform.k;
  updateLabels();
});
svg.call(zoom);

const defs = svg.append('defs');
// Circular portraits, used only for nodes that have an Image_URL filled in.
DATA.nodes.filter(n => n.image).forEach((n, i) => {
  n.patternId = 'p' + i;
  defs.append('pattern')
    .attr('id', n.patternId).attr('width', 1).attr('height', 1)
    .attr('patternContentUnits', 'objectBoundingBox')
    .append('image')
    .attr('width', 1).attr('height', 1)
    .attr('preserveAspectRatio', 'xMidYMid slice')
    .attr('href', n.image);
});

const radius = n => n.status === 'Child' ? 5 : 6 + Math.sqrt(n.degree) * 2.6;

/* ---- spoiler cutoff ----------------------------------------------------- */
// Everything on screen is gated on this. A relationship or a death that hasn't
// aired yet, relative to where the viewer is, simply doesn't exist.
const cuts = {}, enabled = new Set();
DATA.shows.forEach(sh => {
  cuts[sh.key] = { s: sh.s, e: sh.e };
  if (sh.on) enabled.add(sh.key);
});
const SHOW_BY_KEY = Object.fromEntries(DATA.shows.map(sh => [sh.key, sh]));
// Declared here, not down with the detail panel: applyCutoff() reads it during
// boot, and a `let` accessed before its declaration is a temporal dead zone
// error rather than an undefined.
let selected = null;
let searchCore = null;   // people whose name matched
let searchSet = null;    // those people plus everyone they connect to
// Same reason as the two above: applyCutoff() clears any traced route and
// writes the URL hash, and it runs during boot -- a `let` declared down with
// that code is a temporal dead zone, not an undefined.
let pathIds = new Set();
let hashLoading = false;
// Hoisted: clearSelection() calls applySearch(), and applyCutoff() can call
// clearSelection() during boot -- a `const` further down would be a dead zone.
const searchInput = document.getElementById('search');
// Same again: applyCutoff() calls refreshCastList() during boot, which assigns
// this. The function declaration hoists; the `let` it writes to does not.
let castNames = [];
// Every date belongs to exactly one show, so every comparison needs to know
// which clock it is reading. seen() is the only place that knows.
function seen(show, s, e) {
  const c = cuts[show];
  if (!c || !enabled.has(show)) return false;
  return s < c.s || (s === c.s && e <= c.e);
}
// A tie is on screen once its home show has reached it, OR once some other
// show you are watching has revealed it. That is what keeps a Grey's-only
// viewer seeing exactly what Grey's told them.
// ek=0 means "the season is right, the episode is unknown". Those are held back
// until the whole season has been watched, because episode 1 is the EARLIEST
// point in a season and asserting an unknown there is the one direction that
// spoils. No episode number is invented to achieve this -- the data still says
// "unknown", and only the comparison moves to the end of the season.
function atHome(l) {
  if (l.ek) return seen(l.show, l.s, l.e);
  const meta = SHOW_BY_KEY[l.show];
  return seen(l.show, l.s, meta ? meta.episodes : 27);
}
const revealed = l => l.reveals.filter(r => seen(r.show, r.s, r.e));
const aired = l => atHome(l) || revealed(l).length > 0;
// A marriage reads as intact until the split actually airs -- at S22 E02 Owen
// and Teddy are still married, and the chart should say so.
// A couple who marry later are DATING until the wedding airs. Relationship_Type
// is where the tie ended up, not what it was on day one.
const wed = l => l.type === 'Married' && l.ms !== null && seen(l.show, l.ms, l.me);
// Some ties start as a hookup and only become a relationship later. A blank
// gs means it was a relationship from the first scene.
const steady = l => l.gs === null || seen(l.show, l.gs, l.ge);

// The stage the home show has reached.
function homeStage(l) {
  if (l.type === 'Parent' || l.type === 'Fling') return l.type;
  if (wed(l)) return 'Married';
  return steady(l) ? 'Dating' : 'Fling';
}
// Where two shows disagree, the further-along one wins: if Station 19 has shown
// you a wedding, the tie is married even if Grey's has only mentioned them
// dating. Rank makes "further along" well-defined.
const RANK = { Fling: 0, Dating: 1, Married: 2 };
function displayType(l) {
  if (l.type === 'Parent') return 'Parent';
  let best = atHome(l) ? homeStage(l) : null;
  for (const r of revealed(l)) {
    if (best === null || (RANK[r.stage] ?? 0) > (RANK[best] ?? 0)) best = r.stage;
  }
  return best || homeStage(l);
}
const divorced = l => l.split && wed(l) && seen(l.show, l.ss, l.se);
// Over, as of where the viewer is. A relationship that ends in a later season
// is still going from their point of view.
//
// eek=0 means the end season is right but the episode is unknown. Those are
// held to the CLOSE of that season, so the pair stay together for the whole of
// it rather than reading as finished from the opener -- the mirror of how an
// unknown start is held. Derek and Addison divorce late in season 3, and an end
// on 3x01 announced the outcome twenty episodes early.
function over(l) {
  if (l.ls === null) return false;
  if (l.eek) return seen(l.show, l.ls, l.le);
  const meta = SHOW_BY_KEY[l.show];
  return seen(l.show, l.ls, meta ? meta.episodes : 27);
}

// THE predicate for "is this link on screen". Module scope on purpose: it used
// to live inside applyCutoff(), so the stats panel and the path tracer each
// grew their own copy, and a copy of this is a copy that can disagree.
const onChart = l => aired(l) && active.has(displayType(l))
  && (showPast || l.type === 'Parent' || !over(l));
const drawnLinks = () => DATA.links.filter(
  l => onChart(l) && visible.has(l.source.id) && visible.has(l.target.id));

// Episode precision only shows on a show's final season, which is where the
// viewer is likely to be mid-run. Spinoffs carry their key so "S19 S3" cannot
// be mistaken for a Grey's season.
function seasonTag(show, s, e) {
  const meta = SHOW_BY_KEY[show];
  const label = s === (meta ? meta.seasons : 22)
    ? `S${s} E${String(e).padStart(2, '0')}` : `S${s}`;
  return show && show !== 'GA' ? `${show} ${label}` : label;
}
function span(l) {
  const from = seasonTag(l.show, l.s, l.e);
  if (!over(l)) return `${from} \u2013 present`;
  const to = seasonTag(l.show, l.ls, l.le);
  return from === to ? from : `${from} \u2013 ${to}`;
}
const isDead = n => n.ds !== null && seen(n.dshow, n.ds, n.de);
const statusAt = n => n.status === 'Child' ? 'Child' : (isDead(n) ? 'Deceased' : 'Alive');

const fill = n => {
  if (n.patternId) return `url(#${n.patternId})`;
  if (isDead(n)) return 'transparent';
  if (n.status === 'Child') return '#4FC3D9';
  return '#E8EDE9';
};

// Base geometry, all multiplied by the user's spacing setting.
const BASE_LINK = 132, BASE_PARENT_LINK = 74, BASE_CHARGE = -520, BASE_COLLIDE = 24;
let spacing = 1;

// Card sizes are measured HERE, before the simulation exists, because the link
// force resolves its distance accessor once at initialisation -- not per tick
// like collide does. Sizing the nodes further down (where this used to live)
// meant link distances were computed from an undefined width and came out NaN,
// which silently strands most of the graph at no position at all.
const HUB_AT_SIZE = 3;
DATA.nodes.forEach(d => {
  const label = (d.ds !== null ? '† ' : '') + d.id;
  d.label = label;
  const hub = d.degree >= HUB_AT_SIZE;
  d.h = hub ? 26 : 15;
  d.w = hub ? label.length * 6.6 + 22 + (d.image ? 22 : 0)
            : label.length * 5.6 + 8;
});

const sim = d3.forceSimulation(DATA.nodes)
  .force('link', d3.forceLink(DATA.links).id(d => d.id).strength(.4))
  .force('charge', d3.forceManyBody())
  .force('collide', d3.forceCollide())
  // forceCenter only fixes the mean position -- it lets outliers drift off-screen.
  // Mild positional forces keep the whole network inside a bounded area instead.
  // They weaken as spacing rises, or they'd just claw the layout back together.
  .force('x', d3.forceX(0))
  .force('y', d3.forceY(0));

function applySpacing() {
  // Someone with a single connection is a satellite: pull them in tight so they
  // read as belonging to that person instead of floating in the soup.
  const satellite = l => Math.min(l.source.degree, l.target.degree) <= 1;

  // A fixed satellite distance is the thing that was forcing overlap. Everyone
  // hanging off one person sat on the same small circle, so a hub with eight
  // partners had ~465px of circumference to fit ~800px of name cards into --
  // no amount of collide iterations can fix a ring that is too small. Size the
  // ring from the hub's degree and the width of what has to fit on it.
  const ringFor = l => {
    const hub = l.source.degree >= l.target.degree ? l.source : l.target;
    const leaf = hub === l.source ? l.target : l.source;
    const needed = (hub.degree * (leaf.w + 16)) / (2 * Math.PI);
    return Math.max(78, needed);
  };

  sim.force('link')
    .distance(l => satellite(l)
      ? ringFor(l) * spacing
      : (l.type === 'Parent' ? BASE_PARENT_LINK : BASE_LINK) * spacing)
    // Satellites hold their ring firmly; the rest of the graph stays loose
    // enough for the collide pass to do its work.
    .strength(l => satellite(l) ? .75 : .35);
  sim.force('charge')
    .strength(d => (d.degree <= 1 ? BASE_CHARGE * .35 : BASE_CHARGE) * spacing)
    .distanceMax(760 * spacing);
  // Cards are wide, so collide on half the card width, not a notional radius.
  // iterations matters more than any of the distances here: forceCollide only
  // does one relaxation pass by default, which leaves plenty of contacts
  // unresolved -- and because the layout FREEZES afterwards, whatever is still
  // overlapping stays overlapping forever. Three passes cut measured overlap
  // from 62 pairs to a handful.
  sim.force('collide')
    .radius(d => Math.max(d.w / 2, d.h) + 13 * spacing)
    .strength(.95)
    .iterations(3);
  sim.force('x').x(0).strength(.05 / spacing);
  sim.force('y').y(0).strength(.07 / spacing);
}
applySpacing();

// Re-settle the layout off-screen, then reframe. Cheap enough at this size to
// run synchronously rather than animating through an unreadable intermediate.
function relayout() {
  applySpacing();
  DATA.nodes.forEach(n => { n.fx = n.fy = null; });
  sim.alpha(1).stop();
  for (let i = 0; i < 460; i++) sim.tick();
  freezeLayout();
  renderPositions();
  applyCutoff();
}

/* ---- geometry ----------------------------------------------------------- */
// Two tiers, as in a hand-drawn relationship poster: the people the show is
// about get a card with their name (and portrait, once Image_URL is filled in);
// everyone else is a bare name tethered to whoever they were involved with.
const HUB_AT = 3;
const isHub = d => d.degree >= HUB_AT;

// (node sizes are measured up with the geometry constants -- the link force
// needs them before the simulation initialises)

// Curved connectors. A quadratic bow means two people with several kinds of
// history don't overlap into one ambiguous straight line, and it reads far
// calmer than a field of crossing straight segments.
const BOW = 0.13;
function ctrlPoint(d) {
  const x1 = d.source.x, y1 = d.source.y, x2 = d.target.x, y2 = d.target.y;
  return [(x1 + x2) / 2 - (y2 - y1) * BOW, (y1 + y2) / 2 + (x2 - x1) * BOW];
}
function linkPath(d) {
  const [cx, cy] = ctrlPoint(d);
  return `M${d.source.x},${d.source.y}Q${cx},${cy} ${d.target.x},${d.target.y}`;
}
// Exact midpoint of a quadratic Bezier: B(.5) = .25*P0 + .5*C + .25*P2
function linkMid(d) {
  const [cx, cy] = ctrlPoint(d);
  return [0.25 * d.source.x + 0.5 * cx + 0.25 * d.target.x,
          0.25 * d.source.y + 0.5 * cy + 0.25 * d.target.y];
}

const link = root.append('g').selectAll('path')
  .data(DATA.links).join('path')
  .attr('class', 'link')
  .attr('fill', 'none')
  .attr('stroke', d => d.type === 'Parent' ? PARENT_INK : TYPES[d.type].color)
  .attr('stroke-width', d => d.type === 'Married' ? 2 : 1.2)
  .attr('stroke-opacity', d => d.type === 'Parent' ? .5 : .45)
  .attr('stroke-dasharray', d => d.type === 'Parent' ? '2 4' : null);

/* ---- connection markers -------------------------------------------------- */
// A badge riding each connection says what kind it was, so the line colour
// isn't carrying the whole meaning. Blood relations get no badge -- the dotted
// line already says it, and 39 extra badges is just noise.
const GLYPH = { Married: '\u2665', Dating: '\u2022\u2022\u2022', Fling: '1' };

const marker = root.append('g').selectAll('g')
  .data(DATA.links.filter(l => l.type !== 'Parent')).join('g')
  .attr('class', 'marker');

marker.append('circle')
  .attr('r', 8)
  .attr('fill', '#0B2B2E')
  .attr('stroke', d => TYPES[d.type].color)
  .attr('stroke-width', 1.4);

marker.append('text')
  .attr('text-anchor', 'middle').attr('dy', '.35em')
  .attr('fill', d => TYPES[d.type].color)
  .style('font-family', "'IBM Plex Mono', monospace")
  .style('font-size', d => d.type === 'Dating' ? '7px' : '9px')
  .style('pointer-events', 'none')
  .text(d => GLYPH[d.type]);

// A divorce is the same heart with a split torn through it -- drawn in the
// background colour so it reads as the heart breaking, not as an added mark.
marker.filter(d => d.split)
  .append('path')
  .attr('class', 'crack')
  .attr('d', 'M0,-6 L-1.8,-1.5 L1.8,0.8 L0,6')
  .attr('fill', 'none')
  .attr('stroke', '#0B2B2E')
  .attr('stroke-width', 1.7)
  .style('display', 'none');

marker.append('title').text(d => `${d.source.id} \u2014 ${d.target.id}: ${d.type}`);

const node = root.append('g').selectAll('g')
  .data(DATA.nodes).join('g')
  .attr('class', 'node')
  .call(d3.drag()
    // Ignore multi-touch so a pinch that happens to start on a node goes to the
    // zoom behaviour instead of being swallowed as a drag.
    .filter(e => !e.button && (!e.touches || e.touches.length === 1))
    .on('start', (e, d) => { d.dragFrom = [e.x, e.y]; d.dragging = false; })
    .on('drag', (e, d) => {
      // A finger never lands perfectly still; require real travel before moving
      // anything, so a tap-to-select doesn't nudge the node.
      if (!d.dragging) {
        const [x0, y0] = d.dragFrom;
        if (Math.hypot(e.x - x0, e.y - y0) < 8 / curK) return;
        d.dragging = true;
      }
      d.fx = d.x = e.x;
      d.fy = d.y = e.y;
      renderPositions();
    })
    // Position is kept, not released -- the node stays where you put it and
    // nothing else on the chart moves.
    .on('end', (e, d) => { d.dragFrom = null; }));

const hub = node.filter(isHub);
hub.append('rect')
  .attr('class', 'card')
  .attr('x', d => -d.w / 2).attr('y', d => -d.h / 2)
  .attr('width', d => d.w).attr('height', d => d.h)
  .attr('rx', d => d.h / 2);
hub.filter(d => d.image)
  .append('circle')
  .attr('class', 'portrait-dot')
  .attr('cx', d => -d.w / 2 + d.h / 2).attr('cy', 0).attr('r', d => d.h / 2 - 3)
  .attr('fill', d => `url(#${d.patternId})`);
hub.append('text')
  .attr('class', 'card-label')
  .attr('x', d => d.image ? -d.w / 2 + d.h + 4 : 0)
  .attr('text-anchor', d => d.image ? 'start' : 'middle')
  .attr('dy', '.34em')
  .text(d => d.label);

const leaf = node.filter(d => !isHub(d));
leaf.append('circle').attr('class', 'pip').attr('r', 3);
leaf.append('text')
  .attr('class', 'leaf-label')
  .attr('x', 7).attr('dy', '.34em')
  .text(d => d.label);

node.append('title').text(d => d.id);

node.on('click', (e, d) => {
      e.stopPropagation();
      if (d.dragging) { d.dragging = false; return; }
      select(d);
    })
    .on('mouseenter', (e, d) => { d.hover = true; updateLabels(); })
    .on('mouseleave', (e, d) => { d.hover = false; updateLabels(); });
svg.on('click', () => clearSelection());

const nodeById = {};
DATA.nodes.forEach(n => nodeById[n.id] = n);

function renderPositions() {
  link.attr('d', linkPath);
  // The scale term has to be here too -- renderPositions runs on every tick and
  // would otherwise strip the counter-scale that keeps markers a fixed size.
  marker.attr('transform', d => {
    const [x, y] = linkMid(d);
    return `translate(${x},${y}) scale(${1 / curK})`;
  });
  node.attr('transform', d => `translate(${d.x},${d.y})`);
}

// Once settled, pin everything. A live simulation meant that brushing a node
// re-energised the whole layout and the chart appeared to recenter itself.
function freezeLayout() {
  DATA.nodes.forEach(n => { n.fx = n.x; n.fy = n.y; });
  sim.stop();
}
sim.on('tick', renderPositions);

/* ---- labels ------------------------------------------------------------- */
// Labels live in graph space, so they must be counter-scaled to hold a constant
// on-screen size. How MANY are shown is a density decision: zoomed out, only the
// hubs are legible; zoomed in, there's room for everyone. Hovering or selecting
// always wins, so any character can be identified at any zoom.
let curK = 1;

// Legibility depends on how far apart nodes are ON SCREEN, not on the zoom
// number. Keying off k alone meant that spreading the graph out -- which frees
// up room for text -- perversely hid labels, because fitting a wider layout
// lowers k. Measure the actual pixel gap instead.
function minDegreeForLabel(k) {
  const gap = BASE_LINK * spacing * k;
  if (gap < 46) return 8;
  if (gap < 78) return 5;
  if (gap < 120) return 3;
  if (gap < 190) return 2;
  return 0;
}

function updateLabels() {
  const k = curK;
  const min = minDegreeForLabel(k);
  // Pin names for a selected character's circle, and for everyone a search
  // turned up -- that's the whole point of searching for them.
  let keep = null;
  if (selected) keep = new Set([selected, ...neighborsOf(selected).map(r => r.other)]);
  if (searchSet) keep = keep ? new Set([...keep, ...searchSet]) : new Set(searchSet);

  // Cards carry their own name and never counter-scale -- they're the anchors.
  node.select('.leaf-label')
    .style('font-size', (10 / k) + 'px')
    .style('stroke-width', (3 / k) + 'px')
    .attr('x', 7 / k)
    .style('display', d =>
      (d.hover || d.degree >= min || (keep && keep.has(d.id))) ? null : 'none');

  // Markers are fixed-size furniture; hide them when they'd just be specks.
  marker.attr('transform', function (d) {
    const [x, y] = linkMid(d);
    return `translate(${x},${y}) scale(${1 / k})`;
  })
  .style('opacity', d => over(d) ? .55 : 1)
  .style('display', d =>
      (k >= 0.45 && aired(d) && active.has(displayType(d))
       && (showPast || !over(d))
       && visible.has(d.source.id) && visible.has(d.target.id)) ? null : 'none');
}

/* ---- applying the cutoff ------------------------------------------------ */
// A node is on screen if at least one of its relationships has aired. That
// keeps characters from appearing before their storyline does -- the Lincoln
// twins don't exist at S22 E02, so they aren't drawn at all.
let visible = new Set();

function applyCutoff(refit = true) {
  // Derived from onChart, not from aired() alone, so the cast matches the
  // connections. Unticking "Blood relative" used to leave the children on the
  // chart as dots with nothing attached to them, because the links went away
  // and the people did not.
  visible = new Set();
  DATA.links.filter(onChart).forEach(l => {
    visible.add(l.source.id);
    visible.add(l.target.id);
  });

  link.style('display', l =>
    (onChart(l) && visible.has(l.source.id) && visible.has(l.target.id)) ? null : 'none');

  // Ended ties recede; the ones still standing keep full weight. This is what
  // separates "these two have history" from "these two are together now".
  link
    .attr('stroke', l => l.type === 'Parent' ? PARENT_INK
      : (divorced(l) ? '#8A7F5E' : TYPES[displayType(l)].color))
    .attr('stroke-opacity', l => l.type === 'Parent' ? .5 : (over(l) ? .3 : .85))
    .attr('stroke-width', l => (wed(l) ? 2 : 1.2) * (over(l) ? 1 : 1.6));
  node.style('display', n => visible.has(n.id) ? null : 'none');
  node.classed('gone', isDead);

  // Marriages that have since ended show a broken heart, and go grey -- the
  // gold is reserved for the ones still standing at this point in the show.
  marker.select('.crack').style('display', d => divorced(d) ? null : 'none');
  marker.select('circle')
    .attr('stroke', d => divorced(d) ? '#8A7F5E' : TYPES[displayType(d)].color);
  marker.select('text')
    .attr('fill', d => divorced(d) ? '#8A7F5E' : TYPES[displayType(d)].color)
    .style('font-size', d => displayType(d) === 'Dating' ? '7px' : '9px')
    .text(d => GLYPH[displayType(d)]);
  marker.select('title').text(d => {
    const state = divorced(d) ? 'Married, later divorced'
      : (d.type === 'Married' && !wed(d) ? 'Dating (marry later)' : displayType(d));
    return `${d.source.id} \u2014 ${d.target.id}\n${state} \u00b7 ${span(d)}`;
  });

  const past = DATA.links.filter(l => aired(l) && l.type !== 'Parent' && over(l)).length;
  d3.select('#past-count').text(past);
  link.filter(d => d.type === 'Married')
    .attr('stroke', d => divorced(d) ? '#8A7F5E' : TYPES.Married.color);

  // A dagger prefix marks the dead, matching how a printed chart would do it.
  node.select('.card-label').text(d => (isDead(d) ? '\u2020 ' : '') + d.id);
  node.select('.leaf-label').text(d => (isDead(d) ? '\u2020 ' : '') + d.id);
  node.select('title').text(d => `${d.id} - ${statusAt(d)}`);

  const counts = {};
  DATA.links.filter(aired).forEach(l => {
    const t = displayType(l);
    counts[t] = (counts[t] || 0) + 1;
  });
  d3.selectAll('[data-count]').text(function () { return counts[this.dataset.count] || 0; });

  // The tally has to describe what is actually on screen, so it counts the
  // links that survive the type filters and the past toggle -- not just the
  // ones that have aired. Counting aired() here meant unticking Fling dropped
  // the people count but left "connections" unchanged.
  const drawn = DATA.links.filter(
    l => onChart(l) && visible.has(l.source.id) && visible.has(l.target.id)).length;
  DATA.shows.forEach(sh => {
    const sfx = sh.key === 'GA' ? '' : '-' + sh.key;
    const c = cuts[sh.key];
    d3.select('#cutoff-read' + sfx)
      .text(!enabled.has(sh.key) ? 'hidden'
        : c.s < 1 ? 'not yet'
        : `S${c.s} E${String(c.e).padStart(2, '0')}`);
  });
  // Same information on the chart itself, so the position is readable while the
  // timeline runs without the rail open.
  d3.select('#transport-read').selectAll('.unit')
    .data(DATA.shows.filter(sh => enabled.has(sh.key)), sh => sh.key)
    .join(enter => {
      const u = enter.append('div').attr('class', 'unit');
      u.append('span').attr('class', 'who');
      u.append('span').attr('class', 'at');
      return u;
    })
    .each(function (sh) {
      const c = cuts[sh.key];
      d3.select(this).select('.who').text(sh.key);
      d3.select(this).select('.at')
        .attr('class', c.s < 1 ? 'at idle' : 'at')
        .text(c.s < 1 ? '—' : `S${c.s} E${String(c.e).padStart(2, '0')}`);
    });
  d3.select('#tally').text(`${visible.size} people, ${drawn} connections`);

  // The note below is about the CUTOFF specifically -- "later" means "hasn't
  // aired yet", so it stays keyed to aired() and ignores the filters.
  const hidden = DATA.links.filter(l => !aired(l)).length;
  d3.select('#cutoff-note').text(hidden ? `${hidden} later connection${hidden === 1 ? '' : 's'} hidden` : '');

  // Anyone selected who no longer exists at this cutoff gets deselected.
  if (selected && !visible.has(selected)) clearSelection();
  else if (selected) select(DATA.nodes.find(n => n.id === selected));

  refreshCastList();
  refreshStats();
  updateLabels();
  // A traced route can be invalidated by any of the above -- winding the cutoff
  // back can remove a link the path ran through.
  if (typeof clearPath === 'function' && pathIds.size) clearPath();
  if (typeof writeHash === 'function') writeHash();
  if (refit) fitToView(400, initialFloor());
}

/* ---- camera ------------------------------------------------------------- */
// The area actually free of chrome: the masthead sits on top, the rail bottom
// left, the fit button bottom right. Fitting to innerWidth/innerHeight alone
// pushes nodes underneath those panels.
function viewport() {
  const top = document.querySelector('header').offsetHeight + 8;
  const rail = document.getElementById('rail');
  if (isPhone()) {
    const bottom = rail.offsetHeight + 64;
    return { x: 12, y: top, w: window.innerWidth - 24, h: window.innerHeight - top - bottom };
  }
  const left = rail.offsetWidth + 48;
  return { x: left, y: top, w: window.innerWidth - left - 40, h: window.innerHeight - top - 40 };
}

function fitToView(duration = 400, floor = 0) {
  const shown = visible.size ? DATA.nodes.filter(n => visible.has(n.id)) : DATA.nodes;
  const xs = shown.map(n => n.x), ys = shown.map(n => n.y);
  if (!xs.length || !isFinite(xs[0])) return;
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 46;
  const vw = viewport();
  if (vw.h < 120) return;
  let k = Math.min(vw.w / (maxX - minX + pad * 2), vw.h / (maxY - minY + pad * 2), 1.6);
  k = Math.max(k, floor);
  const t = d3.zoomIdentity
    .translate(vw.x + vw.w / 2 - k * (minX + maxX) / 2, vw.y + vw.h / 2 - k * (minY + maxY) / 2)
    .scale(k);
  svg.transition().duration(duration).call(zoom.transform, t);
}

// Arriving from a link that names one person. Fitting the whole graph and
// selecting them is technically correct and useless -- on 187 nodes the person
// you asked for is a speck. Put them in the middle instead.
function centreOn(node, duration = 500) {
  if (!node || !isFinite(node.x)) return;
  const vw = viewport();
  if (vw.h < 120) return;
  const k = 1.15;
  const t = d3.zoomIdentity
    .translate(vw.x + vw.w / 2 - k * node.x, vw.y + vw.h / 2 - k * node.y)
    .scale(k);
  svg.transition().duration(duration).call(zoom.transform, t);
}

// Settle the layout off-screen first, then frame it, so the graph is never
// rendered mid-explosion or half outside the canvas.
sim.stop();
for (let i = 0; i < 440; i++) sim.tick();
freezeLayout();
// Positions are only written by renderPositions, which used to be driven by the
// simulation's tick. Now that the layout freezes instead of running, boot has to
// paint once itself -- otherwise every node sits at the origin with no transform.
renderPositions();
applyCutoff(false);
const initialFloor = () => isPhone() ? 0.62 : 0;
fitToView(0, initialFloor());


document.getElementById('fit').onclick = () => fitToView();

/* ---- filtering ---------------------------------------------------------- */
d3.select('#key').selectAll('input').on('change', function () {
  this.checked ? active.add(this.dataset.type) : active.delete(this.dataset.type);
  // Was doing its own partial update against the RAW l.type, which disagreed
  // with displayType() -- a Married tie before its wedding reads as Dating, so
  // unticking Dating left it on screen. It also skipped the node, marker and
  // tally updates entirely. applyCutoff() is the one place that knows all of it.
  applyCutoff(false);
});

document.getElementById('past').addEventListener('change', function () {
  showPast = this.checked;
  applyCutoff();
});

/* ---- cutoff sliders, one block per show ---------------------------------- */
// Grey's keeps the bare ids "season"/"episode" so it stays the primary control
// (and so the existing test harness keeps driving it); spinoffs are suffixed.
const cutoffBox = d3.select('#cutoffs');
DATA.shows.forEach(sh => {
  const sfx = sh.key === 'GA' ? '' : '-' + sh.key;
  const block = cutoffBox.append('div').attr('class', 'show-block');
  block.append('label').attr('class', 'show-head').html(`
    <input type="checkbox" id="on${sfx}" data-show="${sh.key}" ${sh.on ? 'checked' : ''} />
    <span class="show-title">${sh.title}</span>
    <span class="cutoff-read" id="cutoff-read${sfx}"></span>`);
  block.append('label').attr('class', 'slider-row').html(
    `<span>Season</span><input type="range" id="season${sfx}"
       min="1" max="${sh.seasons}" value="${sh.s}" />`);
  block.append('label').attr('class', 'slider-row').html(
    `<span>Episode</span><input type="range" id="episode${sfx}"
       min="1" max="${sh.episodes}" value="${sh.e}" />`);

  const season = document.getElementById('season' + sfx);
  const episode = document.getElementById('episode' + sfx);
  const toggle = document.getElementById('on' + sfx);
  const read = () => {
    cuts[sh.key] = { s: +season.value, e: +episode.value };
    applyCutoff();
  };
  season.addEventListener('input', read);
  episode.addEventListener('input', read);
  toggle.addEventListener('change', () => {
    toggle.checked ? enabled.add(sh.key) : enabled.delete(sh.key);
    block.classed('off', !toggle.checked);
    applyCutoff();
  });
  block.classed('off', !sh.on);
});

/* ---- spacing ------------------------------------------------------------- */
const spacingInput = document.getElementById('spacing');
spacingInput.addEventListener('input', () => {
  d3.select('#spacing-read').text((spacingInput.value / 10).toFixed(1) + '\u00d7');
});
// Recompute on release: a full re-settle per pixel of slider travel is wasteful.
spacingInput.addEventListener('change', () => {
  spacing = spacingInput.value / 10;
  relayout();
});

/* ---- selection + detail panel ------------------------------------------- */
const detail = document.getElementById('detail');
const body = document.getElementById('detail-body');
document.getElementById('close').onclick = clearSelection;

function neighborsOf(name) {
  // Only aired relationships -- the panel must not leak what the graph hides.
  return DATA.links
    .filter(l => aired(l) && (l.source.id === name || l.target.id === name))
    .map(l => ({
      other: l.source.id === name ? l.target.id : l.source.id,
      type: displayType(l),
      when: l.type === 'Parent' ? seasonTag(l.s, l.e) : span(l),
      over: l.type !== 'Parent' && over(l),
      split: divorced(l),
      sort: l.s * 100 + l.e
    }));
}

function select(d) {
  if (!d) return;
  selected = d.id;
  const rel = neighborsOf(d.id);
  const keep = new Set([d.id, ...rel.map(r => r.other)]);

  node.classed('dimmed', n => !keep.has(n.id));
  const touches = l => l.source.id === d.id || l.target.id === d.id;
  link.classed('dimmed', l => !touches(l));
  marker.classed('dimmed', l => !touches(l));

  const status = statusAt(d);
  const current = rel.filter(r => r.type !== 'Parent' && !r.over).length;

  const grouped = {};
  rel.forEach(r => (grouped[r.type] ||= []).push(r));
  Object.values(grouped).forEach(list => list.sort((a, b) => a.sort - b.sort));

  body.innerHTML =
    (d.image ? `<img class="portrait" src="${d.image}" alt="${d.id}">` : '') +
    `<h3>${d.id}</h3>
     <div class="meta">${status} &middot; ${rel.length} connection${rel.length === 1 ? '' : 's'}${
        current ? ` &middot; ${current} current` : ''}</div>` +
    Object.keys(TYPES).filter(t => grouped[t]).map(t => `
      <div class="group">
        <h4 style="color:${TYPES[t].color}">${t}</h4>
        <ul>${grouped[t].map(r => `
          <li data-jump="${r.other}" class="${r.over ? 'over' : ''}">
            <span class="who">${r.other}</span>
            <span class="when">${r.when}${r.split ? ' \u00b7 divorced' : ''}</span>
          </li>`).join('')}</ul>
      </div>`).join('') +
    // The other half of the round trip. The chart answers "who is this connected
    // to"; the table answers "and how do we know". Linking to a pre-filtered
    // table means that second question is one tap away rather than a re-search.
    `<a class="to-table" href="table.html#q=${encodeURIComponent(d.id)}">` +
    `Evidence for ${d.id} &rarr;</a>`;

  updateLabels();

  body.querySelectorAll('[data-jump]').forEach(li => {
    li.onclick = () => {
      const target = DATA.nodes.find(n => n.id === li.dataset.jump);
      if (target) select(target);
    };
  });
  detail.classList.add('open');
}

function clearSelection() {
  selected = null;
  detail.classList.remove('open');
  // Falling back to the search state, not to "everything visible" -- clearing a
  // selection shouldn't silently undo an active search.
  applySearch();
}

/* ---- search ------------------------------------------------------------- */
// Matching someone surfaces their whole neighbourhood: their own name, the names
// of everyone they were involved with, and only the connections that touch them.
function applySearch() {
  const q = searchInput.value.trim().toLowerCase();

  if (!q) {
    searchCore = searchSet = null;
    node.classed('dimmed', false);
    link.classed('dimmed', false);
    marker.classed('dimmed', false);
    updateLabels();
    return;
  }

  searchCore = new Set(DATA.nodes
    .filter(n => visible.has(n.id) && n.id.toLowerCase().includes(q))
    .map(n => n.id));

  searchSet = new Set(searchCore);
  DATA.links.filter(aired).forEach(l => {
    if (searchCore.has(l.source.id)) searchSet.add(l.target.id);
    if (searchCore.has(l.target.id)) searchSet.add(l.source.id);
  });

  const touches = l => searchCore.has(l.source.id) || searchCore.has(l.target.id);
  node.classed('dimmed', n => !searchSet.has(n.id));
  link.classed('dimmed', l => !touches(l));
  marker.classed('dimmed', l => !touches(l));
  updateLabels();
}

searchInput.addEventListener('input', applySearch);
searchInput.addEventListener('search', applySearch);

/* ---- stats --------------------------------------------------------------- */
// Everything here is computed from what is CURRENTLY DRAWN, not from the whole
// dataset -- otherwise it would quietly answer questions about episodes the
// viewer has not reached. Recomputed on every cutoff change, so it also doubles
// as a readout while the timeline plays.
function refreshStats() {
  const links = drawnLinks();

  const degree = new Map();
  const romantic = links.filter(l => l.type !== 'Parent');
  for (const l of romantic) {
    degree.set(l.source.id, (degree.get(l.source.id) || 0) + 1);
    degree.set(l.target.id, (degree.get(l.target.id) || 0) + 1);
  }
  const busiest = [...degree.entries()].sort((a, b) => b[1] - a[1])[0];

  // Largest connected group, over romantic ties only: "how much of this cast is
  // one tangle" is the question a relationship chart is actually asking.
  const adj = new Map();
  for (const l of romantic) {
    if (!adj.has(l.source.id)) adj.set(l.source.id, []);
    if (!adj.has(l.target.id)) adj.set(l.target.id, []);
    adj.get(l.source.id).push(l.target.id);
    adj.get(l.target.id).push(l.source.id);
  }
  const seenIds = new Set();
  let biggest = 0;
  for (const start of adj.keys()) {
    if (seenIds.has(start)) continue;
    let size = 0;
    const stack = [start];
    seenIds.add(start);
    while (stack.length) {
      size++;
      for (const next of adj.get(stack.pop()) || []) {
        if (seenIds.has(next)) continue;
        seenIds.add(next);
        stack.push(next);
      }
    }
    biggest = Math.max(biggest, size);
  }

  const married = romantic.filter(l => displayType(l) === 'Married').length;
  const split = romantic.filter(divorced).length;
  const going = romantic.filter(l => !over(l)).length;

  const rows = [
    ['♥', married, 'marriages', split ? `${split} since ended` : ''],
    ['•', going, 'still going', ''],
    ['●', biggest, 'in the largest tangle',
      adj.size ? `of ${adj.size} with any tie` : ''],
  ];
  if (busiest) rows.push(['⚑', busiest[1], 'ties', busiest[0]]);

  d3.select('#stats').selectAll('.stat')
    .data(rows)
    .join('div').attr('class', 'stat')
    .html(d => `<b>${d[1]}</b> ${d[2]}${d[3] ? ` <span class="who">${d[3]}</span>` : ''}`);
}

// Autocomplete. This was a <datalist>, which is one attribute and does the job
// on a desktop -- and on Android Chrome renders as a full-screen list of all 187
// names, over the chart and over the text being typed. Nothing about a datalist
// can be capped or styled, so the list is ours: at most 8 rows, anchored under
// the field, and dismissable. `castNames` is declared up in the hoisting block.
function refreshCastList() {
  castNames = DATA.nodes.filter(n => visible.has(n.id)).map(n => n.id).sort();
}

function autocomplete(input) {
  const list = document.getElementById(input.getAttribute('aria-controls'));
  if (!list) return;
  let items = [], active = -1;

  const close = () => {
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    items = []; active = -1;
  };

  const mark = i => {
    active = i;
    [...list.children].forEach((li, n) => {
      const on = n === i;
      li.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) {
        input.setAttribute('aria-activedescendant', li.id);
        li.scrollIntoView({ block: 'nearest' });
      }
    });
  };

  const choose = name => {
    input.value = name;
    close();
    // Same event the typing path fires, so selecting and typing cannot drift.
    // window.Event, not Event: identical in a browser, but under jsdom the
    // bare global is Node's own Event class and dispatchEvent rejects it.
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
    input.dispatchEvent(new window.Event('change', { bubbles: true }));
  };

  const open = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) return close();
    // Prefix matches first: typing "mer" should offer Meredith before Cormac.
    const hits = castNames
      .filter(n => n.toLowerCase().includes(q))
      .sort((a, b) => a.toLowerCase().indexOf(q) - b.toLowerCase().indexOf(q))
      .slice(0, 8);
    // An exact single hit is not a suggestion, it is what they already typed.
    if (!hits.length || (hits.length === 1 && hits[0].toLowerCase() === q)) return close();
    list.replaceChildren(...hits.map((name, i) => {
      const li = document.createElement('li');
      li.id = `${list.id}-o${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      const at = name.toLowerCase().indexOf(q);
      li.append(name.slice(0, at));
      const hit = document.createElement('b');
      hit.textContent = name.slice(at, at + q.length);
      li.append(hit, name.slice(at + q.length));
      // pointerdown, not click: on touch the input blurs first and a click
      // handler would fire after the list had already been torn down.
      li.addEventListener('pointerdown', e => { e.preventDefault(); choose(name); });
      return li;
    }));
    items = hits;
    active = -1;
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    place();
  };

  // Measured after showing, because the height depends on how many hits there
  // are. visualViewport is what shrinks when a phone keyboard opens; innerHeight
  // does not, so using innerHeight here would put the list under the keyboard.
  const place = () => {
    const box = input.getBoundingClientRect();
    const vh = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
    const below = vh - box.bottom;
    const above = box.top;
    list.classList.remove('above');
    list.style.maxHeight = '';
    const needed = list.offsetHeight;
    // Only flip if there is genuinely more room the other way -- flipping into
    // an equally bad space just moves the problem.
    const flip = needed > below - 10 && above > below;
    if (flip) list.classList.add('above');
    list.style.maxHeight = Math.max(96, (flip ? above : below) - 12) + 'px';
  };

  input.addEventListener('input', open);
  input.addEventListener('focus', open);
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', e => {
    if (list.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); mark((active + 1) % items.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); mark((active - 1 + items.length) % items.length); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(items[active]); }
    else if (e.key === 'Escape') { close(); }
  });
}

['search', 'from', 'to'].forEach(id => {
  const el = document.getElementById(id);
  if (el) autocomplete(el);
});

/* ---- report a problem ---------------------------------------------------- */
// Two delivery paths, neither of which requires this page to hold a credential.
// A static page cannot keep a secret -- any token shipped here is public -- so
// the API is never called from the browser.
//
//   RELAY: set this to a deployed endpoint and the form POSTs to it directly,
//          no GitLab account needed and no mail client involved. The endpoint
//          holds the token; see relay/ in the repo. Left empty by default
//          because it is a service to run, not a file to ship.
//   Otherwise: GitLab's own issue form (pre-filled, spam-handled by GitLab) for
//          anyone with an account, and Service Desk email for anyone without.
const RELAY = '';
const PROJECT = 'sstangle73/greys-network';
const SERVICE_DESK =
  'contact-project+sstangle73-greys-network-85043144-issue-@incoming.gitlab.com';

const dialog = document.getElementById('report');
const reportNote = document.getElementById('report-note');

// The whole point: a bug report about a spoiler-aware chart is unactionable
// without knowing where the reporter was standing when they saw it.
function reportContext() {
  const where = DATA.shows.map(sh => {
    if (!enabled.has(sh.key)) return `${sh.key}: off`;
    const c = cuts[sh.key];
    return `${sh.key}: ` + (c.s < 1 ? 'not yet aired' : `S${c.s} E${c.e}`);
  }).join('\n  ');
  const hidden = Object.keys(TYPES).filter(t => !active.has(t));
  return [
    'Chart state',
    '  ' + where,
    `  types hidden: ${hidden.length ? hidden.join(', ') : 'none'}`,
    `  past relationships: ${showPast ? 'shown' : 'hidden'}`,
    `  selected: ${selected || 'nobody'}`,
    `  on screen: ${visible.size} people, ${drawnLinks().length} connections`,
    '',
    `Permalink: ${window.location.href}`,
  ].join('\n');
}

function openReport() {
  document.getElementById('report-preview').textContent = reportContext();
  reportNote.textContent = '';
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
}

function closeReport() {
  if (typeof dialog.close === 'function') dialog.close();
  else dialog.removeAttribute('open');
}

function sendReport() {
  const kind = document.getElementById('report-kind').value;
  const body = document.getElementById('report-body').value.trim();
  const trap = document.getElementById('report-website').value;

  if (!body) {
    reportNote.textContent = 'Please describe what you saw first.';
    return;
  }
  // Silently accept and discard: telling a bot it failed just teaches it.
  if (trap) { closeReport(); return; }

  const title = `[${kind}] reported from the chart`;
  const full = `${body}\n\n---\n${reportContext()}`;

  if (RELAY) {
    reportNote.textContent = 'Sending…';
    fetch(RELAY, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, body: full, website: trap }),
    })
      .then(r => {
        if (!r.ok) throw new Error(r.status);
        reportNote.textContent = 'Thank you — your report was filed.';
        setTimeout(closeReport, 1400);
      })
      .catch(() => {
        reportNote.innerHTML =
          'That did not go through. You can ' + fallbackLinks(title, full);
      });
    return;
  }

  reportNote.innerHTML = 'Choose how to send it: ' + fallbackLinks(title, full);
}

function fallbackLinks(title, full) {
  const issue = `https://gitlab.com/${PROJECT}/-/issues/new`
    + `?issue[title]=${encodeURIComponent(title)}`
    + `&issue[description]=${encodeURIComponent(full)}`;
  const mail = `mailto:${SERVICE_DESK}`
    + `?subject=${encodeURIComponent(title)}`
    + `&body=${encodeURIComponent(full)}`;
  return `<a href="${issue}" target="_blank" rel="noopener noreferrer">open a GitLab issue</a>`
    + ` (needs an account, everything pre-filled), or `
    + `<a href="${mail}">send it by email</a> (no account needed).`;
}

document.getElementById('report-open').addEventListener('click', openReport);
document.getElementById('report-cancel').addEventListener('click', closeReport);
document.getElementById('report-send').addEventListener('click', sendReport);

/* ---- rail tabs ----------------------------------------------------------- */
const tabButtons = [...document.querySelectorAll('.tabs [role="tab"]')];
const panels = [...document.querySelectorAll('[data-panel]')];
function showTab(name) {
  tabButtons.forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  panels.forEach(p => { p.hidden = p.dataset.panel !== name; });
}
tabButtons.forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

/* ---- timeline playback --------------------------------------------------- */
// Walks one show's cutoff forward an episode at a time so the network can be
// watched assembling itself. Deliberately does NOT refit between frames: the
// camera chasing a growing graph is unwatchable, and the whole point is to see
// where new ties appear relative to the ones already there.
let playTimer = null;
let playShow = 'GA';

// Airdate alignment. The spinoffs premiered alongside a specific Grey's season
// -- Private Practice season 1 opposite Grey's season 4, Station 19 season 1
// opposite Grey's season 14 -- so "play the universe" drives the Grey's clock
// and derives the others from it. Season order and broadcast order are not the
// same thing, and this is the difference.
const AIRDATE_OFFSET = { GA: 0, PP: 3, S19: 13 };

function playableEnd(key) {
  const meta = SHOW_BY_KEY[key];
  return { s: meta.seasons, e: meta.episodes };
}

function atEnd(key) {
  const end = playableEnd(key);
  return cuts[key].s >= end.s && cuts[key].e >= end.e;
}

// Push a cutoff into both the state and its slider.
function setCut(key, s, e) {
  cuts[key] = { s, e };
  const sfx = key === 'GA' ? '' : '-' + key;
  const ss = document.getElementById('season' + sfx);
  const ee = document.getElementById('episode' + sfx);
  if (ss) ss.value = Math.max(1, s);
  if (ee) ee.value = Math.max(1, e);
}

// Given where Grey's is, where should the other shows be?
function syncUniverse(gaSeason, gaEpisode) {
  for (const key of Object.keys(cuts)) {
    if (key === 'GA') continue;
    const meta = SHOW_BY_KEY[key];
    const season = gaSeason - (AIRDATE_OFFSET[key] || 0);
    if (season < 1) {
      // Hasn't premiered yet at this point in the run. Season 0 reads as
      // "nothing has aired" everywhere that compares against a cutoff.
      setCut(key, 0, 0);
    } else if (season > meta.seasons) {
      setCut(key, meta.seasons, meta.episodes);       // finished; hold at the end
    } else {
      setCut(key, season, Math.min(gaEpisode, meta.episodes));
    }
  }
}

function stepPlayback() {
  const universe = playShow === 'ALL';
  const key = universe ? 'GA' : playShow;
  const meta = SHOW_BY_KEY[key];
  let { s, e } = cuts[key];
  e += 1;
  if (e > meta.episodes) { e = 1; s += 1; }
  if (s > meta.seasons) { stopPlayback(); return; }
  setCut(key, s, e);
  if (universe) syncUniverse(s, e);
  applyCutoff(false);
  if (atEnd(key)) stopPlayback();
}

function setPlayUI(running) {
  const btn = document.getElementById('play');
  const mini = document.getElementById('play-mini');
  if (btn) {
    btn.textContent = running ? 'Pause' : 'Play';
    btn.setAttribute('aria-pressed', String(running));
  }
  if (mini) {
    mini.innerHTML = running ? '⏸' : '▶';
    mini.setAttribute('aria-pressed', String(running));
    mini.setAttribute('aria-label', running ? 'Pause the timeline' : 'Play the timeline');
  }
}

function stopPlayback() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  setPlayUI(false);
}

function startPlayback() {
  const key = document.getElementById('play-show').value;
  playShow = key;
  const driver = key === 'ALL' ? 'GA' : key;

  const turnOn = k => {
    if (enabled.has(k)) return;
    const box = document.getElementById(k === 'GA' ? 'on' : 'on-' + k);
    if (box) { box.checked = true; box.dispatchEvent(new window.Event('change')); }
  };
  key === 'ALL' ? Object.keys(cuts).forEach(turnOn) : turnOn(key);

  // Starting from the end and immediately stopping is a confusing no-op, so
  // rewind to the beginning first.
  if (atEnd(driver)) {
    setCut(driver, 1, 1);
    if (key === 'ALL') syncUniverse(1, 1);
    applyCutoff(false);
  }
  setPlayUI(true);
  playTimer = setInterval(stepPlayback, 260);
}

// "Whole universe" first, because watching the three shows interleave in
// broadcast order is the more interesting thing this can do.
d3.select('#play-show').selectAll('option')
  .data([{ key: 'ALL', title: 'Whole universe' }].concat(DATA.shows))
  .join('option')
  .attr('value', sh => sh.key)
  .text(sh => sh.title);

function togglePlayback() { playTimer ? stopPlayback() : startPlayback(); }
document.getElementById('play').addEventListener('click', togglePlayback);
document.getElementById('play-mini').addEventListener('click', togglePlayback);
// Touching any cutoff by hand means you have taken over.
document.getElementById('play-show').addEventListener('change', stopPlayback);

/* ---- trace a connection -------------------------------------------------- */
// Breadth-first over the links that are ACTUALLY ON SCREEN, so a route can never
// run through a relationship the viewer hasn't reached yet. Searching the full
// graph and then hiding the result would leak exactly what the cutoff exists to
// hide -- "Meredith to Maya in 3 steps" tells you the steps exist.
// (pathIds is declared up with the other boot-time state.)

function shortestPath(fromId, toId) {
  if (fromId === toId) return [fromId];
  const adj = new Map();
  for (const l of drawnLinks()) {
    if (!adj.has(l.source.id)) adj.set(l.source.id, []);
    if (!adj.has(l.target.id)) adj.set(l.target.id, []);
    adj.get(l.source.id).push([l.target.id, l]);
    adj.get(l.target.id).push([l.source.id, l]);
  }
  const prev = new Map([[fromId, null]]);
  const queue = [fromId];
  while (queue.length) {
    const at = queue.shift();
    if (at === toId) break;
    for (const [next, l] of adj.get(at) || []) {
      if (prev.has(next)) continue;
      prev.set(next, [at, l]);
      queue.push(next);
    }
  }
  if (!prev.has(toId)) return null;
  const chain = [];
  for (let at = toId; at !== fromId; ) {
    const [before, l] = prev.get(at);
    chain.unshift({ from: before, to: at, link: l });
    at = before;
  }
  return chain;
}

function clearPath() {
  pathIds = new Set();
  link.classed('on-path', false);
  node.classed('on-path', false);
  marker.classed('on-path', false);
}

// Resolve loosely so "meredith" finds "Meredith Grey" -- exact first, then
// unique prefix, then unique substring.
function resolveName(raw) {
  const q = raw.trim().toLowerCase();
  if (!q) return null;
  const pool = DATA.nodes.filter(n => visible.has(n.id));
  const exact = pool.find(n => n.id.toLowerCase() === q);
  if (exact) return exact.id;
  for (const test of [n => n.id.toLowerCase().startsWith(q),
                      n => n.id.toLowerCase().includes(q)]) {
    const hits = pool.filter(test);
    if (hits.length === 1) return hits[0].id;
    if (hits.length > 1) return { ambiguous: hits.slice(0, 4).map(n => n.id) };
  }
  return null;
}

const traceOut = document.getElementById('trace-out');

function runTrace() {
  clearPath();
  const a = resolveName(document.getElementById('from').value);
  const b = resolveName(document.getElementById('to').value);

  for (const [label, hit] of [['From', a], ['To', b]]) {
    if (!hit) {
      traceOut.innerHTML = `<span class="miss">${label}: no one on screen by that name.</span>`;
      return;
    }
    if (hit.ambiguous) {
      traceOut.innerHTML = `<span class="miss">${label} is ambiguous:</span> ${hit.ambiguous.join(', ')}`;
      return;
    }
  }

  const chain = shortestPath(a, b);
  if (!chain) {
    traceOut.innerHTML = `<span class="miss">No route between them at this point in the show.</span>`;
    return;
  }
  if (!chain.length || a === b) {
    traceOut.innerHTML = `<span class="hop">${a}</span>`;
    return;
  }

  const onPath = new Set(chain.map(step => step.link));
  pathIds = new Set([a, ...chain.map(step => step.to)]);
  link.classed('on-path', l => onPath.has(l));
  marker.classed('on-path', l => onPath.has(l));
  node.classed('on-path', n => pathIds.has(n.id));

  const degrees = chain.length;
  traceOut.innerHTML =
    `<div>${degrees} step${degrees === 1 ? '' : 's'}</div>` +
    `<div><span class="hop">${a}</span>` +
    chain.map(step =>
      ` <span class="via">&rarr; ${displayType(step.link).toLowerCase()} &rarr;</span> ` +
      `<span class="hop">${step.to}</span>`).join('') +
    `</div>`;
  updateLabels();
  writeHash();
}

document.getElementById('trace-go').addEventListener('click', runTrace);
for (const id of ['from', 'to']) {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') runTrace();
  });
}

/* ---- shareable state ----------------------------------------------------- */
// The page is a single file with no server, so the URL hash is the only place
// a view can live. Without this, "look at S7" is unshareable.
// (hashLoading is declared up with the other boot-time state.)

function writeHash() {
  if (hashLoading) return;
  const parts = [];
  DATA.shows.forEach(sh => {
    if (!enabled.has(sh.key)) { parts.push(`${sh.key}=off`); return; }
    parts.push(`${sh.key}=${cuts[sh.key].s}.${cuts[sh.key].e}`);
  });
  const off = Object.keys(TYPES).filter(t => !active.has(t));
  if (off.length) parts.push('hide=' + off.join('+'));
  if (!showPast) parts.push('past=0');
  if (spacing !== 1) parts.push('sp=' + spacing.toFixed(1));
  if (selected) parts.push('sel=' + encodeURIComponent(selected));
  const f = document.getElementById('from').value.trim();
  const t = document.getElementById('to').value.trim();
  if (f && t) parts.push(`trace=${encodeURIComponent(f)}~${encodeURIComponent(t)}`);
  // Qualified off `window` rather than relying on bare globals: the page script
  // is executed with window passed in explicitly, so bare `history` resolves to
  // a global that does not exist outside a browser.
  if (!window.history || !window.history.replaceState) return;
  // Opening the file straight off disk is a supported way to use this, and a
  // file:// document cannot always have its URL rewritten. A shareable link is
  // a nicety; it must never take the chart down with it.
  try {
    window.history.replaceState(
      null, '', parts.length ? '#' + parts.join('&') : window.location.pathname);
  } catch (e) { /* no addressable URL - the chart still works */ }
}

function readHash() {
  const raw = (window.location && window.location.hash || '').replace(/^#/, '');
  if (!raw) return false;
  hashLoading = true;
  let trace = null;
  for (const chunk of raw.split('&')) {
    const [key, value] = chunk.split('=');
    if (!value) continue;
    if (cuts[key]) {
      if (value === 'off') {
        enabled.delete(key);
        const box = document.getElementById(key === 'GA' ? 'on' : 'on-' + key);
        if (box) { box.checked = false; box.dispatchEvent(new window.Event('change')); }
      } else {
        const [s, e] = value.split('.').map(Number);
        // 0 is meaningful in universe playback: "this show had not premiered
        // yet". A plain truthiness check silently dropped it.
        if (!isNaN(s)) {
          cuts[key] = { s, e: e || 1 };
          const sfx = key === 'GA' ? '' : '-' + key;
          const ss = document.getElementById('season' + sfx);
          const ee = document.getElementById('episode' + sfx);
          if (ss) ss.value = s;
          if (ee) ee.value = e || 1;
        }
      }
    } else if (key === 'hide') {
      value.split('+').forEach(t => {
        active.delete(t);
        const box = document.querySelector(`[data-type="${t}"]`);
        if (box) box.checked = false;
      });
    } else if (key === 'past' && value === '0') {
      showPast = false;
      const box = document.getElementById('past');
      if (box) box.checked = false;
    } else if (key === 'sp') {
      spacing = Math.max(0.6, Math.min(2.2, parseFloat(value) || 1));
      const sp = document.getElementById('spacing');
      if (sp) sp.value = Math.round(spacing * 10);
      d3.select('#spacing-read').text(spacing.toFixed(1) + '×');
    } else if (key === 'sel') {
      selected = decodeURIComponent(value);
    } else if (key === 'trace') {
      trace = value.split('~').map(decodeURIComponent);
    }
  }
  hashLoading = false;
  if (trace && trace.length === 2) {
    document.getElementById('from').value = trace[0];
    document.getElementById('to').value = trace[1];
  }
  return { trace: !!trace };
}

/* ---- rail toggle -------------------------------------------------------- */
const rail = document.getElementById('rail');
const railToggle = document.getElementById('rail-toggle');
railToggle.onclick = () => {
  const open = rail.classList.toggle('collapsed') === false;
  railToggle.setAttribute('aria-expanded', String(open));
  fitToView();
};

/* ---- resize ------------------------------------------------------------- */
let resizeTimer;
window.addEventListener('resize', () => {
  sizeSvg();
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => fitToView(), 150);
});

/* ---- boot from a shared link -------------------------------------------- */
// Last, because readHash() drives the per-show sliders and the legend, and none
// of those elements exist until the blocks above have built them.
(function bootFromHash() {
  const restored = readHash();
  if (!restored) return;
  applyCutoff(false);
  fitToView(0, initialFloor());
  if (selected) {
    const who = DATA.nodes.find(n => n.id === selected);
    if (who && visible.has(who.id)) { select(who); centreOn(who, 0); }
    else selected = null;
  }
  if (restored.trace) runTrace();
})();
</script>
</body>
</html>
"""


def render(graph: dict) -> str:
    return (
        TEMPLATE
        .replace("__D3_CDN__", D3_CDN)
        .replace("__NODE_COUNT__", str(len(graph["nodes"])))
        .replace("__LINK_COUNT__", str(len(graph["links"])))
        .replace("__GRAPH_DATA__", json.dumps(graph))
    )


def main(indir: str, out: str) -> None:
    graph = load_graph(indir)
    # newline="\n" so the emitted HTML is byte-identical on Windows and POSIX.
    # Without it Python translates to CRLF here, and the test harness matches on
    # "<script>\n(const DATA...".
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(graph))
    print(f"Wrote {out} ({len(graph['nodes'])} nodes, {len(graph['links'])} links)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the network visualization.")
    parser.add_argument("--indir", default=".", help="Directory holding nodes.csv and edges.csv")
    parser.add_argument("--out", default="greys_network.html", help="Output HTML path")
    args = parser.parse_args()
    main(args.indir, args.out)
