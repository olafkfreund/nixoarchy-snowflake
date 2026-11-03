// Every accessory must fit inside his 340×460 window: nothing may be cut off by the window's edge.
//   node tests/accessories_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). Turns each look / skin / prop / mark on in turn, waits for its spring to
// settle, samples its on-screen box while it sways, and fails if any part leaves the window. Exit 0 = all fit.
const [port, url] = process.argv.slice(2);
const MARGIN = 3, TOP = 3;                                // (SVG boxes leave out the stroke: keep a little room for it;
                                                          //  his own arms reach ~10 px from the top in every move)
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
await send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4500);
await ev("setInterval(()=>{ nextFidAt=1e15; },50); window.__hold=null; await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full'); return 1");   // (measure him full size: no idle peek)

// Settings → Plugins draws a hostile name and error as text, never as markup (#149)
if ((await ev(`plugRender({items:[{id:'x-1',name:'<b>x</b>',version:'<i>1</i>',source:'Folder',enabled:false,caps:['<u>caps</u>'],error:'<img src=x onerror=1>'}],error:'<s>e</s>'});
  const l=document.getElementById('plugList'); return [l.querySelector('b,i,u,img,s')!==null||document.querySelector('#plugErr s')!==null, l.textContent.includes('<b>x</b>'), l.textContent.includes('<img src=x onerror=1>')];`)).join() !== "false,true,true") {
  console.log("CUT  plugin names are not plain text"); process.exit(1);
}
await ev("plugRender({items:[]}); return 1");

// one case = how to turn it on, and which element(s) to measure
const LOOKS = { tie: "meeting", hb: "music", hf: "music", sh: "fullscreen", gl: "coding", nc: "night", ph: "party", um: "rain" };
const cases = [];
for (const [part, sit] of Object.entries(LOOKS)) cases.push({ name: `look ${sit} (${part})`, on: `
  clearInterval(__hold); for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; SIT.weather='';
  await new Promise(r=>setTimeout(r,8500));   // (a look lingers 8 s after it goes off: start each one from none)
  __hold=setInterval(()=>{ for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false;
    ${sit === "rain" ? "SIT.weather='rain'; info.look_weather=true;" : `SIT.${sit}=true; info.look_${sit}=true;`}
    info.look_beat=true; beat=1; beatAt=performance.now(); },60);`, wait: 5200, el: part === "gl" ? "SIT_P.lensL" : `SIT_P.${part}`, also: part === "gl" ? "SIT_P.lensR" : null });
for (const skin of ["halo", "crown", "sprout", "bow"]) cases.push({ name: `skin ${skin}`, on: `
  clearInterval(__hold); for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; applyLook({...LOOK, skin:'${skin}'});`,
  wait: 1500, el: "document.getElementById('accFront')", also: "document.getElementById('accBack')", after: "applyLook({...LOOK, skin:'none'});" });
// the example plugin hat (party-hat-plus) at each anchor, in front and behind; its colours must come from the page's variables
for (const anchor of ["head", "left", "right", "base"]) for (const layer of ["front", "back"]) cases.push({ name: `plugin hat ${anchor}/${layer}`, on: `
  clearInterval(__hold); for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false;
  Object.assign(info.plugin_props[0],{anchor:'${anchor}',layer:'${layer}'}); applyLook({...LOOK, skin:'plug:party-hat-plus'});
  if(!document.querySelector('#acc${layer === "front" ? "Front" : "Back"} path')) throw new Error('hat not drawn');
  if(getComputedStyle(document.querySelector('#acc${layer === "front" ? "Front" : "Back"} path')).fill==='rgb(0, 0, 0)') throw new Error('acc colour did not resolve');`,
  wait: 1500, el: "document.getElementById('accFront')", also: "document.getElementById('accBack')", after: "applyLook({...LOOK, skin:'none'});" });
