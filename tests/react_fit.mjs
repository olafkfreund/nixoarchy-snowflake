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
  window.fetch=async(u,o)=>{ const r=await f0(u,o); if(!/\\/api\\/state/.test(String(u))) return r; const j=await r.json(); return new Response(JSON.stringify({...j,proactive:true,reactions:true,look_meeting:true,look_weather:true,look_music:true,click_through:true})); };
  window.IDS=['load','memory','error','soon','meeting','notice','ask','done','open','rain','snow','wind','workout'];
  window.CH=['snowflake','terminal','robot','devil'];
  window.grp=()=>['#rxSky','#rxBack','#rxFront'].map(s=>document.querySelector(s).innerHTML.length);
  window.empty=()=>grp().every(n=>n===0);
  window.sit=o=>onEvent({t:'situation',...Object.fromEntries(Object.entries(SIT).filter(([k])=>k!=='weather')),weather:SIT.weather,...o});
  window.rxReset=()=>{ RXS.clear(); musKeep=false; rxEnd(); musSync(); RX_AT={}; stgState='closed'; info.look_beat=false;
    sit({meeting:false,fullscreen:false,locked:false,cpu_hot:false,ram_low:false,music:false,windy:false,weather:null});
    for(const k in sitOn){ sitOn[k]=false; sitSeen[k]=false; } nudgeQ.clear(); notifyQ.length=0; if(notifyRow) notifyClear(); notifyRow=null; notifyAt=0;
    Object.assign(info,{proactive:true,reactions:true,look_meeting:true,look_weather:true,look_music:true,hover:false}); hiddenNow=false; delete document.hidden;
    document.body.classList.remove('bar','hover','calm','peek'); setCharacter('snowflake'); lastActive=performance.now(); };
  rxReset(); return 1;`);
await sleep(300);
const settle = () => ev(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,60)); return 1;`);

// a real mouse click at a point, or a real key
const click = async (x, y) => { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
  await send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1 }); await sleep(120); };
const esc = async () => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }); await sleep(120); };
const centre = sel => ev(`const r=(${sel}).getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];`);

