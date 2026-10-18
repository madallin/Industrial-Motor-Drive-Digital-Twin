'use strict';

// Logical read-only channel: this client never sends application messages.
class TelemetryTransport {
  constructor({url,onFrame,onUnavailable,onStatus,poll,Socket=globalThis.WebSocket,clock=()=>Date.now(),timers=globalThis}){
    Object.assign(this,{url,onFrame,onUnavailable,onStatus,poll,Socket,clock,timers});
    this.socket=null;this.retry=null;this.watch=null;this.stopped=true;this.lastFrame=0;this.delay=1000;this.polling=false;
  }
  start(){
    this.stopped=false;this.connect();
    this.watch=this.timers.setInterval(()=>this.check(),1000);
  }
  connect(){
    if(this.stopped)return;
    if(!this.Socket){this.onStatus('HTTP (rezervă)');return;}
    this.onStatus('Conectare WebSocket…');
    let socket;
    try{socket=new this.Socket(this.url());}catch{this.schedule();return;}
    this.socket=socket;this.openedAt=this.clock();
    socket.onmessage=event=>{
      if(this.stopped||this.socket!==socket)return;
      try{
        const frame=JSON.parse(event.data),age=this.clock()-frame.snapshot_epoch*1000;
        if(frame.schema!=='industrial-drive.stream.v1'||!frame.system||!Number.isFinite(age)||age< -1000||age>3000||frame.event_gap)throw Error('Invalid or expired snapshot');
        this.lastFrame=this.clock();this.delay=1000;this.onStatus('WebSocket conectat');this.onFrame(frame);
      }catch{this.fail(socket);}
    };
    socket.onclose=()=>{
      if(this.stopped||this.socket!==socket)return;
      this.socket=null;this.lastFrame=0;this.onUnavailable();this.onStatus('HTTP (rezervă)');this.fallback();this.schedule();
    };
    socket.onerror=()=>this.fail(socket);
  }
  fail(socket){
    if(this.socket!==socket||this.stopped)return;
    this.lastFrame=0;this.onUnavailable();socket.close();
  }
  schedule(){
    if(this.stopped||this.retry)return;
    const delay=this.delay;this.delay=Math.min(15000,this.delay*2);
    this.retry=this.timers.setTimeout(()=>{this.retry=null;this.connect();},delay);
  }
  async fallback(){
    if(this.polling||this.stopped)return;
    this.polling=true;
    try{await this.poll();}finally{this.polling=false;}
  }
  check(){
    if(this.stopped)return;
    if(this.socket&&this.clock()-(this.lastFrame||this.openedAt)>5000)this.fail(this.socket);
    if(!this.socket||!this.lastFrame)this.fallback();
  }
  stop(){
    this.stopped=true;this.timers.clearInterval(this.watch);this.timers.clearTimeout(this.retry);this.retry=null;
    if(this.socket)this.socket.close();this.socket=null;this.lastFrame=0;
  }
}
if(typeof module!=='undefined')module.exports={TelemetryTransport};
