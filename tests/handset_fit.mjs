// The call handset (#115): phases and paths, keys, the POST, keyboard, focus ring, reduced motion, fit, hover region, bar pill, calm.
//   node tests/handset_fit.mjs <cdp-port> <page-url>      (HANDSET_SHOTS=<dir> also saves screenshots)
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). The window is simulated like tests/stages_fit.mjs: the page asks for callWant[0]
// extra width, the viewport becomes 340+want and nixiLayout says how far Nixi moved. Exit 0 = pass.
const [port, url0] = process.argv.slice(2);
const url = url0.replace("/#", "/?native=1#");     // NATIVE is a const set on load
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
const view = (w, h = 460) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
const key = async (k, code, vk, text) => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: k, code, windowsVirtualKeyCode: vk, ...(type === "keyDown" && text ? { text } : {}) }); };
await send("Page.enable"); await send("Emulation.setFocusEmulationEnabled", { enabled: true });
await send("Page.addScriptToEvaluateOnNewDocument", { source: `window.__m=[]; window.webkit={messageHandlers:{nixiui:{postMessage:m=>window.__m.push(String(m))}}};` });
await view(340);
await send("Page.navigate", { url }); await sleep(4500);
await ev(`setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); window.__calls=[]; window.__reply={ok:true};
  const f=window.fetch; window.fetch=(u,o)=>String(u).includes('/api/call')?(window.__calls.push(JSON.parse(o.body)),Promise.resolve(new Response(JSON.stringify(window.__reply)))):f(u,o); return 1`);

const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const long = "x".repeat(60);
const base = { t: "call", id: "c1", gen: 1, phase: "ringing", path: "host", who: "Ada Lovelace", number: null, answered_at: null, audio_here: false, muted: false, volume: null, keys: ["answer", "reject"], note: "" };
const FIX = {
  "host ringing": base,
  "host ringing (number)": { ...base, who: null, number: "+4791234567" },
  "host ringing (long name)": { ...base, who: long + " " + long },
  "host dialing": { ...base, phase: "dialing", label: "mobile", keys: ["hangup"] },
  "host active": { ...base, phase: "active", answered_at: Date.now() / 1000 - 75, audio_here: true, volume: 0.6, keys: ["hangup", "mute", "vol_up", "vol_down"] },
  "host active (muted, long)": { ...base, phase: "active", who: long, answered_at: Date.now() / 1000 - 4000, audio_here: true, muted: true, volume: 1.2, keys: ["hangup", "mute", "vol_up", "vol_down"] },
  "phone ringing": { ...base, path: "phone", keys: ["answer", "reject"] },
  "phone active (on phone)": { ...base, phase: "active", path: "phone", answered_at: Date.now() / 1000 - 5, keys: [], note: "On phone" },
  "watch ringing": { ...base, path: "watch", keys: [], note: "Ringing on " + long },
  "second call": { ...base, phase: "active", answered_at: Date.now() / 1000 - 5, keys: [], note: "Second call: use your phone " + long },
  "failed": { ...base, keys: [], note: "Didn't work. Use your phone" },
  "ended": { ...base, phase: "ended", keys: [], note: "Call ended" },
};
const ACTS = ["answer", "reject", "hangup", "mute", "vol_up", "vol_down"];
const show = async (fx, ox = () => 0) => {
  await ev(`onEvent(${JSON.stringify(fx)}); return 1`); await sleep(60);
  const want = await ev("return callWant[0]");
  await view(340 + want); await ev(`window.nixiLayout(${ox(want)},0); return 1`); await sleep(500);
  return want;
};
const state = () => ev(`const h=document.getElementById('handset'), r=h.getBoundingClientRect(), l=document.getElementById('hsLcd');
  return { box:[r.left,r.top,r.right,r.bottom,innerWidth,innerHeight], on:h.classList.contains('on'), disp:getComputedStyle(h).display,
    en:[...h.querySelectorAll('button')].filter(b=>!b.disabled&&getComputedStyle(b).display!=='none').map(b=>b.dataset.act), labels:[...h.querySelectorAll('button')].every(b=>b.getAttribute('aria-label')),
    lcd:l.innerText, clipped:l.scrollHeight>l.clientHeight+1||[...l.children].some(c=>c.getBoundingClientRect().bottom>l.getBoundingClientRect().bottom+1), dbg:[l.scrollHeight,l.clientHeight,...[...l.children].map(c=>Math.round(c.getBoundingClientRect().height))].join(), ring:h.classList.contains('ring') }`);

