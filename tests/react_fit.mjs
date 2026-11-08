// Pins the reaction engine (#208 step 3):
//   node tests/notify_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
// Nothing is spoken: sfx and enqueue are stubbed; the music card comes in step 4.
const [port, url] = process.argv.slice(2);
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 820, height: 620, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4000);

const fails = [];
const check = (ok, what, got) => { if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + JSON.stringify(got)}`); } };
const eq = (got, want, what) => check(JSON.stringify(got) === JSON.stringify(want), what, got);


await ev(`
  window.__say=[]; sfx=n=>{}; enqueue=(t,o)=>window.__say.push(t);
  nixiIdleScale(1000); const f0=window.fetch.bind(window);   // the page re-reads /api/state every few seconds: keep the flags the test turned on
  window.fetch=async(u,o)=>{ const r=await f0(u,o); if(!/\\/api\\/state/.test(String(u))) return r; const j=await r.json(); return new Response(JSON.stringify({...j,proactive:true,reactions:true,look_meeting:true,look_weather:true})); };
  window.IDS=['load','memory','error','soon','meeting','notice','ask','done','open','rain','snow','wind','workout'];
  window.CH=['snowflake','terminal','robot','devil'];
  window.grp=()=>['#rxSky','#rxBack','#rxFront'].map(s=>document.querySelector(s).innerHTML.length);
  window.empty=()=>grp().every(n=>n===0);
  window.sit=o=>onEvent({t:'situation',...Object.fromEntries(Object.entries(SIT).filter(([k])=>k!=='weather')),weather:SIT.weather,...o});
  window.rxReset=()=>{ RXS.clear(); rxEnd(); RX_AT={};
    sit({meeting:false,fullscreen:false,locked:false,cpu_hot:false,ram_low:false,music:false,windy:false,weather:null});
    for(const k in sitOn){ sitOn[k]=false; sitSeen[k]=false; } nudgeQ.clear(); notifyQ.length=0; if(notifyRow) notifyClear(); notifyRow=null; notifyAt=0;
    Object.assign(info,{proactive:true,reactions:true,look_meeting:true,look_weather:true,hover:false}); hiddenNow=false; delete document.hidden;
    document.body.classList.remove('bar','hover','calm','peek'); setCharacter('snowflake'); lastActive=performance.now(); };
  rxReset(); return 1;`);
await sleep(300);
const settle = () => ev(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,60)); return 1;`);

// 1. every in-scope reaction on every character: draws, stays inside the viewBox, keeps off the eyes, leaves the groups empty
for (const ch of ["snowflake", "terminal", "robot", "devil"]) for (const id of ["load","memory","error","soon","meeting","notice","ask","done","open","rain","snow","wind","workout"]) {
  const r = await ev(`rxReset(); setCharacter('${ch}'); const ok=rxPlay('${id}'); await new Promise(r=>setTimeout(r,120)); document.getAnimations().forEach(a=>{ a.pause(); a.currentTime=0; });
    const sv=document.querySelector('#guy').getBoundingClientRect(), eyes=[E.eL,E.eR].map(e=>e.getBoundingClientRect()), out=[], hit=[];
    for(const s of ['#rxSky','#rxBack','#rxFront']) for(const c of document.querySelector(s).querySelectorAll('rect,circle,path,ellipse,line,polygon,text')){ const b=c.getBoundingClientRect(); if(!b.width&&!b.height) continue;
      if(b.left<sv.left-1||b.right>sv.right+1||b.top<sv.top-1||b.bottom>sv.bottom+1) out.push(s+' '+c.tagName+' '+JSON.stringify([b.left,b.top,b.right,b.bottom,'svg',sv.left,sv.top,sv.right,sv.bottom].map(Math.round))); }
    for(const e of eyes) for(const [fx,fy] of [[.5,.5],[.5,.25],[.5,.75],[.25,.5],[.75,.5]]) for(const el of document.elementsFromPoint(e.left+e.width*fx,e.top+e.height*fy)) if(el.closest('#rxBack,#rxFront')) hit.push(el.tagName+' '+el.parentNode.getAttribute('class'));
    const cl=document.querySelector('#stage').classList, drawn=!empty(), has=[cl.contains('r-${id}'),cl.contains('c-${ch}')];
    rxEnd(); return {ok,drawn,has,out,hit,after:empty(),left:[...document.querySelector('#stage').classList].filter(c=>/^(r|c)-|^rx$/.test(c))};`);
  check(r.ok && r.drawn && r.has.every(Boolean), `${id} on ${ch} plays and sets r-/c- classes`, r);
  check(r.out.length === 0, `${id} on ${ch} stays inside the viewBox`, r.out);
  check(r.hit.length === 0, `${id} on ${ch} does not cover the eyes`, r.hit);
  check(r.after && r.left.length === 0, `${id} on ${ch} leaves the groups and classes empty`, r);
}

