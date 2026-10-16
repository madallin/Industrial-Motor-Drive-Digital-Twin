'use strict';

// Isolated presentation tests. No PSIM connection or recorded data is modified.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const script=fs.readFileSync(path.join(root,'dashboard/app.js'),'utf8');
const markup=fs.readFileSync(path.join(root,'dashboard/index.html'),'utf8');

test('all static UI element references exist in the HTML',()=>{
  const ids=new Set([...markup.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
  for(const file of ['app.js','charts.js']){
    const source=fs.readFileSync(path.join(root,'dashboard',file),'utf8');
    for(const [,id] of source.matchAll(/\b(?:element|text|renderTable|drawChart)\(\s*'([^']+)'/g)){
      if(id.endsWith('-'))continue; // Dynamic reading IDs are checked below.
      assert.ok(ids.has(id),`${file} references missing element ${id}`);
    }
  }
  for(const key of ['rpm','frecventa','curent','rms','vdc'])assert.ok(ids.has('reading-'+key));
});

function ui(overrides={}){
  const nodes=new Map([...markup.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],{
    value:'',textContent:'',dataset:{},hidden:false,disabled:false,
    checkValidity:()=>true,setCustomValidity(){},reportValidity:()=>true,
    replaceChildren(){},insertRow:()=>({dataset:{},insertCell:()=>({})})
  }]));
  for(const [id,value] of Object.entries({'frequency-input':'50','load-input':'5','acceleration-input':'2','deceleration-input':'5','time-window':'30'}))nodes.get(id).value=value;
  const requests=[];
  const fixture={psim:{ultim:null,achizitie:'INDISPONIBIL'},control:{limite:{frecventa_max_hz:50,sarcina_max_nm:10},psim:{
    disponibil:true,in_asteptare:false,confirmat:false,respins:false,expirat:false,
    aplicat:{drive_state:'READY',fault:0,pornit:false,frecventa_hz:50,sarcina_nm:5,acceleration_s:2,deceleration_s:5},...overrides
  }}};
  const context=vm.createContext({
    fixture,AbortSignal,
    document:{getElementById:id=>{assert.ok(nodes.has(id),'Missing HTML element: '+id);return nodes.get(id);},addEventListener(){}},
    localStorage:{setItem(){},getItem(){return null;}},
    fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({secventa:1})};}
  });
  vm.runInContext(script,context);
  vm.runInContext('appState.system=fixture;renderControls()',context);
  return {nodes,context,requests,run:code=>vm.runInContext(code,context)};
}

test('READY permits explicit START; displaying state never sends commands',()=>{
  const h=ui();
  assert.equal(h.nodes.get('start-command').disabled,false);
  assert.equal(h.nodes.get('stop-command').disabled,true);
  assert.equal(h.nodes.get('apply-references').disabled,true);
  assert.equal(h.requests.length,0);
  assert.equal(h.nodes.get('controller-state').textContent,'Pregătit');
});

test('navigation selects the requested page and keeps the tab state in sync',()=>{
  const h=ui();
  const tabs=[...markup.matchAll(/<button data-page="([^"]+)"/g)].map(([,page])=>({
    dataset:{page},selected:page==='operation',attributes:{},
    classList:{toggle(name,active){assert.equal(name,'selected');this.active=active;}},
    setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];}
  }));
  const sections=[...markup.matchAll(/<section id="(page-[^"]+)"/g)].map(([,id])=>({id,hidden:id!=='page-operation'}));
  h.nodes.get('time-window').closest=()=>({hidden:false});
  h.context.document.querySelectorAll=selector=>selector==='nav button'?tabs:sections;
  h.run('refresh=()=>{};drawCharts=()=>{};navigate("recordings")');
  assert.equal(h.run('appState.page'),'recordings');
  assert.equal(h.nodes.get('page-title').textContent,'Înregistrări');
  assert.deepEqual(sections.map(section=>section.hidden),[true,true,false]);
  assert.deepEqual(tabs.map(tab=>tab.classList.active),[false,false,true]);
  assert.equal(tabs[2].attributes['aria-current'],'page');
});