// every phase and path, at the three spots Nixi can be in the window: only the server's keys are enabled, nothing is clipped, the window is clear of him
const POS = { "Nixi at the left edge": w => 0, "Nixi in the middle": w => w / 2, "Nixi at the right edge": w => w };
for (const [pn, ox] of Object.entries(POS)) for (const [fn, fx] of Object.entries(FIX)) {
  const want = await show(fx, ox), s = await state(), [l, tp, r, b, W, H] = s.box, strip = [ox(want), ox(want) + 340];
  const inside = l >= 0 && r <= W && tp >= 0 && b <= H, clear = r <= strip[0] || l >= strip[1];
  check(want > 0 && s.on && inside && clear, `${fn} / ${pn}`, `box ${[l, tp, r, b].map(v => v.toFixed(0))} in ${W}x${H}, Nixi ${strip}`);
  if (pn === "Nixi in the middle") {
    check(JSON.stringify(s.en.sort()) === JSON.stringify([...fx.keys].sort()) || (fx.phase === "active" && fx.keys.length === 0 && s.en.length === 0), `${fn}: only the keys sent are enabled`, s.en.join());
    check(s.labels && !s.clipped, `${fn}: labelled and not clipped`, s.lcd.replace(/\n/g, "|")+" "+s.dbg);
    check(s.ring === (fx.phase === "ringing"), `${fn}: rings only while ringing`);
  }
}
{ await show(FIX["host ringing"]); const s = await state();
  check(/Ada Lovelace/i.test(s.lcd) && /Ringing/i.test(s.lcd), "ringing LCD shows the name and Ringing", s.lcd.replace(/\n/g, "|"));
  await show({ ...FIX["host dialing"], answered_at: Date.now() / 1000 - 30 }); const d = await state();
  const dl = await ev("return [document.getElementById('hsWho').textContent, document.getElementById('hsSt').textContent, document.getElementById('hsTm').textContent, document.getElementById('pillTxt').textContent, !document.getElementById('hsIc').innerHTML.includes('3.2') && document.getElementById('hsIc').innerHTML.includes('<path')]");
  check(dl[0] === "Ada Lovelace \u00b7 mobile" && dl[1] === "Calling\u2026" && dl[2] === "" && dl[3] === "Ada Lovelace \u00b7 mobile" && dl[4] && !d.ring && d.en.join() === "hangup", "dialing shows who \u00b7 label in display and pill, Calling\u2026, phone icon, hangup only, and no clock", JSON.stringify(dl));
  await show(FIX["host active"]); const a = await state();
  check(/01:\d\d/.test(a.lcd) && /In call/i.test(a.lcd), "active LCD shows the timer from answered_at", a.lcd.replace(/\n/g, "|"));
  check(await ev("return document.querySelectorAll('#hsVol i.f').length===5"), "volume bar shows 0.6 as 5 of 8");
  await show(FIX["host active (muted, long)"]);
  check(await ev("return getComputedStyle(document.querySelector('#hsLcd .mu')).display!=='none' && document.querySelector('.k-mute').getAttribute('aria-pressed')==='true'"), "muted shows on the LCD and the key");
  await show(FIX["host ringing (number)"]); check(/4791234567/.test((await state()).lcd), "a number shows when there is no name"); }

// the POST: the body is {id, gen, act}; a click, Enter and Space all send it
{ await show({ ...base, id: "zz", gen: 7 });
  await ev("window.__calls.length=0; document.querySelector('#handset .k-answer').click(); return 1"); await sleep(150);
  let c = await ev("return window.__calls"); check(c.length === 1 && JSON.stringify(c[0]) === JSON.stringify({ id: "zz", gen: 7, act: "answer" }), "a click POSTs {id, gen, act}", JSON.stringify(c));
  await key("Tab", "Tab", 9);
  await ev("window.__calls.length=0; document.querySelector('#handset .k-reject').focus(); return 1");
  await key("Enter", "Enter", 13, "\r"); await sleep(150);
  c = await ev("return window.__calls"); check(c.length === 1 && c[0].act === "reject", "Enter on a focused key POSTs", JSON.stringify(c));
  await ev("window.__calls.length=0; document.querySelector('#handset .k-answer').focus(); return 1");
  await key(" ", "Space", 32, " "); await sleep(150);
  c = await ev("return window.__calls"); check(c.length === 1 && c[0].act === "answer", "Space on a focused key POSTs", JSON.stringify(c));
  await ev("window.__reply={ok:false,stale:true}; window.__calls.length=0; document.querySelector('#handset .k-answer').click(); return 1"); await sleep(200);
  check(await ev("return !document.querySelector('#handset .k-answer').disabled && document.getElementById('handset').classList.contains('on')"), "a stale reply draws the handset again");
  await ev("window.__reply={ok:false,busy:true}; document.querySelector('#handset .k-answer').click(); return 1"); await sleep(200);
  check(await ev("return !document.querySelector('#handset .k-answer').disabled"), "a busy reply draws the handset again");
  await ev("window.__reply={ok:true}; return 1");
  await ev("window.__shortcut=0; addEventListener('keydown',()=>window.__shortcut++); document.querySelector('#handset .k-answer').focus(); return 1");
  await key("Enter", "Enter", 13, "\r"); await sleep(100);
  check(await ev("return window.__shortcut===0"), "Enter on a key does not reach the window's shortcuts");
  // the focus ring after keyboard use
  await ev("document.querySelector('#handset .k-answer').focus(); return 1");
  const fr = await ev("const cs=getComputedStyle(document.querySelector('#handset .k-answer')); return [cs.outlineStyle, parseFloat(cs.outlineWidth)]");
  check(fr[0] === "solid" && fr[1] >= 2, "a focused key has a visible ring", JSON.stringify(fr)); }

