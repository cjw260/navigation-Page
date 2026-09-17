import test from 'node:test';
import assert from 'node:assert/strict';
import { initProjectPreviews } from '../assets/project-previews.mjs';
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture(t, { touch=false, reduced=false, saveData=false } = {}) {
  t.mock.timers.enable({ apis:['setTimeout'] });
  const events = () => new EventTarget();
  const media = query => Object.assign(events(), {matches:query.includes('reduced') ? reduced : !touch});
  const entries = [0,1,2].map(i => {
    const video = Object.assign(events(), {dataset:{preview:`/preview-${i}.mp4`},readyState:0,currentTime:0,plays:0,pauses:0,play(){this.plays++;return Promise.resolve();},pause(){this.pauses++;}});
    const classes=new Set();
    const card=Object.assign(events(),{querySelector:()=>video,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}});
    return {card,video,classes};
  });
  const root=Object.assign(events(),{hidden:false,readyState:'complete',querySelectorAll:()=>entries.map(e=>e.card)});
  let observe;
  const calls=[];const windowEvents=events();
  const env={matchMedia:media,navigator:{connection:{saveData}},setTimeout,clearTimeout,AbortController,URL:{createObjectURL:()=>`blob:${Math.random()}`,revokeObjectURL:()=>{}},addEventListener:windowEvents.addEventListener.bind(windowEvents),IntersectionObserver:class {constructor(cb){observe=cb;}observe(){}},fetch(url,{signal}){return new Promise((resolve,reject)=>{calls.push({url,signal,finish:()=>resolve({ok:true,blob:async()=>new Blob(['preview'])}),fail:()=>resolve({ok:false})});signal.addEventListener('abort',()=>reject(new Error('aborted')));});}};
  const controller=initProjectPreviews(root,env);
  return {entries,calls,root,controller,visible:(i,on=true)=>observe([{target:entries[i].card,isIntersecting:on}]),tick:n=>t.mock.timers.tick(n),enter:i=>entries[i].card.dispatchEvent(Object.assign(new Event('pointerenter'),{pointerType:'mouse'})),leave:i=>entries[i].card.dispatchEvent(new Event('pointerleave'))};
}
test('does not download during initial load; visible cards load sequentially',async t=>{
  const f=fixture(t);f.visible(0);f.visible(1);f.tick(1999);assert.equal(f.calls.length,0);f.tick(1);f.tick(100);assert.equal(f.calls.length,1);
  f.calls[0].finish();await flush();f.tick(100);assert.equal(f.calls.length,2);assert.equal(f.calls[1].url,'/preview-1.mp4');
});
test('brief hover is cancelled before downloading',t=>{
  const f=fixture(t);f.enter(0);f.tick(80);f.leave(0);f.tick(200);assert.equal(f.calls.length,0);
});
test('hover takes priority over background and cover stays until playing',async t=>{
  const f=fixture(t);f.visible(0);f.tick(2100);f.enter(1);f.tick(160);assert.equal(f.calls[0].signal.aborted,true);
  await flush();f.tick(100);assert.equal(f.calls[1].url,'/preview-1.mp4');f.calls[1].finish();await flush();assert.equal(f.entries[1].video.plays,1);assert.equal(f.entries[1].classes.has('is-preview-playing'),false);
  f.entries[1].video.dispatchEvent(new Event('playing'));assert.equal(f.entries[1].classes.has('is-preview-playing'),true);
  f.entries[1].video.dispatchEvent(new Event('waiting'));assert.equal(f.entries[1].classes.has('is-preview-playing'),false);
});
test('leaving cancels pending load and late responses never reveal a preview',async t=>{
  const f=fixture(t);f.enter(0);f.tick(160);f.leave(0);assert.equal(f.calls[0].signal.aborted,true);f.calls[0].finish();await flush();assert.equal(f.entries[0].video.plays,0);assert.equal(f.entries[0].classes.size,0);
});
test('completed preview is reused on repeat hover',async t=>{
  const f=fixture(t);f.enter(0);f.tick(160);f.calls[0].finish();await flush();f.leave(0);f.enter(0);f.tick(160);assert.equal(f.calls.length,1);assert.equal(f.entries[0].video.plays,2);
});
test('touch and reduced-motion do not autoplay or prefetch',t=>{
  const f=fixture(t,{touch:true});f.visible(0);f.tick(2200);f.enter(0);f.tick(200);assert.equal(f.calls.length,0);
});
test('save-data keeps intentional hover but disables background downloads',t=>{
  const f=fixture(t,{saveData:true});f.visible(0);f.tick(2200);assert.equal(f.calls.length,0);f.enter(0);f.tick(160);assert.equal(f.calls.length,1);
});
test('failed downloads keep cover and do not retry in a loop',async t=>{
  const f=fixture(t);f.enter(0);f.tick(160);f.calls[0].fail();await flush();f.tick(60000);assert.equal(f.calls.length,1);assert.equal(f.entries[0].classes.size,0);
});
test('background tab stops previews and pending downloads',async t=>{
  const f=fixture(t);f.enter(0);f.tick(160);f.root.hidden=true;f.root.dispatchEvent(new Event('visibilitychange'));await flush();assert.equal(f.calls[0].signal.aborted,true);f.tick(5000);assert.equal(f.calls.length,1);
});

test('reduced-motion keeps still covers',t=>{ const f=fixture(t,{reduced:true});f.visible(0);f.tick(2200);f.enter(0);f.tick(200);assert.equal(f.calls.length,0); });
