// README pictures (#133): the six characters, a WhatsApp chat card and the call handset, with made-up data.
//   node docs/media/capture.mjs <cdp-port> <page-url> <out-dir>      (docs/media/capture.py starts both)
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138).
import { writeFileSync } from "node:fs";
const [port, url0, out] = process.argv.slice(2);
const url = url0.replace("/#", "/?native=1#");     // native: the page asks the window for room beside him
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
const view = (w, h = 460) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 2, mobile: false });
const need = (ok, what) => { if (!ok) { console.error(`${what}: not drawn as expected, nothing saved`); process.exit(1); } };
const shot = async (name, h) => { const w = await ev("return innerWidth");   // h: crop the empty floor under him
  const r = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: w, height: h, scale: 1 } }); writeFileSync(`${out}/${name}.png`, Buffer.from(r.result.data, "base64")); console.log("wrote", name); };

await send("Page.enable"); await view(340);
await send("Page.navigate", { url }); await sleep(4500);
await ev("setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}); return 1");
await ev("clearTimeout(chipT); chip.className=''; return 1");   // the "no voice engine" chip: a throwaway home has none

for (const c of ["snowflake", "terminal", "robot", "devil", "einstein", "skull"]) {
  await ev(`setCharacter(${JSON.stringify(c)}); nextBlink=performance.now()+1e9; blinkAt=-1e9; return 1`);   // eyes open
  await sleep(2500); await shot(`char-${c}`, 320);
}
await ev("setCharacter('snowflake'); return 1");

// the wa_thread fixture from tests/stages_fit.mjs, made-up names
const wa = { t: "stage", v: 1, kind: "wa_thread", card: "wc_thread", title: "WhatsApp", is_group: false, reply: "r", file: "f", summary: "s", suggest: "g",
  messages: [
    { from_me: false, sender_name: "Clara Example", at: "14:18", text: "Are we still on for lunch?", kind: "text" },
    { from_me: true, sender_name: "Me", at: "14:19", text: "Yes! 12:30 at the usual place", kind: "text" },
    { from_me: false, sender_name: "Clara Example", at: "14:20", text: "", kind: "voice message", download: "d1" },
    { from_me: false, sender_name: "Clara Example", at: "14:21", text: "", kind: "document", caption: "The menu", file_name: "menu.pdf", size: 48200, download: "d2" },
  ].reverse() };                                   // the bridge sends newest first
await ev(`stageClose(); await new Promise(r=>setTimeout(r,320)); onEvent(${JSON.stringify(wa)}); return 1`); await sleep(60);
let want = await ev("return stageWant[0]");
await view(340 + want); await ev("window.nixiLayout(0,0); return 1"); await sleep(700);
need(await ev(`const r=document.getElementById('stg').getBoundingClientRect();
  return stgState==='open' && r.left>=0 && r.top>=0 && r.right<=innerWidth && r.bottom<=400 && document.getElementById('stg').textContent.includes('usual place')`), "whatsapp card");
await shot("whatsapp", 400);

await ev("stageClose(); await new Promise(r=>setTimeout(r,400)); return 1"); await view(340); await sleep(300);
// the "host ringing" handset from tests/handset_fit.mjs
const call = { t: "call", id: "c1", gen: 1, phase: "ringing", path: "host", who: "Ada Lovelace", number: null, answered_at: null, audio_here: false, muted: false, volume: null, keys: ["answer", "reject"], note: "" };
await ev(`onEvent(${JSON.stringify(call)}); return 1`); await sleep(80);
want = await ev("return callWant[0]");
await view(340 + want); await ev("window.nixiLayout(0,0); return 1"); await sleep(500);
need(await ev(`const h=document.getElementById('handset'), r=h.getBoundingClientRect();
  return getComputedStyle(h).display!=='none' && r.width>0 && r.left>=0 && r.top>=0 && r.right<=innerWidth && r.bottom<=320 && h.textContent.includes('Ada Lovelace')`), "handset");
await shot("handset", 320);
process.exit(0);
