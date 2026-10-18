'use strict';

function invalidateIntegrations(){
  text('mqtt-status','Fără conexiune cu aplicația');
  text('historian-status','Fără conexiune cu aplicația');
}

function renderIntegrations(integrations={},mqtt={}){
  const consumer=integrations.mqtt_consumer||{};
  text('mqtt-status',!mqtt.activ?'Dezactivat':mqtt.conectat&&(!consumer.enabled||consumer.connected)?'Conectat':mqtt.conectat?'Notificări indisponibile':'Deconectat');
  const history=integrations.historian||{};
  text('historian-status',!history.enabled?'Dezactivat':history.available?'Disponibil':'Indisponibil; CSV disponibil');
  const events=integrations.notifications||[],body=element('notification-table'),signature=JSON.stringify(events);
  if(body.dataset.signature===signature)return;
  body.dataset.signature=signature;body.replaceChildren();
  if(!events.length){const cell=body.insertRow().insertCell();cell.colSpan=5;cell.textContent='Nicio notificare.';return;}
  for(const event of events.slice().reverse()){
    const row=body.insertRow();
    for(const value of [new Date(event.observed_epoch*1000).toLocaleTimeString('ro-RO'),severityLabels[event.severity]||event.severity,event.source==='psim'?'Motor':event.source==='mqtt'?'Comunicații':event.source,conditionLabel(event.code)])row.insertCell().textContent=value;
    const cell=row.insertCell();
    if(event.acknowledged_epoch)cell.textContent='Luat la cunoștință';
    else{
      const button=document.createElement('button');button.textContent='Ia la cunoștință';
      button.addEventListener('click',async()=>{
        button.disabled=true;
        try{
          const response=await fetch('/api/notifications/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:event.id}),signal:AbortSignal.timeout(3000)});
          if(!response.ok)throw Error();cell.textContent='Luat la cunoștință';
        }catch{button.disabled=false;button.textContent='Reîncearcă';}
      });cell.append(button);
    }
  }
}

async function loadHistorianSessions(){
  try{
    const data=await fetchJson('/api/historian/sessions');
    for(const [id,optional] of [['historian-session',false],['historian-comparison',true]]){
      const select=element(id),previous=select.value;select.replaceChildren();
      if(optional)select.add(new Option('Fără comparație',''));
      for(const session of data.sessions)select.add(new Option(sessionLabel({id:session.id}),session.id));
      if(data.sessions.some(session=>session.id===previous))select.value=previous;
    }
    text('historian-query-status',data.sessions.length?'':'Nu există înregistrări de motor în istoric.');
  }catch{text('historian-query-status','Istoricul structurat nu este disponibil. Înregistrările CSV rămân accesibile.');}
}

async function queryHistorian(){
  const session=element('historian-session').value,comparison=element('historian-comparison').value;
  const start=Number(element('historian-start').value),end=element('historian-end').value===''?1e12:Number(element('historian-end').value);
  if(!session||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<start){text('historian-query-status','Selectează o sesiune și un interval valid.');return;}
  const button=element('query-historian');button.disabled=true;
  try{
    const query=id=>fetchJson(`/api/historian/query?session=${encodeURIComponent(id)}&start=${start}&end=${end}&limit=1`);
    const [a,b]=await Promise.all([query(session),comparison?query(comparison):null]);
    const describe=value=>value?`${formatNumber(value.average,2)} / ${formatNumber(value.minimum,2)} / ${formatNumber(value.maximum,2)}`:'—';
    renderTable('historian-table',[['rpm','Turație [rpm]'],['rms','RMS estimat [A]'],['vdc','DC-link [V]'],['frecventa','Frecvență [Hz]']].map(([key,label])=>[label,describe(a.statistics[key]),describe(b?.statistics[key])]),'Fără măsurători.',3);
    text('historian-query-status',`${a.sample_count} eșantioane indexate${b?` · Comparație: ${b.sample_count} eșantioane`:''}. Interval în timp simulat.`);
  }catch{text('historian-query-status','Interogarea nu a reușit. Reîncearcă sau consultă CSV-ul.');}
  finally{button.disabled=false;}
}
