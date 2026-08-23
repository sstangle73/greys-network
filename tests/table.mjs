// Table filters.
//
// The table exists to be the version that works when the chart cannot: screen
// readers, text browsers, scripting off. Filtering is the only script on the
// page, so the thing most worth pinning is not that it filters -- it is that
// the page is still complete and inert WITHOUT it. Every assertion below either
// checks the no-JS reading survives, or checks a filter failure mode that would
// silently show the wrong data rather than error.
import fs from 'fs';
import { JSDOM } from 'jsdom';

const html = fs.readFileSync('table.html', 'utf8');
const checks = [];
const check = (label, ok, detail = '') => checks.push([label, ok, detail]);

// ---------------------------------------------------------------- no-JS ----
// Parsed with scripts disabled: exactly what a text browser or a reader with
// scripting off receives.
{
  const dom = new JSDOM(html, { runScripts: 'outside-only' });
  const doc = dom.window.document;
  const rows = doc.querySelectorAll('tbody tr:not([data-empty])');
  check('every row is in the HTML, not built by script', rows.length > 200,
        `${rows.length} rows`);
  check('no row starts hidden',
        [...rows].every(r => !r.hasAttribute('hidden')));
  check('empty-state rows start hidden',
        [...doc.querySelectorAll('[data-empty]')].every(r => r.hasAttribute('hidden')));
  // A control that cannot work must not be reachable by keyboard.
  check('filter UI is hidden until the script runs',
        !doc.documentElement.hasAttribute('data-js'));
  const css = html.split('</style>')[0];
  check('.filters is display:none by default',
        /\.filters\s*\{\s*display:\s*none/.test(css));
  check('.filters is revealed only under [data-js]',
        /\[data-js\]\s+\.filters\s*\{/.test(css));
}

// ------------------------------------------------------------- with JS ----
const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'https://localhost/greys/table.html',
});
const { window } = dom;
const doc = window.document;

const q = doc.getElementById('q');
const boxes = [...doc.querySelectorAll('#filters input[type=checkbox]')];
const rowsOf = name => [...doc.querySelectorAll(
  `table[data-table="${name}"] tbody tr:not([data-empty])`)];
const visible = name => rowsOf(name).filter(r => !r.hidden).length;
const fire = (el, t) => el.dispatchEvent(new window.Event(t, { bubbles: true }));

const totalRomantic = rowsOf('romantic').length;
const totalFamily = rowsOf('family').length;

check('script ran and revealed the controls',
      doc.documentElement.hasAttribute('data-js'));
check('nothing is filtered out on load',
      visible('romantic') === totalRomantic && visible('family') === totalFamily,
      `${visible('romantic')}/${totalRomantic}`);

// The failure this is really guarding: an empty group read as "match nothing"
// would open the page on an empty table.
check('counts read as unfiltered on load',
      /Showing all/.test(doc.querySelector('[data-count]').textContent));

// -- text search ------------------------------------------------------------
q.value = 'bailey';
fire(q, 'input');
const hits = rowsOf('romantic').filter(r => !r.hidden);
check('search narrows the table', hits.length > 0 && hits.length < totalRomantic,
      `${hits.length} hits`);
check('every surviving row actually matches',
      hits.every(r => r.dataset.names.includes('bailey')));
check('count reflects the filtered total',
      doc.querySelector('table[data-table="romantic"] [data-count]')
         .textContent.includes(`of ${totalRomantic}`));

// Searching covers the citation column, so an episode code finds its ties.
q.value = '18x01';
fire(q, 'input');
check('search matches citations, not just names',
      rowsOf('romantic').some(r => !r.hidden));

// -- no matches -------------------------------------------------------------
q.value = 'zzzzz-no-such-person';
fire(q, 'input');
check('a search with no hits shows the empty state, not a bare table',
      visible('romantic') === 0 &&
      !doc.querySelector('table[data-table="romantic"] [data-empty]').hidden);

// -- reset ------------------------------------------------------------------
fire(doc.getElementById('reset'), 'click');
check('clear restores every row',
      visible('romantic') === totalRomantic && visible('family') === totalFamily);
check('clear unticks every box', boxes.every(b => !b.checked));

// -- checkbox groups --------------------------------------------------------
const ga = boxes.find(b => b.name === 'show' && b.value === 'GA');
ga.checked = true;
fire(ga, 'input');
check('show filter keeps only that show',
      rowsOf('romantic').filter(r => !r.hidden).every(r => r.dataset.show === 'GA'));