for (const cat of ["chat", "video"]) cases.push({ name: `prop ${cat}`, on: `
  clearInterval(__hold); propOn={cat:'${cat}',t0:performance.now(),until:performance.now()+60000,n:3};`, wait: 1500,
  el: `SIT_P.${cat === "chat" ? "chat" : "feed"}.g`, after: "propOn=null;" });
cases.push({ name: "agent mark (ask)", on: "clearInterval(__hold); agentMark('claude','ask');", wait: 1500, el: "document.getElementById('agentMark')", after: "AM=null;" });
cases.push({ name: "cue dot (!)", on: "clearInterval(__hold); AM=null; attnPend={from:'x',at:performance.now()}; renderCue(); document.getElementById('cue').setAttribute('display','');", wait: 600, el: "document.getElementById('cue')", after: "attnPend=null; renderCue();" });
cases.push({ name: "thinking bubble", on: "clearInterval(__hold); poke('thinking',6000);", wait: 1500, el: "document.getElementById('think')" });
cases.push({ name: "question mark", on: "clearInterval(__hold); poke('confused',6000);", wait: 1500, el: "document.getElementById('qmark')" });
cases.push({ name: "mail pop-out", on: "clearInterval(__hold); mailPop({key:'k',app:'thunderbird',summary:'Invoice 42 is due Friday',category:'mail'});", wait: 1600,
  el: "document.getElementById('mailPop')", also: "document.querySelector('#mailPop .lt')", grow: 130, noBounce: true });   // (HTML, outside the bouncing SVG)   // (the window grows 130 px each side for it)

const box = expr => `(()=>{ const e=${expr}; if(!e) return null; const r=e.getBoundingClientRect(); return r.width&&r.height?[r.left,r.top,r.right,r.bottom]:null; })()`;
const fails = [];
for (const c of cases) {
  await ev(c.on + " return 1");
  await sleep(c.wait);
  let worst = null;
  // at rest while he sways, then through his biggest bounce ("happy": a camera punch-zoom and a tall jelly stretch)
  const sample = `const a=${box(c.el)}, b=${c.also ? box(c.also) : "null"}; return [a,b];`;
  const grow = b => { for (const r of b) if (r) worst = worst ? [Math.min(worst[0], r[0]), Math.min(worst[1], r[1]), Math.max(worst[2], r[2]), Math.max(worst[3], r[3])] : r; };
  for (let i = 0; i < 6; i++) { grow(await ev(sample)); await sleep(120); }
  // then through each of his biggest moves, one at a time (random fidgets are held off, so the result never depends on luck):
  // the "happy" punch-zoom and jelly bounce, a yawn (he stretches up from the bottom) and a roll (a full spin)
  const during = (start, ms) => ev(`${start}; const out=[]; const t0=performance.now();
    while(performance.now()-t0<${ms}){ const s=(()=>{${sample}})(); out.push(...s); await new Promise(r=>requestAnimationFrame(r)); } return out;`);
  if (!c.noBounce) {
    grow(await during("poke('happy',1500)", 1400)); await sleep(1200);
    for (const f of ["yawn", "roll"]) { grow(await during(`FID={name:'${f}',t0:performance.now(),dur:FIDGETS.${f}.dur}; FIDGETS.${f}.start&&FIDGETS.${f}.start(FID)`, 2600)); await ev("FID=null; return 1"); await sleep(600); }
  }
  const W = 340, H = 460, g = c.grow || 0, ok = worst && worst[0] >= MARGIN - g && worst[1] >= TOP && worst[2] <= W + g - MARGIN && worst[3] <= H - MARGIN;
  console.log(`${ok ? "ok  " : "CUT "} ${c.name.padEnd(26)} ${worst ? worst.map(v => v.toFixed(0)).join(",") : "not drawn"}`);
  if (!ok) fails.push(c.name);
  if (c.after) await ev(c.after + " return 1");
}
await ev("clearInterval(__hold); return 1");
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} cut off: ${fails.join(", ")}` : "\nall fit");
process.exit(fails.length ? 1 : 0);
