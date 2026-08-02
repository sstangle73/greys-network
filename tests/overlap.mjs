// Label overlap.
//
// The layout freezes after an initial solve, so whatever it produces is what
// you read -- there is no settling afterwards to rescue it. This measures how
// many visible node boxes intersect, which is the thing that actually makes the
// chart hard to read, and fails if it regresses past a threshold.
import fs from 'fs';
import { JSDOM } from 'jsdom';
import * as d3 from 'd3';

const html = fs.readFileSync('greys_network.html', 'utf8');
const script = html.match(/<script>\n(const DATA.*?)\n<\/script>/s)[1];
const dom = new JSDOM(html.replace(/<script[\s\S]*?<\/script>/g, ''),
  { pretendToBeVisual: true, url: 'https://localhost/greys/' });
const { window } = dom;
Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true });
Object.defineProperty(window, 'innerHeight', { value: 900, configurable: true });
global.window = window; global.document = window.document; global.d3 = d3;
global.SVGElement = window.SVGElement;
if (!globalThis.navigator) {
  Object.defineProperty(globalThis, 'navigator',
    { value: window.navigator, configurable: true });
}
global.requestAnimationFrame = window.requestAnimationFrame.bind(window);
global.setTimeout = setTimeout; global.clearTimeout = clearTimeout;

new Function('window', 'document', 'd3', script)(window, window.document, d3);

const nodes = d3.selectAll('.node').data()
  .filter(n => Number.isFinite(n.x) && Number.isFinite(n.y));

// Node boxes are centred on x,y. Compare in graph space: zoom scales everything
// equally, so a box that overlaps here overlaps at any zoom.
function box(n) {
  return { x0: n.x - n.w / 2, x1: n.x + n.w / 2, y0: n.y - n.h / 2, y1: n.y + n.h / 2 };
}

let pairs = 0, worst = 0, worstPair = null;
for (let i = 0; i < nodes.length; i++) {
  for (let j = i + 1; j < nodes.length; j++) {
    const a = box(nodes[i]), b = box(nodes[j]);
    const dx = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
    const dy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
    if (dx > 0 && dy > 0) {
      pairs++;
      const area = dx * dy;
      if (area > worst) { worst = area; worstPair = [nodes[i].id, nodes[j].id]; }
    }
  }
}

const pct = (100 * pairs / nodes.length).toFixed(1);
console.log(`  nodes            ${nodes.length}`);
console.log(`  overlapping pairs ${pairs}  (${pct} per 100 nodes)`);
if (worstPair) console.log(`  worst            ${worstPair.join('  /  ')}  ${worst.toFixed(0)}px2`);

// Threshold, not zero: a force layout of 183 nodes will always have some
// contact, and chasing zero would spread the graph until nothing is legible.
const LIMIT = Number(process.env.OVERLAP_LIMIT || 12);
const ok = pairs <= LIMIT;
console.log(ok ? `\nLayout is legible (limit ${LIMIT}).`
               : `\nToo much overlap: ${pairs} pairs, limit ${LIMIT}.`);
process.exit(ok ? 0 : 1);