test('running, stopping and coasting states prevent accidental restart',()=>{
  for(const state of ['RUNNING','STOPPING','COASTING']){
    const h=ui();
    h.run(`fixture.control.psim.aplicat.drive_state='${state}';fixture.control.psim.aplicat.pornit=${state==='RUNNING'};renderControls()`);
    assert.equal(h.nodes.get('start-command').disabled,true,state);
    assert.equal(h.nodes.get('drive-status').dataset.state,state);
    if(state==='RUNNING')assert.equal(h.nodes.get('stop-command').disabled,false);
  }
});

test('STOP remains available while a START request is pending',()=>{
  const h=ui({in_asteptare:true,cerut:{pornit:true,secventa:17}});
  assert.equal(h.nodes.get('start-command').disabled,true);
  assert.equal(h.nodes.get('stop-command').disabled,false);
  assert.match(h.nodes.get('command-confirmation').textContent,/confirmarea/);
  assert.doesNotMatch(h.nodes.get('command-confirmation').textContent,/#17|ACK/);
});

test('fault exposes its cause and reset without enabling START',()=>{
  const h=ui();
  h.run("Object.assign(fixture.control.psim.aplicat,{drive_state:'FAULT',fault:1});renderControls()");
  assert.equal(h.nodes.get('start-command').disabled,true);
  assert.equal(h.nodes.get('reset-command').hidden,false);
  assert.equal(h.nodes.get('reset-command').disabled,false);
  assert.match(h.nodes.get('control-reason').textContent,/Supracurent/);
});

test('disconnected state disables actions but allows preparing references',()=>{
  const h=ui({disponibil:false,motiv:'Control indisponibil: legatura cu DLL/PSIM este intrerupta.'});
  for(const id of ['start-command','stop-command','apply-references'])assert.equal(h.nodes.get(id).disabled,true);
  assert.equal(h.nodes.get('frequency-input').disabled,false);
  assert.match(h.nodes.get('control-reason').textContent,/Pornește simularea/);
  assert.equal(h.nodes.get('command-confirmation').hidden,true);
});

test('editing a reference marks it unapplied and does not submit it',()=>{
  const h=ui();
  h.nodes.get('frequency-input').value='30';
  h.run('saveDraft()');
  assert.equal(h.nodes.get('draft-status').hidden,false);
  assert.equal(h.nodes.get('apply-references').disabled,false);
  assert.equal(h.requests.length,0);
});

test('invalid collapsed ramp field is revealed and blocks submission',async()=>{
  const h=ui();
  h.nodes.get('acceleration-input').checkValidity=()=>false;
  h.nodes.get('control-form').reportValidity=()=>false;
  await h.run("sendCommand('porneste')");
  assert.equal(h.nodes.get('ramp-settings').open,true);
  assert.equal(h.requests.length,0);
});

test('START sends edited references; STOP does not depend on field validity',async()=>{
  const h=ui();
  h.nodes.get('frequency-input').value='30';
  h.run('appState.busy=true'); // Do not run background polling in this isolated test.
  await h.run("sendCommand('porneste')");
  assert.deepEqual(JSON.parse(h.requests[0].options.body),{tinta:'psim',actiune:'porneste',frecventa_hz:30,sarcina_nm:5,acceleration_s:2,deceleration_s:5});
  h.nodes.get('control-form').reportValidity=()=>false;
  await h.run("sendCommand('opreste')");
  assert.deepEqual(JSON.parse(h.requests[1].options.body),{tinta:'psim',actiune:'opreste'});
});

test('loss of HTTP clears readings and withdraws stale motor state',async()=>{
  const h=ui();
  h.context.fetch=async()=>{throw new TypeError('Failed to fetch');};
  h.run("fixture.control.psim.aplicat.drive_state='RUNNING';renderControls()");
  await h.run('refresh()');
  for(const id of ['start-command','stop-command','reset-command','apply-references'])assert.equal(h.nodes.get(id).disabled,true);
  for(const key of ['rpm','frecventa','curent','rms','vdc'])assert.equal(h.nodes.get('reading-'+key).textContent,'—');
  assert.equal(h.nodes.get('drive-status').dataset.state,'offline');
  assert.equal(h.nodes.get('controller-state').textContent,'Indisponibil');
});

test('successful API polling restores live readings and controls after a connection failure',async()=>{
  const h=ui();
  const response=structuredClone(h.context.fixture);
  response.receptie={eroare:'',conectat:true,actual:true};
  response.psim={achizitie:'ACTIV',ultim:{t:3,rpm:0,curent:0,rms:0,vdc:565.7,frecventa:0},puncte:[]};
  // Chart rendering is covered separately; exercise the complete state renderer.
  h.run('drawCharts=()=>{};appState.pollCount=1');
  h.context.fetch=async()=>{throw new TypeError('Failed to fetch');};
  await h.run('refresh()');
  assert.equal(h.nodes.get('connection-error').hidden,false);
  h.context.fetch=async()=>({ok:true,json:async()=>response});
  await h.run('refresh()');
  assert.equal(h.nodes.get('connection-error').hidden,true);
  assert.equal(h.nodes.get('communication-status').textContent,'Conectat');
  assert.equal(h.nodes.get('reading-vdc').textContent,'565,7');
  assert.equal(h.nodes.get('controller-state').textContent,'Pregătit');
  assert.equal(h.nodes.get('start-command').disabled,false);
});

test('pending, rejection and timeout preserve actual controller state',()=>{
  for(const options of [{in_asteptare:true},{respins:true,motiv_respingere:2},{expirat:true}]){
    const h=ui(options);
    assert.equal(h.nodes.get('controller-state').textContent,'Pregătit');
    assert.equal(h.requests.length,0);
    assert.match(h.nodes.get('command-confirmation').textContent,/confirmarea|refuzată|neconfirmată/);
  }
});

test('historical alarms never claim to be currently active; unresolved alarms sort first',()=>{
  const h=ui();
  h.context.alarms=[
    {cod:'VDC_HIGH_HIGH',severitate:'ALARM',activare_s:1,revenire_s:3},
    {cod:'I_RMS_WARN',severitate:'WARN',activare_s:2,revenire_s:null},
    {cod:'I_RMS_HIGH',severitate:'ALARM',activare_s:4,revenire_s:null}
  ];
  const live=h.run('alarmRows(alarms,true)');
  assert.equal(live[0][0],'Activă');assert.equal(live[0][1],'Alarmă');
  assert.equal(live[2][0],'Încheiată');
  assert.ok(h.run('alarmRows(alarms,false)').every(row=>row[0]!=='Activă'));
});

test('recording metadata distinguishes closed, incomplete and unknown sessions',()=>{
  const h=ui();
  h.context.record={id:'old',puncte:[{t:10},{t:15}],metadate:{achizitie:'OPRIT'},randuri_invalide:0};
  assert.match(h.run('recordingDescription(record)'),/încheiată.*10,000–15,000/);
  h.context.record.randuri_invalide=1;
  assert.match(h.run('recordingDescription(record)'),/Date incomplete/);
  h.context.record.metadate={};
  assert.match(h.run('recordingDescription(record)'),/Închidere neconfirmată/);
});

test('polling leaves the session selector intact when unchanged or focused',()=>{
  const h=ui(),selector=h.nodes.get('recording-selector');
  let replaced=0;
  selector.replaceChildren=()=>replaced++;
  selector.add=()=>{};
  h.context.Option=function(label,value){this.label=label;this.value=value;};
  h.context.sessions=[{id:'psim_a'}];
  h.run("refreshSessionOptions(element('recording-selector'),sessions,'psim_a')");
  h.run("refreshSessionOptions(element('recording-selector'),sessions,'psim_a')");
  assert.equal(replaced,1);
  h.context.document.activeElement=selector;
  h.context.sessions.push({id:'psim_b'});
  h.run("refreshSessionOptions(element('recording-selector'),sessions,'psim_a')");
  assert.equal(replaced,1);
  h.context.document.activeElement=null;
  h.run("refreshSessionOptions(element('recording-selector'),sessions,'psim_a')");
  assert.equal(replaced,2);assert.equal(selector.value,'psim_a');
});

test('unchanged tables preserve their rows between polls',()=>{
  const h=ui(),table=h.nodes.get('event-table');
  let rebuilt=0;
  table.replaceChildren=()=>rebuilt++;
  table.insertRow=()=>({dataset:{},insertCell:()=>({textContent:''})});
  h.run("renderTable('event-table',[[1,'Stare','Oprit','—']],'Gol',4)");
  h.run("renderTable('event-table',[[1,'Stare','Oprit','—']],'Gol',4)");
  assert.equal(rebuilt,1);
});