// motion: shake and blink while ringing; none under reduced motion, and a steady lit LCD reading Ringing
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] }); await sleep(150);
  await show(FIX["host ringing"]);
  const n = await ev("return document.getAnimations().filter(a=>a.animationName&&/^hs/.test(a.animationName)&&a.playState==='running').map(a=>a.animationName).sort()");
  check(n.includes("hsShake") && n.includes("hsBlink"), "ringing shakes and blinks", n.join());
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(250);
  await show(FIX["host ringing"]);
  const r = await ev("return [document.getAnimations().filter(a=>/^hs/.test(a.animationName||'')&&a.playState==='running').length, /Ringing/i.test(document.getElementById('hsLcd').innerText), getComputedStyle(document.getElementById('hsLcd')).animationName]");
  check(r[0] === 0 && r[1] && r[2] === "none", "reduced motion: nothing animates, the LCD reads Ringing", JSON.stringify(r));
  await send("Emulation.setEmulatedMedia", { features: [] }); await sleep(150); }

// zoom 1 and 1.5 (Nixi's size and the page zoom): still inside the window, clear of him
for (const z of [1, 1.5]) {
  await ev(`window.nixiZoom({page:${z},nk:${z}}); return 1`);
  for (const [pn, ox] of Object.entries(POS)) {
    const want = await show(FIX["host active"], ox), s = await state(), [l, tp, r, b, W, H] = s.box, strip = [ox(want), ox(want) + 340];
    check(l >= 0 && r <= W && tp >= 0 && b <= H && (r <= strip[0] || l >= strip[1]), `zoom ${z} / ${pn}`, `box ${[l, tp, r, b].map(v => v.toFixed(0))} in ${W}x${H}`);
  }
}
await ev("window.nixiZoom({page:1,nk:1}); return 1");

// the window: it grows for the handset and shrinks back; no idle shrink
{ await ev("onEvent({t:'call',phase:'gone'}); return 1"); await sleep(400);
  check(await ev("return callWant[0]===0 && !document.getElementById('handset').classList.contains('on')"), "gone: the handset leaves and the window need goes");
  const sizes = await ev("return window.__m.filter(m=>m.startsWith('size:')).slice(-1)"); check(sizes[0] === "size:0,0", "gone: the last size message is 0,0", sizes[0]);
  await show(FIX["host ringing"]);
  check(await ev("return idleActive()"), "idleActive while the handset shows");
  const sz = await ev("return window.__m.filter(m=>m.startsWith('size:')).slice(-1)[0]"); check(/^size:2\d\d,/.test(sz), "the size message asks for the handset's width", sz); }

// hover mode: shown and clickable; the region message holds its rect
{ await show(FIX["host ringing"]); await ev("document.body.classList.add('hover'); sendRegion(true); return 1"); await sleep(200);
  const h = await ev(`const r=document.getElementById('handset').getBoundingClientRect(), m=window.__m.filter(x=>x.startsWith('region:')).pop(), R=JSON.parse(m.slice(7));
    return { shown:r.width>0, R, inR:R.some(([x,y,w,hh])=>x<=r.left&&y<=r.top&&x+w>=r.right&&y+hh>=r.bottom) }`);
  check(h.shown && h.R.length > 0 && h.inR, "hover: the handset shows and the region holds its rect", JSON.stringify(h.R));
  await ev("onEvent({t:'call',phase:'gone'}); sendRegion(true); return 1"); await sleep(100);
  check(await ev("const m=window.__m.filter(x=>x.startsWith('region:')).pop(); return m==='region:[]'"), "hover: no call, the region is empty again");
  await ev("document.body.classList.remove('hover'); return 1"); }