// 2. nothing plays when a blocker holds
const blockers = {
  "reactions off": "info.reactions=false", "proactive off": "info.proactive=false", "notch": "document.body.classList.add('bar')",
  "hover": "document.body.classList.add('hover')", "calm": "document.body.classList.add('calm')", "peek": "document.body.classList.add('peek')",
  "fullscreen": "sit({fullscreen:true})", "locked": "sit({locked:true})", "page hidden": "Object.defineProperty(document,'hidden',{get:()=>true,configurable:true})",
  "sent away": "hiddenNow=true" };
for (const [name, js] of Object.entries(blockers)) {
  const r = await ev(`rxReset(); ${js}; await new Promise(r=>setTimeout(r,60)); const ok=rxPlay('rain'); return [ok, empty(), RX];`);
  eq(r, [false, true, null], `nothing plays with ${name}`);
}
eq(await ev(`rxReset(); sit({meeting:true}); await new Promise(r=>setTimeout(r,60)); return ['load','rain','notice','error','done','meeting','ask'].map(i=>{ RX=null; RX_AT={}; return rxPlay(i); });`),
  [false, false, false, false, false, true, true], "in a meeting only meeting and ask play");

// 3. a blocker arriving mid-reaction (with a sustained prop under it) empties the groups; all but the playing one returns when it clears
const arrive = { ...blockers,
  "meeting (SIT.meeting, before sitOn)": "sit({meeting:true})" };
delete arrive["page hidden"]; delete arrive["sent away"]; delete arrive["reactions off"]; delete arrive["proactive off"];
const mid = {
  ...arrive,
  "reactions off": ["info.reactions=false;showInfo()", "info.reactions=true;showInfo()"],
  "proactive off": ["info.proactive=false;showInfo()", "info.proactive=true;showInfo()"],
  "page hidden": ["Object.defineProperty(document,'hidden',{get:()=>true,configurable:true});document.dispatchEvent(new Event('visibilitychange'))", "delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))"],
  "sent away": ["nixiHidden()", "nixiShown()"] };
const undo = { "notch": "document.body.classList.remove('bar')", "hover": "document.body.classList.remove('hover')", "calm": "document.body.classList.remove('calm')", "peek": "document.body.classList.remove('peek')",
  "fullscreen": "sit({fullscreen:false})", "locked": "sit({locked:false})", "meeting (SIT.meeting, before sitOn)": "sit({meeting:false})" };
for (const [name, v] of Object.entries(mid)) {
  const [on, off] = Array.isArray(v) ? v : [v, undo[name]];
  const r = await ev(`rxReset(); sit({cpu_hot:true}); rxEnd(); const sust=rxPlay('rain'); const a=[!empty(), [...RXS]];   // (the sustained load starts via the situation event, then rain plays over it)
    ${on}; await new Promise(r=>setTimeout(r,80)); const during={empty:empty(), RX:RX&&RX.id, cl:document.querySelector('#stage').classList.contains('rx')};
    ${off}; await new Promise(r=>setTimeout(r,80)); const back={drawn:!empty(), RX:RX&&RX.id, cl:document.querySelector('#stage').className, sust:[...RXS]}; return {a,during,back};`);
  check(r.sust !== false && r.a && r.a[0] && r.a[1].includes('load'), `${name}: a reaction and the sustained prop were up first`, r);
  check(r.during && r.during.empty && r.during.RX === null && !r.during.cl, `${name} arriving mid-reaction empties the groups and ends it`, r);
  check(r.back && r.back.drawn && r.back.RX === null && r.back.sust.includes('load') && !/r-rain/.test(r.back.cl), `${name} clearing brings the sustained prop back, not the reaction`, r);
}

// 4. the sitOn reactions fire from a real situation event after sitStep's 3 s wait, on the page's own clock
for (const [id, sitEv, look] of [["meeting", "{meeting:true}", "look_meeting"], ["rain", "{weather:'rain'}", "look_weather"], ["snow", "{weather:'snow'}", "look_weather"], ["wind", "{windy:true,lean:1}", "look_weather"]]) {
  await ev(`rxReset(); info.${look}=true; sit(${sitEv}); return 1;`);
  await sleep(1500);
  const early = await ev(`return RX&&RX.id;`);
  await sleep(2500);
  const late = await ev(`return RX&&RX.id;`);
  check(early === null && late === id, `${id} starts after the 3 s wait, not before`, [early, late]);
}
await ev(`rxReset(); return 1;`);

// 5. load and memory: start on the turn-on, still prop stays, gone with the signal
const sus = await ev(`rxReset(); const o=[]; sit({cpu_hot:true}); o.push(RX&&RX.id,[...RXS]); await new Promise(r=>setTimeout(r,3300)); o.push(RX&&RX.id,!empty(),document.querySelector('#stage').className.includes('r-load'));
  sit({ram_low:true}); o.push(RX&&RX.id,[...RXS]); await new Promise(r=>setTimeout(r,3300)); o.push(!empty());
  sit({cpu_hot:false}); o.push([...RXS]); sit({ram_low:false}); o.push([...RXS],empty()); return o;`);
