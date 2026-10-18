'use strict';
const element=id=>document.getElementById(id);
const text=(id,value)=>{const node=element(id);if(node.textContent!==String(value))node.textContent=value;};
const formatNumber=(value,decimals=1)=>Number.isFinite(value)?(Math.abs(value)<0.5*10**(-decimals)?0:value).toLocaleString('ro-RO',{minimumFractionDigits:decimals,maximumFractionDigits:decimals}):'—';
const selectedWindow=()=>Number(element('time-window').value);
const units={rpm:'RPM',frecventa:'Hz',curent:'A',rms:'A',vdc:'V'};
const pageTitles={operation:'Operare motor',diagnostic:'Diagnostic',recordings:'Înregistrări'};
const processStates={INIT:'Inițializare',PRECHARGE:'Preîncărcare',READY:'Pregătit',STOP:'Oprit',NOT_READY:'Nepregătit',RUNNING:'În funcționare',ACCELERATING:'Accelerare',WARNING:'Avertizare',ALARM:'Alarmă'};
const driveStates={PRECHARGE:'Preîncărcare',READY:'Pregătit',STARTING:'Accelerare',RUNNING:'În funcțiune',STOPPING:'Decelerare',COASTING:'Rotire prin inerție',STOPPED:'Oprit',FAULT:'Protecție declanșată'};
const driveFaults=['','Supracurent','Subtensiune','Supratensiune','Supraturație','Comunicație întreruptă','Măsurători invalide','Oprire nefinalizată','Preîncărcare nefinalizată','Suprasarcină termică','Rotor blocat','Accelerare nereușită'];
const rejectionReasons=['','Referință invalidă','DC-link nepregatit','Defect memorat','Rotorul încă se rotește','Oprire în curs','Condiții de reset neîndeplinite'];
const conditions={MQTT_EVENT_GAP:'Notificări incomplete; consultă înregistrările',EVENT_JOURNAL_GAP:'Evenimente incomplete; consultă înregistrările',MQTT_CONNECTED:'Conexiune MQTT restabilită',MQTT_DISCONNECTED:'Legătura cu brokerul întreruptă',MQTT_PUBLISHER_OFFLINE:'Publicare telemetrie oprită',COMMUNICATION_LOST:'Măsurători întrerupte',ACQUISITION_ACTIV:'Achiziție măsurători activă',ACQUISITION_ASTEPTARE:'Așteptare măsurători',ACQUISITION_INDISPONIBIL:'Achiziție indisponibilă',ACQUISITION_OPRIT:'Achiziție oprită',DATA_GAP:'Întrerupere eșantionare',PRECHARGE_RESET:'Preîncărcare reluată',PRECHARGE_READY:'Preîncărcare finalizată',START_BEFORE_READY:'Pornire înainte de preîncărcare',I_RMS_WARN:'Curent RMS ridicat',I_RMS_HIGH:'Curent RMS peste limită',VDC_LOW_WARN:'Tensiune DC-link scăzută',VDC_LOW_HIGH:'Subtensiune DC-link',VDC_HIGH_WARN:'Tensiune DC-link ridicată',VDC_HIGH_HIGH:'Supratensiune DC-link',SPEED_WARN:'Abatere de turație',SPEED_HIGH:'Abatere mare de turație'};
const severityLabels={INFO:'Informare',STATE:'Stare',WARN:'Avertizare',ALARM:'Alarmă',CLEARED:'Revenire'};
const conditionLabel=code=>code?.startsWith('DRIVE_')?(driveStates[code.slice(6)]||code):code==='CMD_ACCEPTED'?'Comandă acceptată':code?.startsWith('CMD_REJECT_')?'Comandă respinsă':code?.startsWith('TO_')?(processStates[code.slice(3)]||code):(conditions[code]||code);
const eventValue=(code,value)=>{
  if(!Number.isFinite(value))return '—';
  const unit=code?.startsWith('I_RMS')?' A':code?.startsWith('VDC')||code?.startsWith('PRECHARGE_')||code==='START_BEFORE_READY'?' V':code?.startsWith('SPEED')?' %':code==='DATA_GAP'?' s':'';
  return formatNumber(value,code==='DATA_GAP'?3:2)+unit;
};
let telemetryTransport=null;
const appState={streamEvents:[],streamInstance:null,page:'operation',system:null,history:null,busy:false,pollCount:0,commandBusy:false,commandError:false};
async function fetchJson(url){
  const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(6000)});
  const data=await response.json();
  if(!response.ok) throw Error(data.mesaj||'Date indisponibile.');
  return data;
}
function renderTable(id,rows,empty,columns){
  const body=element(id),signature=JSON.stringify([rows,empty]);
  if(body.dataset.signature===signature)return;
  body.dataset.signature=signature;body.replaceChildren();
  if(!rows.length){const row=body.insertRow(),cell=row.insertCell();cell.colSpan=columns;cell.textContent=empty;return;}
  for(const values of rows){const row=body.insertRow();for(const value of values) row.insertCell().textContent=value??'—';
    if(id==='alarm-table')row.dataset.tone=values[0]==='Activă'?(values[1]==='Alarmă'?'alarm':'warning'):'resolved';
  }
}
function alarmRows(alarms,live){
  const rank=a=>(a.revenire_s==null?0:10)+(a.severitate==='ALARM'?0:1);
  return [...alarms].sort((a,b)=>rank(a)-rank(b)||(b.activare_s||0)-(a.activare_s||0)).map(a=>[
    a.revenire_s!=null?'Încheiată':live?'Activă':'La finalul înregistrării',
    severityLabels[a.severitate]||a.severitate,conditionLabel(a.cod),
    formatNumber(a.activare_s,3),formatNumber(a.revenire_s,3),eventValue(a.cod,a.valoare)
  ]);
}
function eventRows(events){
  return events.slice(-50).reverse().map(a=>[formatNumber(a.t,3),severityLabels[a.nivel]||a.nivel,
    a.cod?.startsWith('DRIVE_')?`Controler · ${conditionLabel(a.cod)}`:a.cod?.startsWith('TO_')?`Monitorizare · ${conditionLabel(a.cod)}`:conditionLabel(a.cod),
    a.cod==='DRIVE_FAULT'?(driveFaults[a.valoare]||formatNumber(a.valoare,0)):a.nivel==='STATE'||a.cod?.startsWith('CMD_')?'—':eventValue(a.cod,a.valoare)]);
}
function renderDiagnostics(data,control,live){
  const active=live?(data.alarme||[]).filter(a=>a.revenire_s==null):[];
  const fault=control.disponibil&&control.aplicat?.fault;
  const alarms=active.filter(a=>a.severitate==='ALARM').length,warnings=active.length-alarms;
  text('communication-status',live?(control.disponibil?'Conectat':'Control indisponibil'):'Fără măsurători');
  text('alarm-summary',fault?(driveFaults[fault]||'Defect activ'):!live?'Diagnostic indisponibil':active.length?`${alarms} alarme · ${warnings} avertizări`:'Fără alarme');
  element('alarm-summary').dataset.tone=fault||alarms?'alarm':warnings?'warning':'neutral';
  text('diagnostic-start',element('start-command').disabled?'Indisponibilă':'Permisă');
  text('diagnostic-communication',live?'Măsurători actuale':data.puncte?.length?'Date istorice; achiziție inactivă':'Așteptare măsurători');
  text('diagnostic-controller',control.disponibil?driveStates[control.aplicat?.drive_state]||'Stare necunoscută':'Fără feedback actual');
  text('diagnostic-reason',element('control-reason').textContent);
  for(const [id,key,unit] of [['synchronous-speed-calculation','sincron','rpm'],['measured-speed-calculation','rpm','rpm'],['speed-error-calculation','abatere_pct','%']]){
    text(id,live&&Number.isFinite(data.ultim?.[key])?`${formatNumber(data.ultim[key],key==='abatere_pct'?1:0)} ${unit}`:'—');
  }
}
function refreshSessionOptions(selection,sessions,previous){
  const signature=sessions.map(s=>s.id).join('|');
  // Preserve focus and selection while the session list is unchanged or open.
  if(selection.dataset.signature===signature||document.activeElement===selection)return;
  selection.dataset.signature=signature;selection.replaceChildren();
  for(const session of sessions)selection.add(new Option(sessionLabel(session),session.id));
  if(sessions.some(s=>s.id===previous))selection.value=previous;
  if(!sessions.length)selection.add(new Option('Nu există înregistrări',''));
}
function recordingDescription(data){
  if(!data)return 'Nu există înregistrări.';
  const first=data.puncte?.[0]?.t,last=data.puncte?.at(-1)?.t;
  const current=appState.system?.psim.achizitie==='ACTIV'&&appState.system.psim.id===data.id;
  const closed=['OPRIT','INREGISTRARE'].includes(data.metadate?.achizitie);
  const sessionState=current?'În curs':closed?'Înregistrare încheiată':'Închidere neconfirmată';
  return `${sessionState} · ${formatNumber(first,3)}–${formatNumber(last,3)} s${data.randuri_invalide?' · Date incomplete: rânduri invalide excluse':''}`;
}
function navigate(page){
  appState.page=page;
  element('time-window').closest('label').hidden=page==='diagnostic';
  element('live-timestamp').hidden=page!=='operation';
  for(const button of document.querySelectorAll('nav button')){
    const active=button.dataset.page===page;button.classList.toggle('selected',active);
    if(active) button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  for(const section of document.querySelectorAll('.page')) section.hidden=section.id!==`page-${page}`;
  text('page-title',pageTitles[page]);element('chart-readout').hidden=true;refresh();drawCharts();
}
function render(){
  const system=appState.system,data=system.psim,latest=data.ultim,reception=system.receptie;
  const live=data.achizitie==='ACTIV'&&Boolean(latest);
  text('live-timestamp',live?`Timp simulat ${formatNumber(latest.t,2)} s`:'');
  for(const key of ['rpm','frecventa','curent','rms','vdc']) text('reading-'+key,formatNumber(latest?.[key],key==='rpm'?0:key==='curent'||key==='rms'?2:1));
  if(reception.eroare){element('connection-error').hidden=false;text('connection-error','Achiziție indisponibilă. Verifică simularea și repornește aplicația.');}
  renderControls();
  if(typeof renderIntegrations==='function')renderIntegrations(system.iiot,system.mqtt);
  const alarms=[...(data.istoric_alarme||[])];
  for(const alarm of data.alarme||[]){
    if(!alarms.some(a=>a.cod===alarm.cod&&a.revenire_s==null))alarms.push(alarm);
  }
  const control=system.control.psim;
  renderDiagnostics(data,control,live);
  text('process-state',control.disponibil?(control.aplicat?.fault?driveFaults[control.aplicat.fault]:(driveStates[control.aplicat?.drive_state]||'Stare necunoscută')):'Fără stare curentă');
  text('alarm-note',live?'Monitorizare curentă':data.puncte?.length?'Ultima înregistrare · stare istorică':'Fără măsurători curente');
  renderTable('alarm-table',alarmRows(alarms,live),'Nicio alarmă sau avertizare înregistrată.',6);
  renderTable('event-table',eventRows(telemetryTransport?.lastFrame&&appState.streamEvents.length?appState.streamEvents.filter(event=>event.session_id==null||event.session_id===data.id||event.session_id?.startsWith(data.metadate?.session_id+'_part')).map(event=>({t:event.sim_time_s,nivel:event.level||event.severity,cod:event.code,valoare:event.value})):data.evenimente||[]),'Niciun eveniment.',4);
  text('chart-axis-context','Timp simulat [s]');
  text('chart-context',data.puncte?.length&&!live?'Ultima înregistrare':'');
  element('chart-context').dataset.recorded=Boolean(data.puncte?.length&&!live);
  drawCharts();
}
function renderControls(){
  if(!appState.system)return;
  const control=appState.system.control.psim,applied=control.aplicat,limits=appState.system.control.limite;
  element('frequency-input').max=limits.frecventa_max_hz;
  element('load-input').max=limits.sarcina_max_nm;
  text('frequency-limit',`0–${formatNumber(limits.frecventa_max_hz,0)} Hz`);
  text('load-limit',`0–${formatNumber(limits.sarcina_max_nm,0)} Nm`);
  const blocked=!control.disponibil||control.in_asteptare||appState.commandBusy;
  for(const id of ['frequency-input','load-input','acceleration-input','deceleration-input'])element(id).disabled=control.in_asteptare||appState.commandBusy;
  for(const id of ['apply-references','start-command'])element(id).disabled=blocked;
  element('stop-command').disabled=!control.disponibil||appState.commandBusy||(!applied?.pornit&&!control.in_asteptare);
  element('start-command').disabled=blocked||Boolean(applied?.fault)||!['READY','STOPPED'].includes(applied?.drive_state)||Boolean(applied?.pornit);
  element('apply-references').disabled=blocked||Boolean(applied?.fault)||['STOPPING','COASTING'].includes(applied?.drive_state);
  element('reset-command').hidden=!applied?.fault;
  element('reset-command').disabled=blocked||!applied?.fault;
  element('drive-status').dataset.state=control.disponibil?applied?.drive_state:'offline';
  text('controller-state',control.disponibil?(driveStates[applied?.drive_state]||'Stare necunoscută'):'Indisponibil');
  const reason=!control.disponibil?operatorReason(control.motiv):applied?.fault?`${driveFaults[applied.fault]||'Defect necunoscut'}. Elimină cauza înainte de reset.`:applied?.drive_state==='PRECHARGE'?'Se încarcă magistrala DC.':['COASTING','STOPPING'].includes(applied?.drive_state)?'START disponibil după oprirea rotorului.':'';
  text('control-reason',reason);element('control-reason').hidden=!reason;
  element('control-reason').dataset.fault=Boolean(control.disponibil&&applied?.fault);
  const confirmation=!control.disponibil?'':
    appState.commandBusy?'Se trimite solicitarea…':
    control.in_asteptare?'Se așteaptă confirmarea comenzii…':
    control.respins?`Comandă refuzată: ${rejectionReasons[control.motiv_respingere]||'condiții neîndeplinite'}.`:
    control.expirat?'Comandă neconfirmată. Verifică starea motorului.':
    control.confirmat?`Acceptată · ${formatNumber(applied?.frecventa_hz)} Hz · ${formatNumber(applied?.sarcina_nm)} Nm\nRampe ${formatNumber(applied?.acceleration_s)} / ${formatNumber(applied?.deceleration_s)} s`:'';
  text('command-confirmation',confirmation);
  element('command-confirmation').hidden=!confirmation;
  element('command-confirmation').dataset.tone=control.respins||control.expirat?'error':control.in_asteptare?'pending':'';
  const changed=[['frequency-input','frecventa_hz'],['load-input','sarcina_nm'],['acceleration-input','acceleration_s'],['deceleration-input','deceleration_s']].some(([id,key])=>Number(element(id).value)!==applied?.[key]);
  element('draft-status').hidden=!control.disponibil||!changed||control.in_asteptare||appState.commandBusy;
  if(!changed)element('apply-references').disabled=true;
  if(control.disponibil&&!control.in_asteptare&&!control.expirat&&!control.respins&&!appState.commandBusy&&!appState.commandError)element('command-message').hidden=true;
}
function operatorReason(reason){
  if(reason?.includes('GNU Octave'))return 'Achiziția nu răspunde. Repornește aplicația.';
  if(reason?.includes('backend'))return 'Conexiune întreruptă. Repornește aplicația.';
  if(reason?.includes('configuratia DLL'))return 'Controlul nu este configurat. Verifică setările blocului de comandă.';
  if(reason?.includes('masuratorile PSIM'))return 'Măsurători întârziate. Verifică rularea simulării.';
  if(reason?.includes('activati numai'))return 'Control dezactivat în configurație.';
  if(reason?.includes('DLL/PSIM'))return 'Pornește simularea în PSIM pentru a activa comenzile.';
  return reason||'Așteptare conexiune.';
}
function refreshReferenceSummary(){
  const value=id=>element(id).value===''?'—':formatNumber(Number(element(id).value),1).replace(/,0$/,'');
  text('ramp-summary',`${value('acceleration-input')} s / ${value('deceleration-input')} s`);
  renderControls();
}
async function sendCommand(action){
  if(appState.commandBusy)return;
  const body={tinta:'psim',actiune:action};
  if(['referinte','porneste'].includes(action)){
    element('frequency-input').setCustomValidity('');
    if(['acceleration-input','deceleration-input'].some(id=>!element(id).checkValidity()))element('ramp-settings').open=true;
    if(!element('control-form').reportValidity())return;
    body.frecventa_hz=Number(element('frequency-input').value);body.sarcina_nm=Number(element('load-input').value);
    body.acceleration_s=Number(element('acceleration-input').value);body.deceleration_s=Number(element('deceleration-input').value);
    if(action==='porneste'&&body.frecventa_hz<=0){
      element('frequency-input').setCustomValidity('Introdu o frecvență mai mare de 0 Hz pentru START.');
      element('frequency-input').reportValidity();return;
    }
  }
  appState.commandError=false;appState.commandBusy=true;renderControls();
  element('command-message').hidden=true;
  try{
    const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(6000)});
    const data=await response.json();if(!response.ok)throw Error(data.mesaj);
  }catch(error){appState.commandError=true;element('command-message').hidden=false;text('command-message',error.name==='TypeError'||error.name==='TimeoutError'?'Comandă neconfirmată. Verifică starea motorului.':operatorReason(error.message));}
  finally{appState.commandBusy=false;refresh();}
}
function saveDraft(){
  try{localStorage.setItem('referinte-motor',JSON.stringify({frecventa:element('frequency-input').value,sarcina:element('load-input').value,acceleration:element('acceleration-input').value,deceleration:element('deceleration-input').value}));}catch{}
  refreshReferenceSummary();
}
function restoreDraft(){
  try{
    const draft=JSON.parse(localStorage.getItem('referinte-motor'));
    if(draft&&typeof draft.frecventa==='string'&&typeof draft.sarcina==='string'){
      element('frequency-input').value=draft.frecventa;element('load-input').value=draft.sarcina;
      if(draft.acceleration)element('acceleration-input').value=draft.acceleration;
      if(draft.deceleration)element('deceleration-input').value=draft.deceleration;
    }
  }catch{}
}
function sessionLabel(session){
  const match=session.id.match(/^psim_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_.*_part(\d+)$/);
  return match?`${match[3]}.${match[2]}.${match[1]} · ${match[4]}:${match[5]}:${match[6]} · Segment ${Number(match[7])}`:session.id;
}
async function refresh(){
  if(appState.busy)return;appState.busy=true;
  try{
    const system=await fetchJson('/api/stare?fereastra='+selectedWindow());
    appState.system=system;element('connection-error').hidden=true;render();
    // An archive request failure does not invalidate current drive control.
    try{
      if(appState.pollCount++%7===0){
        const sessions=(await fetchJson('/api/sesiuni')).sesiuni,selection=element('recording-selector'),previous=selection.value;
        refreshSessionOptions(selection,sessions,previous);
      }
      if(appState.page==='recordings')await fetchHistory();
    }catch{
      if(appState.page==='recordings'){
        appState.history=null;element('recordings-empty').hidden=false;element('recording-content').hidden=true;
        text('recordings-empty','Înregistrarea nu poate fi citită. Reîncercare automată…');
      }
    }
  }catch(error){
    console.error('HMI refresh failed',error);
    text('connection-error','Conexiune întreruptă. Verifică dacă aplicația rulează.');element('connection-error').hidden=false;
    invalidateLive();
  }finally{appState.busy=false;}
}

