'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {TelemetryTransport}=require('../dashboard/transport.js');

function fixture(){
  const calls={poll:0,unavailable:0,frames:[],statuses:[],timeouts:[]};let now=100000;
  class Socket{
    static instances=[];
    constructor(){Socket.instances.push(this);}
    close(){this.onclose?.();}
  }
  const timers={setInterval:()=>1,clearInterval(){},setTimeout:(callback,delay)=>{calls.timeouts.push({callback,delay});return calls.timeouts.length;},clearTimeout(){}};
  const transport=new TelemetryTransport({url:()=> 'ws://localhost/api/stream',Socket,timers,clock:()=>now,
    onFrame:frame=>calls.frames.push(frame),onUnavailable:()=>calls.unavailable++,onStatus:value=>calls.statuses.push(value),poll:async()=>calls.poll++});
  return {transport,calls,Socket,advance:delta=>now+=delta,frame:extra=>({schema:'industrial-drive.stream.v1',snapshot_epoch:now/1000,system:{},events:[],...extra})};
}

test('WebSocket frames suppress continuous HTTP polling and never send commands',()=>{
  const h=fixture();h.transport.start();
  const socket=h.Socket.instances[0];socket.onmessage({data:JSON.stringify(h.frame())});
  h.transport.check();assert.equal(h.calls.poll,0);assert.equal(h.calls.frames.length,1);
  assert.equal(typeof socket.send,'undefined');h.transport.stop();
});
test('stalled sockets withdraw readings, use HTTP fallback, and reconnect with backoff',async()=>{
  const h=fixture();h.transport.start();
  h.advance(6000);h.transport.check();
  assert.ok(h.calls.unavailable>0);assert.equal(h.calls.timeouts[0].delay,1000);
  await Promise.resolve();assert.ok(h.calls.poll>0);
  h.calls.timeouts[0].callback();h.Socket.instances[1].close();
  assert.equal(h.calls.timeouts[1].delay,2000);h.transport.stop();
});
test('stale, malformed, and event-gap frames are never treated as current',()=>{
  for(const kind of ['stale','malformed','gap']){
    const h=fixture();h.transport.start();const socket=h.Socket.instances[0];
    socket.onmessage({data:kind==='malformed'?'{':JSON.stringify(h.frame(kind==='stale'?{snapshot_epoch:1}:{event_gap:true}))});
    assert.equal(h.calls.frames.length,0);assert.ok(h.calls.unavailable>0);h.transport.stop();
  }
});
test('absence of WebSocket leaves HTTP monitoring functional',async()=>{
  const h=fixture();h.transport.Socket=null;h.transport.start();h.transport.check();
  await Promise.resolve();assert.equal(h.calls.poll,1);h.transport.stop();
});