// 1. every in-scope reaction on every character: draws, stays inside the viewBox, keeps off the eyes, leaves the groups empty
for (const ch of ["snowflake", "terminal", "robot", "devil"]) for (const id of ["load","memory","error","soon","meeting","notice","ask","done","open","rain","snow","wind","workout","music"]) {
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
  await T('done',()=>{ attnPend=null; onEvent({t:'attention',kind:'done',name:'Claude',text:'',from:'x'}); });
  await T('notice',()=>onEvent({t:'notify',key:'n1',category:'other',app:'x',source:'',summary:'s',body:'',icon:'',rt:performance.now()}));
  await T('workout',()=>onEvent({t:'nudge',kind:'break',text:'stretch'}));
  const f0=window.fetch.bind(window); window.fetch=(u,x)=>/api\\/quick/.test(String(u))?Promise.resolve(new Response(JSON.stringify({handled:true,say:'Opening Firefox.',opened:true}))):f0(u,x);
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

// Step 5: the Devil keeps his own reds while the other characters use the selected body colour.
const red = await ev(`rxReset(); const out=[];
  for(const colour of ['#1b2a4a','#50c878']){
    const L={...LOOK,body:colour,character:'devil',follow_theme:false}; info.look=L; applyLook(L);   // (the previews draw curLook(), which reads info.look)
    const stops=id=>[...document.querySelectorAll('#'+id+' stop')].map(s=>s.getAttribute('stop-color'));
    const back=document.querySelector('#body>.nix');
    out.push({ball:document.querySelector('#body>path.ball').getAttribute('fill'),rim:getComputedStyle($('#rim')).stroke,
      body:stops('devBody'),wing:stops('devWing'),backBody:back.querySelector('path[fill="url(#devBody)"]')?.getAttribute('fill'),
      wings:[...back.querySelectorAll('[fill="url(#devWing)"]')].length,tail:!!back.querySelector('.tTail'),fork:!!back.querySelector('.dFork')});
    renderSettings(); drawPreview();
    for(const sel of ['#lookPrev','#characterGrid [data-character="devil"] svg','#set .hd .logo']){
      const svg=document.querySelector(sel), b=svg.querySelector('path[data-part="body"]'), g=svg.querySelector('radialGradient[id$="devBody"]');
      out.push({preview:!!b&&!!g&&b.getAttribute('fill')==='url(#'+g.id+')',stops:g?[...g.querySelectorAll('stop')].map(s=>s.getAttribute('stop-color')):[]}); }
    out.push(...['snowflake','terminal','robot'].map(id=>{setCharacter(id);return {fill:document.querySelector('#body>path.ball').getAttribute('fill'),
      stops:['--body0','--body1','--body2'].map(v=>document.documentElement.style.getPropertyValue(v)),expected:bodyStops(colour)};}));
  } rxReset(); return out;`);
for(let i=0;i<red.length;i+=7){
  const d=red[i];
  check(d.ball==='url(#devBody)' && d.rim==='rgb(92, 10, 28)' && JSON.stringify(d.body)===JSON.stringify(['#e0334f','#c81e3a','#7a0f24']) &&
    JSON.stringify(d.wing)===JSON.stringify(d.body) && d.backBody==='url(#devBody)' && d.wings>=2 && d.tail && d.fork,
    `Devil ball and back art stay red for body colour ${i/7}`, d);
  for(let j=1;j<=3;j++) check(red[i+j].preview && JSON.stringify(red[i+j].stops)===JSON.stringify(d.body),
    `Devil preview ${j} stays red for body colour ${i/7}`,red[i+j]);
  check(red.slice(i+4,i+7).every(x=>x.fill==='url(#ballG)'&&JSON.stringify(x.stops)===JSON.stringify(x.expected)),
    `the other three characters use the selected body colour ${i/7}`,red.slice(i+4,i+7));
}

const forks = await ev(`rxReset(); setCharacter('devil'); const stage=$('#stage'), fork=()=>document.querySelector('#body>.nix .dFork'); const out=[];
  for(const id of ['load','memory','error','done','workout']){
    stage.classList.add('c-devil','r-'+id); await new Promise(r=>setTimeout(r,220)); out.push([id,getComputedStyle(fork()).opacity]);
    stage.classList.remove('r-'+id);
  }
  stage.classList.remove('c-devil'); sit({cpu_hot:true}); setCharacter('devil'); rxEnd();
  await new Promise(r=>setTimeout(r,220)); out.push(['sustained load',getComputedStyle(fork()).opacity]);
  sit({cpu_hot:false,ram_low:true}); rxEnd(); await new Promise(r=>setTimeout(r,220)); out.push(['sustained memory',getComputedStyle(fork()).opacity]);
  rxReset(); return out;`);
check(forks.every(([,opacity])=>+opacity===0),"Devil fork hides for all five left props, including sustained load and memory",forks);

// 11. music: the boombox stands in for the headphones, bops on start and on a track change, and the chip and card follow it
await click(5, 5);                                   // (a real pointer on the page first)
await ev(`rxReset(); window.__q=[]; window.__qr={}; window.fetch0=window.fetch; const f1=window.fetch;
  window.fetch=async(u,o)=>{ if(!/\\/api\\/quick/.test(String(u))) return f1(u,o); const t=JSON.parse(o.body).text; window.__q.push(t);
    const r=window.__qr[t]||{handled:true,say:{"what's playing":"That's Song by Band.",pause:'Paused.',play:'Playing.','next song':'Next one.',quieter:'Volume 40 percent.',louder:'Volume 60 percent.'}[t]}; return new Response(JSON.stringify(r)); };
  window.__nat=[]; window.webkit={messageHandlers:{nixiui:{postMessage:m=>window.__nat.push(String(m))}}}; info.click_through=true; sit({music:true}); return 1;`);
await sleep(3600);
const m1 = await ev(`const cs=SIT_P.hb.getAttribute('opacity'); return {rx:RX&&RX.id, has:RXS.has('music'), hb:+cs, chip:!$('#musChip').hidden, card:!$('#musCard').hidden, sp:document.querySelectorAll('#rxFront .sp').length>0, cl:$('#stage').classList.contains('r-music')};`);
check(m1.rx === "music" && m1.has && m1.hb === 0 && m1.chip && !m1.card && m1.sp && m1.cl, "music: the boombox bops on start, the headphones are gone, the chip shows, the card does not open by itself", m1);
await sleep(4500);
const m2 = await ev(`return {rx:RX&&RX.id, drawn:!empty(), cl:$('#stage').classList.contains('r-music'), chip:!$('#musChip').hidden};`);
check(m2.rx === null && m2.drawn && !m2.cl && m2.chip, "music: after the 4 s bop the boombox stays still", m2);
const m3 = await ev(`const o=[]; sit({track:1}); o.push(RX&&RX.id); rxEnd(); sit({track:2}); o.push(RX&&RX.id); rxEnd(); sit({track:2}); o.push(RX&&RX.id); return o;`);
eq(m3, ["music", "music", null], "music: a track change bops again, ignoring the 10 minute rule; no change, no bop");
const m4 = await ev(`info.look_beat=true; beat=1; beatAt=performance.now(); await new Promise(r=>setTimeout(r,80)); const a=document.querySelector('#rxFront .sp').style.transform; info.look_beat=false; beatAt=0; await new Promise(r=>setTimeout(r,300)); return [a, document.querySelector('#rxFront .sp').style.transform];`);
check(/scale\((1\.\d+)\)/.test(m4[0]) && !/1\.1\d/.test(m4[1]), "music: with look_beat the speakers pulse, without it they rest", m4);
const m5 = await ev(`info.reactions=false; showInfo(); await new Promise(r=>setTimeout(r,500)); const o={empty:empty(), chip:$('#musChip').hidden, hb:+SIT_P.hb.getAttribute('opacity')}; info.reactions=true; showInfo(); return o;`);
check(m5.empty && m5.chip && m5.hb > 0, "music: with reactions off, no boombox or chip and the headphones are back", m5);
await sleep(300);
// the card: opens on a click only, one fixed phrase per button, the answer is shown by textContent, never spoken
await ev(`window.__say.length=0; return 1;`);
const chipAt = await centre("$('#musChip')");
await click(...chipAt);
const c1 = await ev(`const c=$('#musCard'); return {open:!c.hidden, said:c.querySelector('.mt').textContent, q:[...window.__q], say:window.__say.length};`);
eq([c1.open, c1.said, c1.q, c1.say], [true, "That's Song by Band.", ["what's playing"], 0], "card: a click opens it and asks what's playing; nothing is spoken");
const regionCovers = async sel => ev(`const rs=window.__nat.filter(m=>m.startsWith('region:')).pop(); const R=(rs&&JSON.parse(rs.slice(7)))||[]; const r=document.querySelector('${sel}').getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2; return R.some(([a,b,w,h])=>x>=a&&x<=a+w&&y>=b&&y<=b+h);`);
check(await regionCovers("#musChip") && await regionCovers("#musCard"), "card: sendRegion covers the chip and the card");
for (const [label, phrase, say] of [["Next", "next song", "Next one."], ["Quieter", "quieter", "Volume 40 percent."], ["Louder", "louder", "Volume 60 percent."]]) {
  const at = await centre(`[...document.querySelectorAll('#musCard .mbs button')].find(b=>b.textContent==='${label}')`);
  await click(...at);
  const r = await ev(`return [window.__q.at(-1), $('#musCard .mt').textContent];`);
  eq(r, [phrase, say], `card: ${label} posts "${phrase}" and shows the answer`);
}
await ev(`window.__qr.louder={handled:false}; return 1;`);
await click(...await centre(`[...document.querySelectorAll('#musCard .mbs button')].find(b=>b.textContent==='Louder')`));
eq(await ev(`return [$('#musCard .mt').textContent, window.__say.length];`), ["I couldn't do that.", 0], "card: an unhandled answer shows the fixed line");
await ev(`delete window.__qr.louder; return 1;`);
// Pause: the card and chip stay with Play when the music stops, until Play
await click(...await centre(`$('#musCard .mp')`));
eq(await ev(`return [window.__q.at(-1), $('#musCard .mp').textContent];`), ["pause", "Play"], "card: Pause posts pause and turns into Play");
const kept = await ev(`sitOn.music=false; sitSeen.music=false; RXS.delete('music'); sit({music:false}); rxCheck(); await new Promise(r=>setTimeout(r,100)); return [!$('#musCard').hidden, !$('#musChip').hidden, $('#musCard .mp').textContent];`);
eq(kept, [true, true, "Play"], "card: after its own Pause the card and chip stay with Play");
await click(...await centre(`$('#musCard .mp')`));
eq(await ev(`return [window.__q.at(-1), $('#musCard .mp').textContent];`), ["play", "Pause"], "card: Play posts play");
const gone = await ev(`rxCheck(); await new Promise(r=>setTimeout(r,100)); return [$('#musCard').hidden, $('#musChip').hidden];`);
eq(gone, [true, true], "card: music stopping on its own closes the card and the chip");
// the close paths
const reopen = async () => { await ev(`rxReset(); window.__q.length=0; sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); return 1;`); await click(...await centre("$('#musChip')")); };
await reopen(); await esc();
eq(await ev(`return $('#musCard').hidden;`), true, "card: Esc closes it");
await reopen(); await click(...await centre("$('#musCard .mx')"));
eq(await ev(`return $('#musCard').hidden;`), true, "card: × closes it");
await reopen(); await click(810, 610);
eq(await ev(`return $('#musCard').hidden;`), true, "card: a click elsewhere closes it");
await reopen();
const side = await ev(`const c=$('#musCard'); const o=[]; for(const sd of ['r','l']){ stgState='open'; stgSide=sd; musClose(); musOpen(); o.push(c.style.left); } stgState='closed'; return o;`);
check(side[0] !== "350px" && side[1] !== "-220px", "card: it opens on the side away from a board", side);
await reopen(); await sleep(15600);
eq(await ev(`return $('#musCard').hidden;`), true, "card: 15 s idle closes it");
// a long answer stays three lines, so the card fits the 160px left below top:300 in the 340x460 window (Codex, #71)
const LONG = "That's " + "A very long song title ".repeat(13) + "by Band.";
await ev(`window.__qr["what's playing"]={handled:true,say:${JSON.stringify(LONG)}}; return 1;`);
await reopen(); await sleep(300);
const tall = await ev(`const c=$('#musCard'), t=c.querySelector('.mt'); const r=c.getBoundingClientRect(), b=[...c.querySelectorAll('.mbs button')].map(x=>x.getBoundingClientRect().bottom-r.top); return {h:r.height, b:Math.max(...b), title:t.title};`);
check(tall.h <= 160 && tall.b <= 160 && tall.title === LONG, "card: a long answer is clamped and the buttons stay within 160px; the full answer is its title", tall);
await ev(`delete window.__qr["what's playing"]; musClose(); return 1;`);
for (const [name, js] of Object.entries({ fullscreen: "sit({fullscreen:true})", "notch": "document.body.classList.add('bar')", "meeting": "sit({meeting:true})", "hover": "document.body.classList.add('hover')" })) {
  await reopen(); await ev(`${js}; await new Promise(r=>setTimeout(r,100)); return 1;`);
  eq(await ev(`return [$('#musCard').hidden, $('#musChip').hidden];`), [true, true], `card: ${name} closes the card and hides the chip`);
}
// 12. review fixes, each pinned
// (a) setCharacter leaves #rim unfilled (it carries class "ball" but is only the outline)
eq(await ev(`return CH.map(c=>{ setCharacter(c); return document.querySelector('#rim').getAttribute('fill'); });`), ["none", "none", "none", "none"], "setCharacter leaves #rim's fill at none for every character");
await ev(`setCharacter('snowflake'); return 1;`);
// (b) Escape closes only the music card, not a pending approval
const apprEsc = async () => { await ev(`rxReset(); window.__q.length=0; window.__ap=[]; const f2=window.fetch; window.fetch=async(u,o)=>{ if(/\\/api\\/approve/.test(String(u))){ window.__ap.push(String(u)); return new Response('{"ok":true}'); } return f2(u,o); };
    sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); return 1;`);
  await sleep(300); await click(...await centre("$('#musChip')"));
  // (a real approval would put the page in calm, which closes the card by itself; here it is pending with the card still open)
  await ev(`pendingAppr={id:'ap1',tool:'Bash',detail:'ls',q:'Can I run this?',confirm:'voice'}; return 1;`);
  await esc(); await sleep(200);
  return ev(`const o={card:$('#musCard').hidden, pending:!!pendingAppr&&pendingAppr.id==='ap1', posts:[...window.__ap]}; pendingAppr=null; return o;`); };
eq(await apprEsc(), { card: true, pending: true, posts: [] }, "Escape with the music card open closes only the card; the approval stays pending");
// (c) after the card's own Pause, a meeting still hides the chip and card
await ev(`rxReset(); sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); return 1;`);
await click(...await centre("$('#musChip')"));
await click(...await centre("$('#musCard .mp')"));
await ev(`sitOn.music=false; sitSeen.music=false; RXS.delete('music'); sit({music:false}); rxCheck(); return 1;`);
eq(await ev(`return [!$('#musCard').hidden, !$('#musChip').hidden];`), [true, true], "after Pause the chip and card stay (before the meeting)");
await ev(`sit({meeting:true}); await new Promise(r=>setTimeout(r,100)); return 1;`);
eq(await ev(`return [$('#musCard').hidden, $('#musChip').hidden];`), [true, true], "after Pause, a meeting hides the chip and the card");
// (d) the headphones come back when the boombox cannot show (Proactive off)
const hp = await ev(`rxReset(); sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); await new Promise(r=>setTimeout(r,1200)); const on=+SIT_P.hb.getAttribute('opacity');
  info.proactive=false; showInfo(); await new Promise(r=>setTimeout(r,800)); return [on, +SIT_P.hb.getAttribute('opacity'), empty(), $('#musChip').hidden];`);
check(hp[0] === 0 && hp[1] > 0 && hp[2] && hp[3], "reactions on, music on, Proactive off: the headphones are back and the boombox is gone", hp);
// (e) with nothing to wear the look layer settles (sitSettled stops the per-frame writes)
const settled = await ev(`rxReset(); sitSettled=false; await new Promise(r=>setTimeout(r,2500)); return sitSettled;`);
eq(settled, true, "with nothing to wear the look layer settles");
// (f) "open" plays only when the server says it opened something, not for any reply that starts with "Opening"
await ev(`window.__qr['when are you open']={handled:true,say:'Opening hours are 9-5'}; rxReset(); await send('when are you open'); await new Promise(r=>setTimeout(r,80)); return 1;`);
eq(await ev(`return [RX&&RX.id, empty()];`), [null, true], "a handled reply that only says \"Opening hours…\" plays no open reaction");
// (g) a finish never plays over a pending question, even well after the question's own reaction ended
await ev(`rxReset(); onEvent({t:'attention',kind:'ask',name:'Claude',text:'needs you',from:'x'}); return 1;`);
await sleep(3400);
eq(await ev(`const a=RX&&RX.id; onEvent({t:'attention',kind:'done',name:'Claude',text:'',from:'x'}); await new Promise(r=>setTimeout(r,80)); const o=[a, RX&&RX.id, $('#stage').classList.contains('r-done')]; attnPend=null; return o;`), [null, null, false], "a done while an ask is pending plays no done reaction");
// (h) reduced motion: the speakers do not pulse to the beat
const pulse = async () => ev(`rxReset(); sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); await new Promise(r=>setTimeout(r,2500));
  info.look_beat=true; beat=1; beatAt=performance.now(); await new Promise(r=>setTimeout(r,60)); const t=document.querySelector('#rxFront .sp').style.transform; rxReset(); return t;`);
const moving = await pulse();
check(parseFloat(moving.slice(6))>1.01, "speakers pulse to the beat with motion allowed", moving);
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
const still = await pulse();
check(!(parseFloat(still.slice(6))>1.01), "reduced motion: the speakers do not pulse", still);
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
// (i) closing the card by hand after its own Pause takes the chip with it; music resuming elsewhere resets the button
const paused = async () => { await ev(`rxReset(); sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); return 1;`);
  await click(...await centre("$('#musChip')")); await click(...await centre("$('#musCard .mp')"));
  await ev(`sitOn.music=false; sitSeen.music=false; RXS.delete('music'); sit({music:false}); rxCheck(); return 1;`); };
await paused();
eq(await ev(`return [!$('#musChip').hidden, !$('#musCard').hidden];`), [true, true], "Pause then music stops: chip and card stay");
await click(...await centre("$('#musCard .mx')"));
eq(await ev(`return [$('#musChip').hidden, $('#musCard').hidden];`), [true, true], "after Pause, × takes the chip with it");
await paused(); await click(810, 610);
eq(await ev(`return [$('#musChip').hidden, $('#musCard').hidden];`), [true, true], "after Pause, a click elsewhere takes the chip with it");
await paused();
const back = await ev(`sit({music:true}); sitOn.music=true; sitSeen.music=true; RXS.add('music'); rxCheck(); const b=$('#musCard .mp'); return [b.textContent, b.dataset.p, musKeep];`);
eq(back, ["Pause", "pause", false], "after Pause, music playing again from outside resets the button to Pause");
await ev(`rxReset(); window.fetch=window.fetch0; return 1;`);

if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("react fit ok");
process.exit(0);
