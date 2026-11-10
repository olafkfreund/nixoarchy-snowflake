// Pins one thing on stage (#227): the focus, the painters that obey it, the agent terminal, Nixi at work.
//   node tests/stage_focus_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
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
  nixiIdleScale(1000); const f0=window.fetch.bind(window); window.fetch0=f0;   // keep the flags the test turned on across /api/state re-reads
  window.fetch=async(u,o)=>{ const r=await f0(u,o); if(!/\\/api\\/state/.test(String(u))) return r; const j=await r.json(); return new Response(JSON.stringify({...j,proactive:true,reactions:true,look_meeting:true,look_weather:true,look_music:true,look_coding:true,click_through:true})); };
  window.sit=o=>onEvent({t:'situation',...Object.fromEntries(Object.entries(SIT).filter(([k])=>k!=='weather')),weather:SIT.weather,...o});
  return 1;`);
await sleep(300);
const settle = () => ev(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,60)); return 1;`);
await settle();

// ---- checks are added step by step (plan/2026-11-10-227-stage-focus.md) ----

await ev(`window.fetch=window.fetch0; return 1;`);
if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("stage focus fit ok");
process.exit(0);
