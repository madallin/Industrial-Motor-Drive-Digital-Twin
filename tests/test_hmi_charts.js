'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'../dashboard/charts.js'),'utf8');
function chartHarness(globals={}){const context=vm.createContext(globals);vm.runInContext(script,context);return expression=>vm.runInContext(expression,context);}

test('autoscale remains stable under noise and expands to include a new extreme',()=>{
  const run=chartHarness();
  run('var initial=stableScale(0,1500,null)');
  assert.equal(run('stableScale(10,1490,initial)===initial'),true);
  assert.equal(run('stableScale(0,1501,initial)===initial'),true);
  const expanded=run('stableScale(-300,2600,initial)');
  assert.ok(expanded[0]<=-300&&expanded[1]>=2600);
  assert.ok(expanded[0]<=run('initial[0]')&&expanded[1]>=run('initial[1]'));
  const zero=run('stableScale(0,0,null)');
  assert.ok(zero.every(Number.isFinite)&&zero[1]>zero[0]);
});

test('declared sampling gaps break paths without treating decimation as data loss',()=>{
  const run=chartHarness();
  run("var gaps=missingIntervals([{cod:'DATA_GAP',t:5,valoare:2},{cod:'DATA_GAP',t:9,valoare:null}])");
  assert.equal(run('gaps.length'),1);
  assert.equal(run('crossesGap(2.5,5.5,gaps)'),true);
  assert.equal(run('crossesGap(1,2.9,gaps)'),false);
  assert.equal(run('crossesGap(5,6,gaps)'),false);
  assert.equal(run('crossesGap(0,100,[])'),false);
});

test('canvas caches unchanged data, renders nulls as gaps and keeps the cursor on samples',()=>{
  let draws=0;
  const paths=[];
  const ctx=new Proxy({
    moveTo:(x,y)=>paths.push(['move',x,y]),lineTo:(x,y)=>paths.push(['line',x,y]),
    getImageData:()=>{draws++;return {};},measureText:()=>({width:20})
  },{get:(o,k)=>o[k]||(()=>{})});
  const canvas={dataset:{},offsetWidth:600,getBoundingClientRect:()=>({width:600,height:300,left:0,top:0}),getContext:()=>ctx,setAttribute(){}};
  const nodes={canvas,empty:{},note:{dataset:{}},'chart-readout':{style:{},offsetWidth:160,offsetHeight:60}};
  const run=chartHarness({element:id=>nodes[id],text:(id,v)=>{nodes[id].textContent=v;},formatNumber:v=>String(v),selectedWindow:()=>30,
    window:{devicePixelRatio:1,innerWidth:800,innerHeight:600},document:{activeElement:null}});
  run("var points=[{t:0,rpm:1},{t:1,rpm:null},{t:2,rpm:3}];var options={session:'s1',mode:'auto',note:'note'}");
  const render="drawChart('canvas',points,[{key:'rpm',name:'Turație'}],'RPM','empty','Gol',options)";
  run(render);run(render);
  assert.equal(draws,1,'No repeated pixel copy for unchanged recording');
  const signalMoves=paths.filter(p=>p[0]==='move').slice(-2);
  assert.equal(signalMoves.length,2);
  assert.equal(paths.filter(p=>p[0]==='line').length,5,'Only grid lines connect; null sample splits the signal');
  canvas.onkeydown({key:'End',preventDefault(){}});
  assert.match(nodes['chart-readout'].textContent,/2 s\nTurație: 3 RPM/);
  canvas.onkeydown({key:'Escape',preventDefault(){}});
  assert.equal(nodes['chart-readout'].hidden,true);
  run("options.mode='fix';points[2].rpm=2200");run(render);
  assert.equal(nodes.note.dataset.outOfRange,true,'Fixed scale explicitly reports clipped data');
  run("options.session='s2';options.mode='auto';points=[]");run(render);
  assert.equal(canvas.hidden,true);assert.equal(nodes.empty.hidden,false);
  assert.equal(nodes.note.textContent,'');
});