function invalidateLive(){
    if(typeof invalidateIntegrations==='function')invalidateIntegrations();
    // Remove stale readings and disable controls when the HTTP connection fails.
    for(const key of ['rpm','frecventa','curent','rms','vdc'])text('reading-'+key,'—');
    for(const id of ['frequency-input','load-input','acceleration-input','deceleration-input','apply-references','start-command','stop-command','reset-command'])element(id).disabled=true;
    text('controller-state','Indisponibil');element('drive-status').dataset.state='offline';
    text('control-reason','Reconectare la aplicație…');element('control-reason').hidden=false;element('control-reason').dataset.fault=false;
    text('communication-status','Conexiune întreruptă');
    text('alarm-summary','Diagnostic indisponibil');element('alarm-summary').dataset.tone='neutral';
    text('diagnostic-communication','Conexiune întreruptă');text('diagnostic-controller','Fără feedback actual');text('diagnostic-start','Indisponibilă');text('diagnostic-reason','Reconectare la aplicație…');text('process-state','Fără stare curentă');
    for(const id of ['synchronous-speed-calculation','measured-speed-calculation','speed-error-calculation'])text(id,'—');
    text('live-timestamp','');text('chart-context',appState.system?.psim.puncte?.length?'Ultima înregistrare':'');element('chart-context').dataset.recorded=true;
    element('command-confirmation').hidden=true;element('draft-status').hidden=true;
    if(appState.system){appState.system.control.psim.disponibil=false;appState.system.control.psim.motiv='Conexiune întreruptă.';appState.system.psim.ultim=null;appState.system.psim.achizitie='INDISPONIBIL';
      text('alarm-note','Conexiune întreruptă · stare istorică');
      renderTable('alarm-table',alarmRows(appState.system.psim.istoric_alarme||[],false),'Starea alarmelor curente nu este disponibilă.',6);
    }
}
function startTelemetry(){
  if(typeof TelemetryTransport!=='function'){setInterval(refresh,1000);return;}
  telemetryTransport=new TelemetryTransport({
    url:()=>`ws://${location.host}/api/stream?fereastra=${selectedWindow()}`,
    onFrame:frame=>{
      if(frame.instance_id!==appState.streamInstance){appState.streamEvents=[];appState.streamInstance=frame.instance_id;}
      for(const event of frame.events||[]){
        if(event.source==='psim'&&!appState.streamEvents.some(previous=>previous.id===event.id))appState.streamEvents.push(event);
      }
      appState.streamEvents=appState.streamEvents.slice(-200);
      appState.system=frame.system;element('connection-error').hidden=true;render();
    },
    onUnavailable:invalidateLive,onStatus:value=>text('transport-status',value),poll:refresh
  });
  telemetryTransport.start();
}

