// The weather marks (#157): the layer follows the camera, no rain touches his face, reduced motion holds still, wind drifts the cloud
// across and wraps once, heavy rain shows three clouds, and a change of sky cross-fades.
//   node tests/weather_fit.mjs <cdp-port> <page-url>
// Headless Chromium with --disable-gpu only (never a desktop browser: #138). The marks' own test clock (WXT) is stepped, so nothing depends on timing.
// Exit 0 = all good.
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
const fails = [];
const check = (name, ok, detail = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? "  " + detail : ""}`); if (!ok) fails.push(name); };

// hold one sky/state and wait until his looks have switched (3 s on, 8 s off); fidgets held off as in accessories_fit.mjs
const INIT = `setInterval(()=>{ nextFidAt=1e15; },50); window.__hold=null; await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full');
  window.wxSleep=ms=>new Promise(r=>setTimeout(r,ms)); window.raf2=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  window.wxSet=async(o,wait=true)=>{ clearInterval(window.__hold);
    const hold=()=>{ for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false;   // (SIT.day is a boolean too: set it after)
      Object.assign(SIT,{day:o.day!==false,weather:o.kind||null,heavy:!!o.heavy,windy:!!o.windy,lean:o.lean||0,party:!!o.party,cold:o.cold||0});
      Object.assign(info,{look_weather:true,look_party:true}); lowFx=!!o.lowFx; nextFidAt=1e15; };
    hold(); window.__hold=setInterval(hold,50); if(!wait) return 1;
    const want={rain:0,snow:0,clear:0,partly:0,cloudy:0,windy:!!o.windy,party:!!o.party,night:0,cold2:(o.cold||0)>=2}; if(o.kind) want[o.kind]=true;
    for(let i=0;i<400;i++){ if(Object.keys(want).every(k=>sitOn[k]===!!want[k])){ await wxSleep(1200); return 1; } await wxSleep(50); }
    throw new Error('looks did not settle '+JSON.stringify(sitOn)); };
  // every streak end of the rain, in #guy units: [violations of the face box (x -56..56, y > -48), lowest y, streaks seen]
  window.wxFace=async(n,dt)=>{ const guy=document.getElementById('guy'), bad=[]; let lowest=-1e9, seen=0;
    for(let i=0;i<n;i++){ WXT=i*dt; await raf2(); const M=guy.getScreenCTM().inverse();
      for(const d of WX.rain.drops){ if(d.getAttribute('display')==='none') continue; seen++; const m=M.multiply(d.getScreenCTM()), L=d.getTotalLength();
        for(const s of [0,L]){ const p=d.getPointAtLength(s), q=new DOMPoint(p.x,p.y).matrixTransform(m); lowest=Math.max(lowest,q.y);
          if(q.x>-56&&q.x<56&&q.y>-48) bad.push([i,+q.x.toFixed(1),+q.y.toFixed(1)]); } } }
    WXT=null; return {bad:bad.slice(0,4),nbad:bad.length,seen,lowest}; };
  window.wxSnap=()=>JSON.stringify([...document.getElementById('wx').querySelectorAll('*')].map(e=>[...e.attributes].map(a=>a.name+'='+a.value)));
  window.cloudX=g=>g.transform.baseVal[0].matrix.e;
  return 1`;
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4500);
await ev(INIT);

// the layer sits right after the camera group, in front of it
check("#wx follows #cam", await ev("const w=document.getElementById('wx'); return w.previousElementSibling?.id==='cam' && w.parentNode.id==='guy'"));

// wxAlpha: a streak fades in, peaks at .85 and fades out
check("wxAlpha shape", await ev("return wxAlpha(0)===0 && Math.abs(wxAlpha(.5)-.85)<1e-9 && Math.abs(wxAlpha(1))<1e-9 && Math.abs(wxAlpha(.25)-wxAlpha(.75))<1e-9 && [...Array(21)].every((_,i)=>wxAlpha(i/20)<=.85+1e-9&&wxAlpha(i/20)>=-1e-9)"));

// no streak enters the face box, in the head slot and in the hat slot; head-slot streaks stop at y -60
for (const [name, o] of [["head, calm", {}], ["head, heavy", { heavy: true }], ["head, windy lean -1", { windy: true, lean: -1 }], ["head, windy lean +1", { windy: true, lean: 1 }],
  ["hat, calm", { party: true }], ["hat, heavy windy lean +1", { party: true, heavy: true, windy: true, lean: 1 }], ["hat, cold 2", { cold: 2 }]]) {
  await ev(`await wxSet(${JSON.stringify({ kind: "rain", ...o })}); return 1`);
  const r = await ev("return await wxFace(20,.7)");
  const hat = /^hat/.test(name);
  check(`rain off his face: ${name}`, r.seen > 0 && r.nbad === 0 && (hat || r.lowest <= -60 + .5), `streaks ${r.seen}, in face box ${r.nbad} ${JSON.stringify(r.bad)}, lowest y ${r.lowest.toFixed(1)}`);
  // the hat slot: the cloud sits to his left (wind drifts it across, so calm only)
  if (hat && !o.windy) { const xs = await ev("const a=[]; for(const t of [0,6.25,12.5,18.75]){ WXT=t; await raf2(); a.push(cloudX(WX.rain.g)); } WXT=null; return a"); check(`cloud centre x < -40: ${name}`, xs.every(x => x < -40), xs.map(x => x.toFixed(1)).join(",")); }
}

// windy drift: the main cloud's x is monotonic over one 14 s pass, except one wrap
for (const lean of [-1, 1]) {
  await ev(`await wxSet({kind:'rain',windy:true,lean:${lean}}); return 1`);
  const xs = await ev("const a=[]; for(let t=0;t<=14;t+=.5){ WXT=t; await raf2(); a.push(cloudX(WX.rain.g)); } WXT=null; return a");
  const sign = lean < 0 ? 1 : -1, wraps = xs.slice(1).filter((x, i) => (x - xs[i]) * sign < 0).length;
  check(`windy drift lean ${lean}`, wraps <= 1 && xs.length === 29 && Math.abs(xs[27] - xs[0]) > 100, `${wraps} wrap, x ${xs[0].toFixed(0)} → ${xs[27].toFixed(0)}`);
}

// heavy rain: the main cloud and two extra ones; one only under lowFx
await ev("await wxSet({kind:'rain',heavy:true}); WXT=2; await raf2(); return 1");
const clouds = () => ev("return [WX.rain.g,...WX.ex].filter(g=>g.getAttribute('display')!=='none'&&+g.getAttribute('opacity')>.5).length");
check("heavy rain: 3 clouds", (await clouds()) === 3);
await ev("await wxSet({kind:'rain',heavy:true,lowFx:true},false); await wxSleep(1500); WXT=2; await raf2(); return 1");
check("heavy rain under lowFx: 1 cloud", (await clouds()) === 1);

// cross-fades: the old mark is gone (display none) within a second of the change taking effect, the new one is fully in
const fade = (from, to, flip, oldG, newG) => ev(`await wxSet(${JSON.stringify(from)}); await wxSet(${JSON.stringify(to)},false);
  ${flip}; const t1=performance.now(); let ok=false; while(performance.now()-t1<3000){ if(${oldG}.getAttribute('display')==='none'&&+${newG}.getAttribute('opacity')>.9){ ok=true; break; } await wxSleep(20); }
  return [ok, Math.round(performance.now()-t1)]`);
for (const [name, args] of [["rain → snow", [{ kind: "rain" }, { kind: "snow" }, "while(!sitOn.snow) await wxSleep(20)", "WX.rain.g", "WX.snow.g"]],
  ["day → night", [{ kind: "clear" }, { kind: "clear", day: false }, "await wxSleep(0)", "WX.sun.g", "WX.moon.g"]]]) {
  const [ok, ms] = await fade(...args);
  check(`cross-fade ${name}`, ok && ms <= 1000, `${ms} ms`);
}

// reduced motion: every attribute in #wx is the same across two frames 200 ms apart, with 3 particles
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
await send("Page.reload"); await sleep(4500); await ev(INIT);
check("reduced motion is on", await ev("return REDUCED.matches"));
for (const [name, o] of [["rain", { kind: "rain" }], ["heavy rain", { kind: "rain", heavy: true }], ["snow", { kind: "snow" }], ["clear night", { kind: "clear", day: false }],
  ["partly", { kind: "partly" }], ["cloudy", { kind: "cloudy" }], ["windy clear", { kind: "clear", windy: true, lean: 1 }], ["rain, party hat", { kind: "rain", party: true }]]) {
  await ev(`await wxSet(${JSON.stringify(o)}); return 1`);
  const a = await ev("return wxSnap()"); await sleep(200); const b = await ev("return wxSnap()");
  const n = o.kind === "rain" ? await ev("return WX.rain.drops.filter(d=>d.getAttribute('display')!=='none').length") : o.kind === "snow" ? await ev("return WX.snow.flakes.filter(d=>d.getAttribute('display')!=='none').length") : 3;
  check(`reduced motion holds still: ${name}`, a === b && n === 3, `${a.length} chars, ${n} particles`);
}

await ev("clearInterval(__hold); WXT=null; lowFx=false; return 1");
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall good");
process.exit(fails.length ? 1 : 0);
