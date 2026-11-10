// Pins one thing on stage (#227): the focus, the painters that obey it, the agent terminal, Nixi at work.
//   node tests/stage_focus_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
const [port, url] = process.argv.slice(2);
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
const errors = [];
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map(a => a.value || a.description).join(" ")); });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 820, height: 620, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4000);

const fails = [];
const check = (ok, what, got) => { if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + JSON.stringify(got)}`); } };
const eq = (got, want, what) => check(JSON.stringify(got) === JSON.stringify(want), what, got);

await ev(`
  window.__say=[]; sfx=n=>{}; enqueue=(t,o)=>window.__say.push(t);
  nixiIdleScale(1000); const f0=window.fetch.bind(window); window.fetch0=f0;   // keep the flags the test turned on across /api/state re-reads
  window.fetch=async(u,o)=>{ if(/\\/api\\/notify\\/seen/.test(String(u))) return new Response('{}'); const r=await f0(u,o); if(!/\\/api\\/state/.test(String(u))) return r; const j=await r.json(); return new Response(JSON.stringify({...j,proactive:true,reactions:true,look_meeting:true,look_weather:true,look_music:true,look_coding:true,click_through:true})); };
  window.sit=o=>onEvent({t:'situation',...Object.fromEntries(Object.entries(SIT).filter(([k])=>k!=='weather')),weather:SIT.weather,...o});
  Object.assign(info,{proactive:true,reactions:true,look_music:true,look_weather:true,look_coding:true});
  return 1;`);
await sleep(300);
const settle = () => ev(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,60)); return 1;`);
await settle();

// ---- checks are added step by step (plan/2026-11-10-227-stage-focus.md) ----
eq(await ev(`return document.body.dataset.focus;`), "ambient", "ambient at rest");
await ev(`onEvent({t:'notify',key:'t1',category:'other',app:'x',summary:'hi'}); return 1;`);
await settle();
eq(await ev(`return document.body.dataset.focus;`), "event", "notification holds event focus");
await sleep(6000); await settle();
eq(await ev(`return document.body.dataset.focus;`), "ambient", "notification focus expires");
await ev(`onEvent({t:'approve',id:'focus-a1',agent:'codex',tool:'Bash',detail:'true',confirm:'click',always:false}); return 1;`);
await settle();
eq(await ev(`return [apEl.classList.contains('on'),document.body.dataset.focus];`), [true,"answer"], "approval card takes answer focus");
await ev(`approvalGone('focus-a1'); return 1;`); await settle();
eq(await ev(`return document.body.dataset.focus;`), "ambient", "focus returns after approval closes");

await ev(`sit({music:true}); return 1;`); await sleep(3600); await settle();
const music = await ev(`return {focus:document.body.dataset.focus, art:!!$('#rxFront .bx'), other:!!$('#rxFront .tv'), classes:[...$('#stage').classList].filter(c=>c.startsWith('r-')), chip:!$('#musChip').hidden};`);
check(music.focus==='media'&&music.art&&!music.other&&JSON.stringify(music.classes)==='["r-music"]'&&music.chip, "media focus paints only music art", music);

const workRain = await ev(`window.__oldWorking=CP.working; CP.working=()=>true; rxEnd(); focusSync(performance.now()); RX_AT.rain=0;
  const played=rxPlay('rain'); return {played,focus:document.body.dataset.focus,rain:!!$('#rxFront .rain'),classes:[...$('#stage').classList].filter(c=>c.startsWith('r-'))};`);
check(workRain.played&&workRain.focus==='work'&&!workRain.rain&&!workRain.classes.includes('r-rain'), "rain reaction stays unpainted during work", workRain);
await ev(`sit({coding:true}); sitOn.rain=true; return 1;`); await sleep(3600); await settle();
const workLook = await ev(`return {focus:document.body.dataset.focus, glasses:+SIT_P.gl.getAttribute('opacity'), rain:WX.rain.g.getAttribute('display')};`);
check(workLook.focus==='work'&&workLook.glasses<.01&&workLook.rain==='none', "work focus fades glasses and weather marks", workLook);
await ev(`CP.working=window.__oldWorking; sitOn.rain=false; sitOn.music=false; sitOn.coding=false; RXS.delete('music'); rxEnd(); focusSync(performance.now());
  notifyAt=0; if(notifyRow) notifyClear(); onEvent({t:'notify',key:'focus-mail',category:'mail',app:'thunderbird',summary:'Mail card',card:{runs:[],buttons:[]}}); return 1;`);
await settle();
const mail = await ev(`return {card:!!(notifyRow&&notifyRow.card&&notifyRow.span.isConnected),focus:document.body.dataset.focus,pop:$('#mailPop').classList.contains('on')};`);
check(mail.card&&mail.focus==='answer'&&!mail.pop, "mail card does not open the mail pop-out", mail);
const delayedMail = await ev(`mailPop({key:'focus-delayed',category:'mail',app:'thunderbird',summary:'Delayed mail'});
  await new Promise(r=>setTimeout(r,100)); return {pop:$('#mailPop').classList.contains('on'),want:popWant};`);
check(!delayedMail.pop&&JSON.stringify(delayedMail.want)==='[0,0]', "delayed mail pop-out yields to answer focus", delayedMail);
eq(errors, [], "no console errors");

await ev(`window.fetch=window.fetch0; return 1;`);
if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("stage focus fit ok");
process.exit(0);
