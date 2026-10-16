'use strict';

// Keep the vertical scale stable until data exceeds it; reframing is explicit.
const fixedRanges={rpm:[0,1800],frecventa:[0,60],curent:[-40,40],rms:[0,20],vdc:[0,700]};

function stableScale(minimum,maximum,previousScale){
  if(previousScale&&minimum>=previousScale[0]&&maximum<=previousScale[1])return previousScale;
  const span=Math.max(maximum-minimum,Math.abs(maximum)*0.05,1);
  const bottom=Math.min(minimum-span*0.08,previousScale?.[0]??Infinity);
  const top=Math.max(maximum+span*0.08,previousScale?.[1]??-Infinity);
  const roughStep=(top-bottom)/4, magnitude=10**Math.floor(Math.log10(roughStep));
  const tickStep=([1,2,2.5,5,10].find(v=>v*magnitude>=roughStep)||10)*magnitude;
  return [minimum>=0?Math.max(0,Math.floor(bottom/tickStep)*tickStep):Math.floor(bottom/tickStep)*tickStep,Math.ceil(top/tickStep)*tickStep,tickStep];
}

function missingIntervals(events){
  return (events||[]).filter(e=>e.cod==='DATA_GAP'&&Number.isFinite(e.t)&&Number.isFinite(e.valoare)&&e.valoare>0)
    .map(e=>[e.t-e.valoare,e.t]);
}
function crossesGap(previous,current,gaps){
  return Number.isFinite(previous)&&gaps.some(([a,b])=>previous<b&&current>a&&current>previous);
}