check('show filter actually removed something',
      visible('romantic') < totalRomantic);

// Two ticks in one group is OR, not AND -- an AND would empty the table.
const s19 = boxes.find(b => b.name === 'show' && b.value === 'S19');
s19.checked = true;
fire(s19, 'input');
const twoShows = visible('romantic');
check('two ticks in a group widen the result (OR, not AND)',
      twoShows > rowsOf('romantic').filter(r => r.dataset.show === 'GA').length);

// Across groups it must be AND, or the filters do not compose.
const married = boxes.find(b => b.name === 'type' && b.value === 'Married');
married.checked = true;
fire(married, 'input');
check('separate groups compose as AND',
      rowsOf('romantic').filter(r => !r.hidden).every(
        r => r.dataset.type === 'Married' && ['GA', 'S19'].includes(r.dataset.show)));
check('cross-group filter is narrower than the show filter alone',
      visible('romantic') < twoShows);

// -- URL state --------------------------------------------------------------
check('filters are reflected in the URL', /show=/.test(window.location.hash),
      window.location.hash);

// A filtered link, opened cold, must come back to the same view.
{
  const hash = window.location.hash;
  const second = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://localhost/greys/table.html' + hash,
  });
  const d2 = second.window.document;
  const restored = [...d2.querySelectorAll('#filters input:checked')]
    .map(b => b.name + '=' + b.value).sort();
  check('a filtered URL restores its filters', restored.length === 3,
        restored.join(' '));
  const shown = [...d2.querySelectorAll(
    'table[data-table="romantic"] tbody tr:not([data-empty])')].filter(r => !r.hidden);
  check('a filtered URL restores the same rows',
        shown.length > 0 && shown.every(r => r.dataset.type === 'Married'));
}

// -- the round trip to the chart --------------------------------------------
// Both pages hold the same data and used to link only at page level, so finding
// a person here meant finding them again among 187 nodes there.
{
  const link = doc.querySelector('tbody a.who');
  check('names link into the chart', !!link && /greys_network\.html#sel=/.test(link.href),
        link ? link.getAttribute('href') : 'no link');
  // The href has to survive a name with a space, an apostrophe or an accent, or
  // the chart looks up a person who does not exist and silently selects nobody.
  const tricky = [...doc.querySelectorAll('tbody a.who')]
    .find(a => a.textContent.includes("O'Malley"));
  check('a name with an apostrophe is encoded',
        !!tricky && !/'/.test(tricky.getAttribute('href').split('#sel=')[1]),
        tricky ? tricky.getAttribute('href') : 'no O’Malley row');
  check('every name cell is linked',
        doc.querySelectorAll('tbody a.who').length ===
        doc.querySelectorAll('tbody tr:not([data-empty])').length * 2);
  // Links must not swallow the filter search: the row still matches on text.
  const row = link.closest('tr');
  check('linking did not break the search index',
        (row.dataset.names || '').includes(link.textContent.toLowerCase().split(' ')[0]));
}

// -- support link ----------------------------------------------------------
// Cheap to assert, easy to lose: it lives inside a template string in each
// builder, so a refactor can drop it without anything else noticing.
{
  const chart = fs.readFileSync('greys_network.html', 'utf8');
  const URL_RE = /https:\/\/buymeacoffee\.com\/stevenstorie/;
  check('table has the support link', URL_RE.test(html));
  check('chart has the support link', URL_RE.test(chart));
  // It opens in a new tab on the chart, so it needs the opener guard.
  const tag = chart.match(/<a href="https:\/\/buymeacoffee[^>]*>/);
  check('chart support link is rel-guarded',
        !!tag && /target="_blank"/.test(tag[0]) && /noopener/.test(tag[0]),
        tag ? tag[0] : 'no anchor');
}

// -- the E01 regression -----------------------------------------------------
// Episode 1 used to be suppressed on the assumption it was always a placeholder.
// Once the known-flags were filled in, that made real premieres read as vaguer
// than they are.
check('a known episode 1 renders as E01, not a bare season',
      /E01/.test(html));
check('unknown episodes still say so', /E\?\?/.test(html));

let bad = 0;
for (const [label, ok, detail] of checks) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${ok || !detail ? '' : '  (' + detail + ')'}`);
  if (!ok) bad++;
}
console.log(bad ? `\n${bad} table check(s) failed` : '\nTable filters behave.');
process.exit(bad ? 1 : 0);
