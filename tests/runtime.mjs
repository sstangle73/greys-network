import fs from 'fs';
import { JSDOM } from 'jsdom';
import * as d3 from 'd3';

const html = fs.readFileSync('greys_network.html', 'utf8');
const script = html.match(/<script>\n(const DATA.*?)\n<\/script>/s)[1];

const dom = new JSDOM(html.replace(/<script[\s\S]*?<\/script>/g, ''), { pretendToBeVisual: true, url: 'https://localhost/greys/' });
const { window } = dom;

// Wire the globals the page expects, then execute its script for real.
global.window = window;
global.document = window.document;
global.d3 = d3;
// d3-zoom reads navigator.maxTouchPoints. Node 20 has no navigator global,
// Node 21+ has a getter-only one that plain assignment throws on.
if (!globalThis.navigator) {
  Object.defineProperty(globalThis, 'navigator',
    { value: window.navigator, configurable: true });
}
global.requestAnimationFrame = window.requestAnimationFrame.bind(window);
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;

const errors = [];
try {
  new Function('window','document','d3', script)(window, window.document, d3);
} catch (e) {
  errors.push(`BOOT: ${e.constructor.name}: ${e.message}`);
}

if (!errors.length) {
  const doc = window.document;
  const fire = (el, type) => el.dispatchEvent(new window.Event(type, { bubbles: true }));

  const trials = [
    ['season slider -> S10',  () => { doc.getElementById('season').value = 10; fire(doc.getElementById('season'), 'input'); }],
    ['episode slider -> E18', () => { doc.getElementById('episode').value = 18; fire(doc.getElementById('episode'), 'input'); }],
    ['season slider -> S1',   () => { doc.getElementById('season').value = 1; fire(doc.getElementById('season'), 'input'); }],
    ['back to S22 E02',       () => { doc.getElementById('season').value = 22; doc.getElementById('episode').value = 2;
                                      fire(doc.getElementById('season'), 'input'); }],
    ['uncheck Parent filter', () => { const cb = doc.querySelector('[data-type="Parent"]'); cb.checked = false; fire(cb, 'change'); }],
    ['search "grey"',         () => { const s = doc.getElementById('search'); s.value = 'grey'; fire(s, 'input'); }],
    ['clear search',          () => { const s = doc.getElementById('search'); s.value = ''; fire(s, 'input'); }],
    ['toggle rail',           () => fire(doc.getElementById('rail-toggle'), 'click')],
    ['fit button',            () => fire(doc.getElementById('fit'), 'click')],
    ['autocomplete populated',() => { const n = doc.querySelectorAll('#cast option').length;
                                      if (!n) throw new Error('datalist empty'); }],
    ['search dims markers',   () => { const s2 = doc.getElementById('search'); s2.value='meredith'; fire(s2,'input');
                                      const dimmed = [...doc.querySelectorAll('.marker')].filter(m=>m.classList.contains('dimmed')).length;
                                      const lit = [...doc.querySelectorAll('.marker')].filter(m=>!m.classList.contains('dimmed')).length;
                                      if (!dimmed || !lit) throw new Error(`markers dimmed=${dimmed} lit=${lit}`); }],
    ['search pins neighbours',() => { const shown=[...doc.querySelectorAll('.leaf-label')].filter(t=>t.style.display!=='none').length;
                                      if (!shown) throw new Error('no neighbour labels'); }],
    ['untick past relationships',()=>{const c=doc.getElementById('past');c.checked=false;fire(c,'change');
                                      const lit=[...doc.querySelectorAll('.link')].filter(l=>l.style.display!=='none').length;
                                      if(!lit) throw new Error('everything vanished');}],
    ['retick past',           ()=>{const c=doc.getElementById('past');c.checked=true;fire(c,'change');}],
    // Multi-show controls. These exist because Private Practice and Station 19
    // dates are in their OWN numbering -- a PP season 6 tie must not be gated
    // on the Grey's slider.
    ['per-show blocks built', ()=>{const n=doc.querySelectorAll('.show-block').length;
                                   if(n<3) throw new Error(`only ${n} show blocks`);}],
    ['S19 slider moves',      ()=>{const s=doc.getElementById('season-S19');
                                   if(!s) throw new Error('no Station 19 slider');
                                   s.value=1; fire(s,'input');}],
    ['PP slider moves',       ()=>{const s=doc.getElementById('season-PP');
                                   if(!s) throw new Error('no Private Practice slider');
                                   s.value=1; fire(s,'input');}],
    ['toggling PP off drops its ties', ()=>{
        const before=[...doc.querySelectorAll('.link')].filter(l=>l.style.display!=='none').length;
        const t=doc.getElementById('on-PP'); t.checked=false; fire(t,'change');
        const after=[...doc.querySelectorAll('.link')].filter(l=>l.style.display!=='none').length;
        if(after>before) throw new Error(`hiding a show added links: ${before} -> ${after}`);}],
    ['PP back on',            ()=>{const t=doc.getElementById('on-PP');t.checked=true;fire(t,'change');
                                   const s=doc.getElementById('season-PP');s.value=6;fire(s,'input');}],
    ['S19 back on',           ()=>{const s=doc.getElementById('season-S19');s.value=7;fire(s,'input');}],
    ['readout per show',      ()=>{for(const id of ['cutoff-read','cutoff-read-PP','cutoff-read-S19']){
                                     const el=doc.getElementById(id);
                                     if(!el||!el.textContent.trim()) throw new Error(`empty ${id}`);}}],
    ['panel shows spans',     ()=>{doc.querySelectorAll('.node .card')[0].dispatchEvent(new window.MouseEvent('click',{bubbles:true}));
                                   if(!doc.querySelector('.detail .when')) throw new Error('no span in panel');}],
    ['spacing -> 1.8x',       () => { const sp = doc.getElementById('spacing'); sp.value = 18;
                                      fire(sp, 'input'); fire(sp, 'change'); }],
    ['spacing -> 0.6x',       () => { const sp = doc.getElementById('spacing'); sp.value = 6;
                                      fire(sp, 'input'); fire(sp, 'change'); }],
    ['select a node',         () => { const g = doc.querySelectorAll('.node circle')[3];
                                      g.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); }],
    ['slide while selected',  () => { doc.getElementById('season').value = 5; fire(doc.getElementById('season'), 'input'); }],
    ['close panel',           () => fire(doc.getElementById('close'), 'click')],
    // Trace a connection. The route must be computed over the links actually on
    // screen -- routing through an unaired tie would leak what the cutoff hides.
    ['trace finds a route',   ()=>{doc.getElementById('season').value=22;
                                   fire(doc.getElementById('season'),'input');
                                   doc.getElementById('from').value='Meredith Grey';
                                   doc.getElementById('to').value='Cristina Yang';
                                   fire(doc.getElementById('trace-go'),'click');
                                   const out=doc.getElementById('trace-out').textContent;
                                   if(!/step/.test(out)) throw new Error(`no route: ${out}`);
                                   const lit=doc.querySelectorAll('.link.on-path').length;
                                   if(!lit) throw new Error('route found but nothing highlighted');}],
    // The romantic graph spans all three shows: Meredith reaches Private
    // Practice through Addison. If a future edit stranded a show, this breaks.
    ['trace crosses shows',   ()=>{doc.getElementById('from').value='Meredith Grey';
                                   doc.getElementById('to').value='Violet Turner';
                                   fire(doc.getElementById('trace-go'),'click');
                                   const out=doc.getElementById('trace-out').textContent;
                                   if(!/step/.test(out)) throw new Error(`shows are disconnected: ${out}`);}],
    // Bailey is genuinely unreachable from Meredith -- her only partners have no
    // other ties. A "no route" answer has to be honest, not a silent blank.
    ['trace reports no route',()=>{doc.getElementById('from').value='Meredith Grey';
                                   doc.getElementById('to').value='Miranda Bailey';
                                   fire(doc.getElementById('trace-go'),'click');
                                   const out=doc.getElementById('trace-out').textContent;
                                   if(!/No route/i.test(out)) throw new Error(`expected no route, got: ${out}`);}],
    ['trace resolves partial names',()=>{doc.getElementById('from').value='meredith grey';
                                   doc.getElementById('to').value='cristina';
                                   fire(doc.getElementById('trace-go'),'click');
                                   const out=doc.getElementById('trace-out').textContent;
                                   if(/no one on screen/.test(out)) throw new Error(out);}],
    ['trace reports an unknown name',()=>{doc.getElementById('from').value='Nobody McNobody';
                                   doc.getElementById('to').value='Meredith Grey';
                                   fire(doc.getElementById('trace-go'),'click');
                                   const out=doc.getElementById('trace-out').textContent;
                                   if(!/no one on screen/i.test(out)) throw new Error(`expected a miss, got: ${out}`);
                                   if(doc.querySelectorAll('.link.on-path').length)
                                     throw new Error('failed trace left a route highlighted');}],
    ['cutoff change clears the route',()=>{doc.getElementById('from').value='Meredith Grey';
                                   doc.getElementById('to').value='Miranda Bailey';
                                   fire(doc.getElementById('trace-go'),'click');
                                   doc.getElementById('season').value=3;
                                   fire(doc.getElementById('season'),'input');
                                   if(doc.querySelectorAll('.link.on-path').length)
                                     throw new Error('route survived a cutoff change');}],
    // The URL hash is the only place a view can live in a single-file page.
    ['state lands in the URL',()=>{doc.getElementById('season').value=7;
                                   fire(doc.getElementById('season'),'input');
                                   const h=window.location.hash;
                                   if(!/GA=7\./.test(h)) throw new Error(`hash missing cutoff: ${h}`);}],
    // Tabs: only one group is mounted at a time, which is what keeps the rail
    // short enough that its collapse button stays reachable on a phone.
    ['tabs mount one panel',  ()=>{const tabs=[...doc.querySelectorAll('.tabs [role="tab"]')];
                                   if(tabs.length<4) throw new Error(`${tabs.length} tabs`);
                                   const open=[...doc.querySelectorAll('[data-panel]')].filter(p=>!p.hidden);
                                   if(open.length!==1) throw new Error(`${open.length} panels visible`);}],
    ['switching tabs swaps the panel',()=>{
                                   fire(doc.querySelector('[data-tab="find"]'),'click');
                                   const open=[...doc.querySelectorAll('[data-panel]')].filter(p=>!p.hidden);
                                   if(open.length!==1||open[0].dataset.panel!=='find')
                                     throw new Error(`showing ${open.map(p=>p.dataset.panel)}`);
                                   fire(doc.querySelector('[data-tab="when"]'),'click');}],
    // Playback drives ONE show's cutoff. Pressing play at the end rewinds first
    // -- otherwise it stops instantly and looks broken. That rewind is
    // synchronous, so it can be asserted without waiting on the interval.
    ['play rewinds and engages',()=>{const season=doc.getElementById('season');
                                   const ppBefore=doc.getElementById('season-PP').value;
                                   season.value=22; doc.getElementById('episode').value=27;
                                   fire(season,'input');
                                   const btn=doc.getElementById('play');
                                   fire(btn,'click');
                                   if(btn.getAttribute('aria-pressed')!=='true')
                                     throw new Error('play did not engage');
                                   if(season.value!=='1')
                                     throw new Error(`expected rewind to S1, got S${season.value}`);
                                   if(doc.getElementById('season-PP').value!==ppBefore)
                                     throw new Error('playing Grey\'s moved another show');
                                   fire(btn,'click');
                                   if(btn.getAttribute('aria-pressed')!=='false')
                                     throw new Error('pause did not disengage');}],
    ['hidden types land in the URL',()=>{const cb=doc.querySelector('[data-type="Fling"]');
                                   cb.checked=false; fire(cb,'change');
                                   if(!/hide=.*Fling/.test(window.location.hash))
                                     throw new Error(`hash missing filter: ${window.location.hash}`);
                                   cb.checked=true; fire(cb,'change');}],
  ];

  for (const [name, fn] of trials) {
    try { fn(); console.log(`  ok   ${name}`); }
    catch (e) { errors.push(`${name}: ${e.constructor.name}: ${e.message}`); console.log(`  FAIL ${name}`); }
  }

  console.log(`\nreadout: ${doc.getElementById('cutoff-read').textContent} | ${doc.getElementById('tally').textContent}`);
  console.log(`note: "${doc.getElementById('cutoff-note').textContent}"`);
}

console.log(errors.length ? `\nERRORS:\n${errors.join('\n')}` : '\nNo runtime errors.');
process.exit(errors.length ? 1 : 0);