function windowedPoints(points){
  if(!points?.length) return [];
  const start=points[points.length-1].t-selectedWindow();
  return points.filter(point=>point.t>=start);
}
function drawChart(elementId, points, series, unit, emptyId, message, options={}){
  const canvas=element(elementId);
  points=windowedPoints(points);
  const hasData=points.some(point=>series.some(seriesItem=>Number.isFinite(point[seriesItem.key])));
  canvas.hidden=!hasData;
  if(emptyId){element(emptyId).hidden=hasData;text(emptyId,message);}
  if(!hasData||!canvas.offsetWidth){element('chart-readout').hidden=true;canvas._cursor=null;canvas._index=null;canvas._signature=null;if(options.note)text(options.note,'');return;}
  const bounds=canvas.getBoundingClientRect(), pixelRatio=Math.min(2,window.devicePixelRatio||1);
  const width=bounds.width, height=bounds.height;
  const key=series[0].key, chartIdentity=[options.session,key,selectedWindow(),options.mode].join('|');
  if(canvas._identity!==chartIdentity){canvas._scale=null;canvas._identity=chartIdentity;canvas._cursor=null;canvas._index=null;element('chart-readout').hidden=true;}
  const gaps=missingIntervals(options.events);
  const signature=JSON.stringify([chartIdentity,width,height,pixelRatio,points.map(p=>[p.t,p[key]]),gaps]);
  if(canvas._signature===signature)return;
  canvas._signature=signature;
  canvas.width=Math.round(width*pixelRatio);canvas.height=Math.round(height*pixelRatio);
  const context=canvas.getContext('2d');context.setTransform(pixelRatio,0,0,pixelRatio,0,0);context.clearRect(0,0,width,height);
  const margins={left:64,right:18,top:22,bottom:32}, l=width-margins.left-margins.right, h=height-margins.top-margins.bottom;
  let minimum=Infinity,maximum=-Infinity;
  for(const point of points) for(const seriesItem of series){const value=point[seriesItem.key];if(Number.isFinite(value)){minimum=Math.min(minimum,value);maximum=Math.max(maximum,value);}}
  const scale=options.mode==='fix'?fixedRanges[key]:stableScale(minimum,maximum,canvas._scale);
  const outOfRange=minimum<scale[0]||maximum>scale[1];
  canvas._scale=scale;[minimum,maximum]=scale;
  if(options.note){text(options.note,outOfRange?'Valori în afara scării · alege Automată':`${options.mode==='fix'?'Fix':'Auto'}: ${formatNumber(minimum,Math.abs(maximum)<10?2:0)}…${formatNumber(maximum,Math.abs(maximum)<10?2:0)} ${unit}`);element(options.note).dataset.outOfRange=outOfRange;}
  canvas.setAttribute('aria-label',`${series[0].name}, ${unit}. Timp simulat, ${formatNumber(points[0].t,2)}–${formatNumber(points.at(-1).t,2)} secunde. Săgeți pentru cursor; Home și End pentru capete; Escape pentru închidere.`);
  const firstTime=points[0].t, latest=Math.max(firstTime+0.001,points[points.length-1].t);
  const x=timePoint=>margins.left+(timePoint-firstTime)/(latest-firstTime)*l;
  const y=value=>margins.top+h-(value-minimum)/(maximum-minimum)*h;
  context.font='12px "Segoe UI", Arial, sans-serif';context.strokeStyle='#e4e9ec';context.fillStyle='#596e7b';context.lineWidth=1;
  const tickStep=scale[2]||(maximum-minimum)/4,decimalPlaces=Math.max(0,Math.min(4,Math.ceil(-Math.log10(tickStep))+1));
  for(let value=minimum;value<=maximum+tickStep*0.001;value+=tickStep){
    const position=y(value);context.beginPath();context.moveTo(margins.left,position);context.lineTo(width-margins.right,position);context.stroke();context.textAlign='right';context.fillText(formatNumber(value,decimalPlaces),margins.left-10,position+4);
  }
  for(let index=0;index<=4;index++){
    const xPosition=margins.left+index*l/4;context.textAlign='center';context.fillText(`${formatNumber(firstTime+(latest-firstTime)*index/4,latest-firstTime<5?2:1)} s`,xPosition,height-9);
  }
  context.textAlign='left';context.fillText(unit,8,13);
  context.save();context.beginPath();context.rect(margins.left,margins.top,l,h);context.clip();
  for(const seriesItem of series){
    context.beginPath();context.strokeStyle=seriesItem.interrupted?'#7a74a3':'#008c95';context.lineWidth=1.6;context.setLineDash(seriesItem.interrupted?[6,4]:[]);
    let start=true, previous=null;
    for(const point of points){const value=point[seriesItem.key];if(!Number.isFinite(value)){start=true;continue;}if(start||crossesGap(previous,point.t,gaps)){context.moveTo(x(point.t),y(value));start=false;}else context.lineTo(x(point.t),y(value));previous=point.t;}
    context.stroke();
    if(points.length===1){context.beginPath();context.arc(x(points[0].t),y(points[0][seriesItem.key]),3,0,Math.PI*2);context.fillStyle='#006e76';context.fill();}
  }
  context.restore();
  const baseImage=context.getImageData(0,0,canvas.width,canvas.height), tooltip=element('chart-readout');
  const hideCursor=()=>{context.putImageData(baseImage,0,0);tooltip.hidden=true;canvas._cursor=null;canvas._index=null;};
  const trackPoint=(index)=>{
    context.putImageData(baseImage,0,0);
    const point=points[index], px=x(point.t);
    context.save();context.strokeStyle='#8498a2';context.lineWidth=1;context.setLineDash([3,3]);
    context.beginPath();context.moveTo(px,margins.top);context.lineTo(px,margins.top+h);context.stroke();context.setLineDash([]);
    for(const seriesItem of series){
      if(!Number.isFinite(point[seriesItem.key])||point[seriesItem.key]<minimum||point[seriesItem.key]>maximum)continue;
      context.beginPath();context.arc(px,y(point[seriesItem.key]),4,0,Math.PI*2);
      context.fillStyle='#008c95';context.fill();context.strokeStyle='#fff';context.lineWidth=2;context.stroke();
    }
    context.restore();
    text('chart-readout',`${formatNumber(point.t,3)} s\n${series.map(seriesItem=>`${seriesItem.name}: ${formatNumber(point[seriesItem.key],2)} ${unit}`).join('\n')}`);
    tooltip.hidden=false;
    const rect=canvas.getBoundingClientRect();
    const anchorY=y(point[series[0].key]);
    tooltip.style.left=Math.max(8,Math.min(rect.left+px+14,window.innerWidth-tooltip.offsetWidth-8))+'px';
    tooltip.style.top=Math.max(8,Math.min(rect.top+(Number.isFinite(anchorY)?anchorY:margins.top)+14,window.innerHeight-tooltip.offsetHeight-8))+'px';
    canvas._index=index;
  };
  const onCursor=event=>{
    const rect=canvas.getBoundingClientRect(), dx=event.clientX-rect.left, dy=event.clientY-rect.top;
    if(dx<margins.left||dx>width-margins.right||dy<margins.top||dy>height-margins.bottom){hideCursor();return;}
    canvas._cursor={clientX:event.clientX,clientY:event.clientY};
    const timePoint=firstTime+(dx-margins.left)/l*(latest-firstTime);
    if(gaps.some(([a,b])=>timePoint>a&&timePoint<b)){hideCursor();return;}
    let index=0;
    for(let i=1;i<points.length;i++)if(Math.abs(points[i].t-timePoint)<Math.abs(points[index].t-timePoint))index=i;
    trackPoint(index);
  };
  canvas.onpointermove=onCursor;canvas.onpointerdown=onCursor;canvas.onpointerleave=hideCursor;canvas.onblur=hideCursor;
  canvas.onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Escape'){hideCursor();return;}
    canvas._cursor=null;
    const index=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,(canvas._index??0)+(event.key==='ArrowRight'?1:-1)));
    trackPoint(index);
  };
  if(canvas._cursor)onCursor(canvas._cursor);
  else if(document.activeElement===canvas&&Number.isInteger(canvas._index))trackPoint(Math.min(canvas._index,points.length-1));
}
