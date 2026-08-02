// Mobile filter interaction.
//
// Reported bug: "editing filters on mobile now gets stuck". On a phone the rail
// expands to fill the screen, which is a state the desktop path never reaches --
// and viewport() subtracts the rail's height from the available space.
import fs from 'fs';
import { JSDOM } from 'jsdom';
import * as d3 from 'd3';

const html = fs.readFileSync('greys_network.html', 'utf8');
const script = html.match(/<script>\n(const DATA.*?)\n<\/script>/s)[1];
const dom = new JSDOM(html.replace(/<script[\s\S]*?<\/script>/g, ''),
  { pretendToBeVisual: true, url: 'https://localhost/greys/' });
const { window } = dom;

// A phone, and a rail that actually reports a height like one.
Object.defineProperty(window, 'innerWidth', { value: 412, configurable: true });
Object.defineProperty(window, 'innerHeight', { value: 915, configurable: true });
global.window = window; global.document = window.document; global.d3 = d3;
global.SVGElement = window.SVGElement;
if (!globalThis.navigator) {
  Object.defineProperty(globalThis, 'navigator',
    { value: window.navigator, configurable: true });
}
global.requestAnimationFrame = window.requestAnimationFrame.bind(window);
global.setTimeout = setTimeout; global.clearTimeout = clearTimeout;

const doc = window.document;
// jsdom reports 0 for every offsetHeight, which hides the whole bug. Model the
// real thing: an expanded rail on a phone is nearly the full viewport tall.
const railEl = doc.getElementById('rail');
Object.defineProperty(doc.querySelector('header'), 'offsetHeight',
  { value: 96, configurable: true });
Object.defineProperty(railEl, 'offsetHeight',
  { get: () => railEl.classList.contains('collapsed') ? 52 : 860, configurable: true });
Object.defineProperty(railEl, 'offsetWidth', { value: 412, configurable: true });

new Function('window', 'document', 'd3', script)(window, window.document, d3);

const fire = (el, t) => el.dispatchEvent(new window.Event(t, { bubbles: true }));
const litLinks = () =>
  [...doc.querySelectorAll('.link')].filter(l => l.style.display !== 'none').length;
const litNodes = () =>
  [...doc.querySelectorAll('.node')].filter(n => n.style.display !== 'none').length;

const checks = [];
const check = (label, ok, detail = '') => checks.push([label, ok, detail]);

// Open the rail, as the reporter had it.
fire(doc.getElementById('rail-toggle'), 'click');
check('rail opens on mobile', !railEl.classList.contains('collapsed'));

const before = { links: litLinks(), nodes: litNodes() };

// Untick a type while the rail is open and covering the viewport.
const fling = doc.querySelector('[data-type="Fling"]');
fling.checked = false;
let threw = null;
try { fire(fling, 'change'); } catch (e) { threw = e; }
check('unticking a type does not throw', !threw, threw && threw.message);
const afterOff = { links: litLinks(), nodes: litNodes() };
check('unticking a type removes links', afterOff.links < before.links,
      `${before.links} -> ${afterOff.links}`);

// Re-tick it: this is the half people report as "stuck" -- the filter goes off
// but will not come back.
fling.checked = true;
try { fire(fling, 'change'); } catch (e) { threw = e; }
check('re-ticking does not throw', !threw, threw && threw.message);
const afterOn = { links: litLinks(), nodes: litNodes() };
check('re-ticking restores the links', afterOn.links === before.links,
      `${before.links} -> ${afterOff.links} -> ${afterOn.links}`);
check('re-ticking restores the cast', afterOn.nodes === before.nodes,
      `${before.nodes} -> ${afterOff.nodes} -> ${afterOn.nodes}`);

// Untick everything, then restore. An empty graph is the edge case most likely
// to wedge the camera.
const boxes = [...doc.querySelectorAll('#key input')];
try {
  boxes.forEach(b => { b.checked = false; fire(b, 'change'); });
} catch (e) { threw = e; }
check('unticking every type does not throw', !threw, threw && threw.message);
check('unticking every type empties the chart', litLinks() === 0, `${litLinks()} links lit`);
try {
  boxes.forEach(b => { b.checked = true; fire(b, 'change'); });
} catch (e) { threw = e; }
check('re-ticking every type does not throw', !threw, threw && threw.message);
check('chart comes back from empty', litLinks() === before.links,
      `${before.links} expected, got ${litLinks()}`);

// The reported bug: the rail grows upward from a fixed bottom edge, so once it
// is taller than the screen its collapse button rises off the top and there is
// no way back out. These guard the structure that keeps it reachable.
const railBody = doc.querySelector('.rail-body');
const toggle = doc.getElementById('rail-toggle');
check('collapse button is a direct child of the rail', toggle.parentElement === railEl,
      `parent is ${toggle.parentElement && toggle.parentElement.className}`);
check('collapse button is outside the scrolling body', !railBody.contains(toggle));

// The two views have to reach each other, by filenames that resolve both on the
// live site and in a local build. The table used to link to index.html, which
// only exists once CI has renamed it.
const chartHtml = fs.readFileSync('greys_network.html', 'utf8');
check('chart links to the table', /href="table\.html"/.test(chartHtml));
// The masthead is pointer-events:none so the graph stays draggable underneath
// it. Anything clickable placed in there must opt back in, or it renders
// perfectly and swallows every click.
const sheet = chartHtml.split('</style>')[0];
check('masthead link accepts clicks',
      /\.alt-view\s*\{[^}]*pointer-events:\s*auto/s.test(sheet));
for (const m of sheet.matchAll(/header\s*\{([^}]*)\}/gs)) {
  check('masthead itself still lets drags through',
        /pointer-events:\s*none/.test(m[1]));
}
if (fs.existsSync('table.html')) {
  const tableHtml = fs.readFileSync('table.html', 'utf8');
  check('table links back to the chart', /href="greys_network\.html"/.test(tableHtml));
  check('table does not link to a CI-only filename', !/href="index\.html"/.test(tableHtml));
} else {
  console.log('  --   table.html not built; run build_table.py');
}

const css = fs.readFileSync('greys_network.html', 'utf8')
  .split('</style>')[0];
check('rail height is capped', /\.rail\s*\{[^}]*max-height/s.test(css));
check('rail body scrolls', /\.rail-body\s*\{[^}]*overflow-y:\s*auto/s.test(css));
check('trace inputs are themed', /#search,\s*\.trace-form input/.test(css));

let bad = 0;
for (const [label, ok, detail] of checks) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${ok || !detail ? '' : '  (' + detail + ')'}`);
  if (!ok) bad++;
}
console.log(bad ? `\n${bad} mobile check(s) failed` : '\nMobile filters behave.');
process.exit(bad ? 1 : 0);
