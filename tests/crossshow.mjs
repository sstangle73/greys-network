// Cross-show gating.
//
// Every date in the dataset belongs to exactly one show's numbering. The bug
// this guards against is a date being read against the wrong clock -- a
// Private Practice season 5 tie disappearing because the GREY'S slider moved,
// or a Station 19 tie showing up for someone who has the show switched off.
// That confusion is what put PP and S19 ties in Grey's seasons in the first
// place, so it gets a test rather than a comment.
import fs from 'fs';
import { JSDOM } from 'jsdom';
import * as d3 from 'd3';

const html = fs.readFileSync('greys_network.html', 'utf8');
const script = html.match(/<script>\n(const DATA.*?)\n<\/script>/s)[1];
const dom = new JSDOM(html.replace(/<script[\s\S]*?<\/script>/g, ''), { pretendToBeVisual: true });
const { window } = dom;
global.window = window; global.document = window.document; global.d3 = d3;
// d3-zoom reads navigator.maxTouchPoints; Node 20 has no built-in navigator.
global.navigator = window.navigator;
global.requestAnimationFrame = window.requestAnimationFrame.bind(window);
global.setTimeout = setTimeout; global.clearTimeout = clearTimeout;
new Function('window', 'document', 'd3', script)(window, window.document, d3);

const doc = window.document;
const fire = (el, t) => el.dispatchEvent(new window.Event(t, { bubbles: true }));

function linkVisible(a, b) {
  const paths = [...doc.querySelectorAll('.link')];
  const data = d3.selectAll('.link').data();
  for (let i = 0; i < paths.length; i++) {
    const d = data[i];
    if (!d) continue;
    const pair = new Set([d.source.id, d.target.id]);
    if (pair.has(a) && pair.has(b)) return paths[i].style.display !== 'none';
  }
  return null;   // no such edge
}

const checks = [];
const check = (label, got, want) => checks.push([label, got === want, `got ${got}, want ${want}`]);

// Defaults: Grey's pinned at S22 E02, the spinoffs open at their finales.
check('PP tie visible while Grey\'s sits at S22 E02',
      linkVisible('Addison Montgomery', 'Jake Reilly'), true);
check('S19 tie visible while Grey\'s sits at S22 E02',
      linkVisible('Carina DeLuca', 'Maya Bishop'), true);

// The Grey's slider must not govern another show's dates.
const ga = doc.getElementById('season'); ga.value = 1; fire(ga, 'input');
check('Grey\'s at S1 leaves the PP tie alone',
      linkVisible('Addison Montgomery', 'Jake Reilly'), true);
check('Grey\'s at S1 does hide a Grey\'s tie',
      linkVisible('Meredith Grey', 'Nick Marsh'), false);

// ...but that show's own slider must.
const pp = doc.getElementById('season-PP'); pp.value = 1; fire(pp, 'input');
check('PP at S1 hides a PP season 5 tie',
      linkVisible('Addison Montgomery', 'Jake Reilly'), false);

// Switching a show off removes its ties whatever the other clocks say.
const s19 = doc.getElementById('on-S19'); s19.checked = false; fire(s19, 'change');
check('Station 19 switched off hides its tie',
      linkVisible('Carina DeLuca', 'Maya Bishop'), false);

let bad = 0;
for (const [label, ok, detail] of checks) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : '  (' + detail + ')'}`);
  if (!ok) bad++;
}
console.log(bad ? `\n${bad} cross-show check(s) failed` : '\nCross-show gating correct.');
process.exit(bad ? 1 : 0);
