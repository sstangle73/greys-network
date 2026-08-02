import fs from 'fs';
import { JSDOM } from 'jsdom';
import * as d3 from 'd3';
const html=fs.readFileSync('greys_network.html','utf8');
const script=html.match(/<script>\n(const DATA.*?)\n<\/script>/s)[1];
const dom=new JSDOM(html.replace(/<script[\s\S]*?<\/script>/g,''),{pretendToBeVisual:true});
const {window}=dom;
Object.defineProperty(window,'innerWidth',{value:412,configurable:true});
Object.defineProperty(window,'innerHeight',{value:915,configurable:true});
global.window=window; global.document=window.document; global.d3=d3;
global.SVGElement=window.SVGElement;
// d3-zoom reads navigator.maxTouchPoints. Node 21+ has a built-in navigator so
// this passes locally without it; Node 20 does not, and CI failed where the
// dev machine was green. Take it from jsdom rather than from the runtime.
global.navigator=window.navigator;
global.requestAnimationFrame=window.requestAnimationFrame.bind(window);
new Function('window','document','d3',script)(window,window.document,d3);
const doc=window.document;

function report(label){
  const nodes=[...doc.querySelectorAll('.node')];
  const withT=nodes.filter(n=>n.getAttribute('transform'));
  const atOrigin=withT.filter(n=>/translate\(0,\s*0\)/.test(n.getAttribute('transform')));
  const links=[...doc.querySelectorAll('.link')];
  const withD=links.filter(l=>l.getAttribute('d'));
  const coords=withT.map(n=>n.getAttribute('transform'));
  const distinct=new Set(coords).size;
  console.log(`${label}
  nodes painted:   ${withT.length}/${nodes.length}   (at origin: ${atOrigin.length})
  distinct positions: ${distinct}
  links with a path: ${withD.length}/${links.length}`);
  return withT.length===nodes.length && withD.length===links.length && distinct>50;
}
const bootOk=report('at boot:');

// spacing change goes through relayout()
const sp=doc.getElementById('spacing'); sp.value=14;
sp.dispatchEvent(new window.Event('input',{bubbles:true}));
sp.dispatchEvent(new window.Event('change',{bubbles:true}));
const spacingOk=report('\nafter spacing change:');

// cutoff change goes through applyCutoff()
const se=doc.getElementById('season'); se.value=12;
se.dispatchEvent(new window.Event('input',{bubbles:true}));
const cutoffOk=report('\nafter cutoff change:');

console.log('\n'+(bootOk&&spacingOk&&cutoffOk ? 'PASS - chart is painted in every path' : 'FAIL'));
process.exit(bootOk&&spacingOk&&cutoffOk?0:1);