// bar mode: a compact pill with the same keys, no handset
for (const edge of ["top", "bottom", "left", "right"]) {
  await ev(`document.body.classList.remove('calm','e-top','e-bottom','e-left','e-right'); document.body.classList.add('bar','e-${edge}'); onEvent(${JSON.stringify(FIX["host ringing"])}); HS.sync(); return 1`); await sleep(500);
  const p = await ev(`const p=document.getElementById('callPill'), r=p.getBoundingClientRect(), h=document.getElementById('handset');
    return { box:[r.left,r.top,r.right,r.bottom,innerWidth,innerHeight], en:[...p.querySelectorAll('button')].filter(b=>!b.disabled&&getComputedStyle(b).display!=='none').map(b=>b.dataset.act), txt:p.textContent, hs:getComputedStyle(h).display, want:callWant[0], tw:document.querySelector('#pillTxt').scrollWidth<=document.querySelector('#pillTxt').clientWidth+1 }`);
  const [l, tp, r, b, W, H] = p.box;
  check(l >= 0 && r <= W && tp >= 0 && b <= H && r - l > 100 && p.en.join() === "answer,reject" && p.hs === "none" && p.want === 0 && /Ada/.test(p.txt), `bar pill (${edge})`, `box ${[l, tp, r, b].map(v => v.toFixed(0))} keys ${p.en} want ${p.want}`);
  await ev("window.__calls.length=0; document.querySelector('#callPill .k-answer').click(); return 1"); await sleep(120);
  if (edge === "top") check(await ev("return window.__calls.length===1 && window.__calls[0].act==='answer'"), "bar pill: a key POSTs");
  await ev(`document.body.classList.remove('bar'); HS.sync(); return 1`);
}
{ await ev("document.body.classList.remove('bar','e-top','e-bottom','e-left','e-right'); return 1");
  // the region in bar mode holds the pill
  await ev("document.body.classList.add('bar','e-top'); sendRegion(true); return 1"); await sleep(150);
  check(await ev(`const r=document.getElementById('callPill').getBoundingClientRect(), R=JSON.parse(window.__m.filter(x=>x.startsWith('region:')).pop().slice(7)); return R.some(([x,y,w,h])=>x<=r.left&&y<=r.top&&x+w>=r.right&&y+h>=r.bottom)`), "bar: the region holds the pill");
  await ev("document.body.classList.remove('bar','e-top'); return 1"); }

// calm mode hides it; the window asks for nothing
{ await show(FIX["host ringing"]); await ev("setEl.classList.add('on'); calmCheck(); HS.sync(); return 1"); await sleep(200);   // (calm follows the open panels)
  check(await ev("return getComputedStyle(document.getElementById('handset')).display==='none' && getComputedStyle(document.getElementById('callPill')).display==='none' && callWant[0]===0"), "calm: hidden, no width asked for");
  await ev("setEl.classList.remove('on'); calmCheck(); HS.sync(); return 1"); await sleep(200);
  check(await ev("return getComputedStyle(document.getElementById('handset')).display!=='none' && callWant[0]>0"), "calm over: it is back"); }

// screenshots for the owner's look-over
if (process.env.HANDSET_SHOTS) {
  const dir = process.env.HANDSET_SHOTS, fs = await import("node:fs");
  await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 27, g: 34, b: 48, a: 1 } });
  const shot = async (name, w, h, clip) => { await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 3, mobile: false }); await sleep(300);
    const r = await send("Page.captureScreenshot", { format: "png", clip: { ...clip, scale: 1 } }); fs.writeFileSync(`${dir}/handset-${name}.png`, Buffer.from(r.result.data, "base64")); };
  const want = await show(FIX["host ringing"]); await ev("document.getAnimations().forEach(a=>{ if(a.animationName==='hsShake') a.pause(); }); return 1");
  await shot("ringing", 340 + want, 460, { x: 330, y: 0, width: 130, height: 300 });
  await show(FIX["host active"]); await shot("active", 340 + want, 460, { x: 330, y: 0, width: 130, height: 300 });
  await show({ ...FIX["host ringing"], who: "Ada Lovelace" }); await ev("document.body.classList.add('bar','e-top'); HS.sync(); return 1"); await sleep(500);
  await shot("bar-pill", 340, 460, { x: 0, y: 0, width: 340, height: 110 });
}

await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