async function fetchHistory(){
  const selection=element('recording-selector').value;
  const data=selection?await fetchJson('/api/inregistrare?sesiune='+encodeURIComponent(selection)+'&fereastra='+selectedWindow()):null;
  // Ignore a response if the selected session changed during the request.
  if(selection!==element('recording-selector').value)return;
  appState.history=data;
  element('recordings-empty').hidden=Boolean(data);
  element('recording-content').hidden=!data;
  text('recording-metadata',recordingDescription(data));
  renderTable('recording-events',eventRows(data?.jurnal_evenimente||[]),'Niciun eveniment înregistrat.',4);
  for(const [id,tip] of [['export-samples','samples'],['export-events','events']]){
    const link=element(id),active=Boolean(data&&(tip==='samples'||data.are_evenimente));
    link.setAttribute('aria-disabled',String(!active));
    if(active)link.href='/api/export?sesiune='+encodeURIComponent(selection)+'&tip='+tip;else link.removeAttribute('href');
  }
  renderTable('recording-table',(data?.esantioane_recente||[]).slice().reverse().map(p=>[formatNumber(p.t,6),formatNumber(p.rpm,6),formatNumber(p.curent,6),formatNumber(p.rms,6),formatNumber(p.vdc,6),formatNumber(p.frecventa,6)]),'Niciun eșantion.',6);
  drawCharts();
}
async function refreshRecordings(){
  try{
    const sessions=(await fetchJson('/api/sesiuni')).sesiuni,selection=element('recording-selector');
    refreshSessionOptions(selection,sessions,selection.value);
    await fetchHistory();
  }catch{text('recording-metadata','Înregistrările nu pot fi citite. Reîncercare automată…');}
}
function drawCharts(){
  if(appState.page==='operation'){
    const key=element('signal-selector').value;
    drawChart('live-chart',appState.system?.psim.puncte||[],[{key,name:element('signal-selector').selectedOptions[0].textContent}],units[key],'empty-live-chart','Pornește simularea în PSIM pentru a vedea măsurătorile.',{session:appState.system?.psim.metadate?.session_id||appState.system?.psim.id,mode:element('live-scale').value,note:'live-scale-note',events:appState.system?.psim.jurnal_evenimente||appState.system?.psim.evenimente});
  }
  if(appState.page==='recordings'){
    const key=element('recording-signal-selector').value;
    drawChart('recording-chart',appState.history?.puncte||[],[{key,name:element('recording-signal-selector').selectedOptions[0].textContent}],units[key],'empty-recording-chart','Niciun eșantion disponibil.',{session:appState.history?.id,mode:element('recording-scale').value,note:'recording-scale-note',events:appState.history?.jurnal_evenimente});
  }
}
document.addEventListener('DOMContentLoaded',()=>{
  for(const button of document.querySelectorAll('nav button'))button.addEventListener('click',()=>navigate(button.dataset.page));
  element('control-form').addEventListener('submit',event=>{event.preventDefault();sendCommand('referinte');});
  element('frequency-input').addEventListener('input',()=>{element('frequency-input').setCustomValidity('');saveDraft();});
  element('load-input').addEventListener('input',saveDraft);
  for(const id of ['acceleration-input','deceleration-input'])element(id).addEventListener('input',saveDraft);
  element('reset-command').addEventListener('click',()=>sendCommand('reset'));
  element('start-command').addEventListener('click',()=>sendCommand('porneste'));
  element('stop-command').addEventListener('click',()=>sendCommand('opreste'));
  element('time-window').addEventListener('change',()=>{if(telemetryTransport){telemetryTransport.stop();startTelemetry();}refresh();});
  element('signal-selector').addEventListener('change',drawCharts);
  element('recording-signal-selector').addEventListener('change',drawCharts);
  element('recording-selector').addEventListener('change',refresh);
  element('alarm-summary').addEventListener('click',()=>navigate('diagnostic'));
  for(const [scaleId,reframeId,chartId] of [['live-scale','reframe-live-chart','live-chart'],['recording-scale','reframe-recording-chart','recording-chart']]){
    element(scaleId).addEventListener('change',drawCharts);
    element(reframeId).addEventListener('click',()=>{element(chartId)._scale=null;element(chartId)._signature=null;drawCharts();});
  }
  window.addEventListener('resize',drawCharts);
  restoreDraft();refreshReferenceSummary();refresh();startTelemetry();
  element('historian-details').addEventListener('toggle',()=>{if(element('historian-details').open)loadHistorianSessions();});
  element('query-historian').addEventListener('click',queryHistorian);
  setInterval(()=>{if(appState.page==='recordings')refreshRecordings();},10000);
  window.addEventListener('beforeunload',()=>telemetryTransport?.stop());
});