eq(sus, ["load", ["load"], null, true, false, "memory", ["load", "memory"], true, ["memory"], [], true], "load and memory: play on turn-on, a still prop stays, gone with the signal");

// 5b. the signal turning on under another reaction, or under fullscreen, still gives the still prop once that clears
const under = await ev(`const o=[]; rxReset(); rxPlay('rain'); sit({cpu_hot:true}); o.push(RX&&RX.id,[...RXS]); rxEnd(); o.push(!empty());
  rxReset(); sit({fullscreen:true}); sit({fullscreen:true,ram_low:true}); o.push(empty(),[...RXS]); sit({fullscreen:false,ram_low:true}); await new Promise(r=>setTimeout(r,80)); o.push(!empty(),RX&&RX.id); rxReset(); return o;`);
eq(under, ["rain", ["load"], true, true, ["memory"], true, null], "a sustained prop turned on under another reaction or fullscreen shows when it clears");

// 6. the real handlers: ambient, attention, notification, nudge and the quick reply
const trig = await ev(`const o={}; const T=async(k,f)=>{ rxReset(); f(); await new Promise(r=>setTimeout(r,60)); o[k]=RX&&RX.id; };
  await T('error',()=>onEvent({t:'ambient',sys:['a.service'],cal:null,weather:null}));
  await T('soon',()=>onEvent({t:'ambient',alert:true,cal:{time:'10:00',title:'x'},sys:[],weather:null}));
  await T('ask',()=>onEvent({t:'attention',kind:'ask',name:'Claude',text:'needs you',from:'x'}));
  await T('done',()=>onEvent({t:'attention',kind:'done',name:'Claude',text:'',from:'x'}));
  await T('notice',()=>onEvent({t:'notify',key:'n1',category:'other',app:'x',source:'',summary:'s',body:'',icon:'',rt:performance.now()}));
  await T('workout',()=>onEvent({t:'nudge',kind:'break',text:'stretch'}));
  const f0=window.fetch.bind(window); window.fetch=(u,x)=>/api\\/quick/.test(String(u))?Promise.resolve(new Response(JSON.stringify({handled:true,say:'Opening Firefox.'}))):f0(u,x);
  rxReset(); await send('open firefox'); await new Promise(r=>setTimeout(r,60)); o.open=RX&&RX.id; window.fetch=f0;
  await T('notice_job',()=>onEvent({t:'notify',key:'n2',category:'other',app:'nixi-job',summary:'s',body:'',icon:'',rt:performance.now()}));
  rxReset(); return o;`);
eq(trig, { error: "error", soon: "soon", ask: "ask", done: "done", notice: "notice", workout: "workout", open: "open", notice_job: null }, "each real signal plays its reaction (a long-command row does not)");

// 7. an approval is never held up: ask preempts a playing reaction, and plays even when the same ask came just before
eq(await ev(`rxReset(); rxPlay('rain'); const a=rxPlay('ask'); rxEnd(); const b=rxPlay('ask'); return [a,b];`), [true, true], "ask preempts and repeats");

// 8. the same reaction twice in 10 minutes plays once
eq(await ev(`rxReset(); const a=rxPlay('error'); rxEnd(); const b=rxPlay('error'); RX_AT.error-=600001; const c=rxPlay('error'); return [a,b,c];`), [true, false, true], "once per 10 minutes");
eq(await ev(`rxReset(); const a=rxPlay('rain'); const b=rxPlay('error'); return [a,b];`), [true, false], "one at a time, a late one is dropped");

// 9. reduced motion: no reaction animation runs; the prop shows still
const anims = async () => ev(`rxReset(); setCharacter('devil'); rxPlay('load'); await new Promise(r=>setTimeout(r,200)); const n=document.getAnimations().filter(a=>a.animationName&&/^fx/.test(a.animationName)).length, d=!empty(); rxReset(); return [n,d];`);
const normal = await anims();
check(normal[0] > 0 && normal[1], "without reduced motion the reaction animates", normal);
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
const reduced = await anims();
check(reduced[0] === 0 && reduced[1], "reduced motion: the prop shows and no animation runs", reduced);
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });

// 10. setCharacter to each character and back, and the notch, still work
const sc = await ev(`rxReset(); const b0=document.querySelector('#body>path.ball').getAttribute('d'); const o=[];
  rxPlay('load',true); for(const c of CH){ setCharacter(c); o.push(document.querySelector('#stage').classList.contains('c-'+c), document.querySelector('#body>path.ball').getAttribute('d')===CHARACTERS[c].ball); }
  setCharacter('snowflake'); RXS.clear(); rxEnd(); document.body.classList.add('bar'); await new Promise(r=>setTimeout(r,80)); o.push(rxPlay('rain')); document.body.classList.remove('bar');
  await new Promise(r=>setTimeout(r,80)); o.push(document.querySelector('#body>path.ball').getAttribute('d')===b0, empty()); return o;`);
eq(sc, [true, true, true, true, true, true, true, true, false, true, true], "setCharacter round trip and the notch");

if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("react fit ok");
process.exit(0);
