// Agent summaries (#191): the page queue, strict sentences, stopping, captions.
//   node tests/agent_voice_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). Exit 0 = pass.
const [port, url] = process.argv.slice(2);
const [base, hash = ""] = url.split("#");
const nativeUrl = `${base}${base.includes("?") ? "&" : "?"}native=1${hash ? "#" + hash : ""}`;
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
const view = (w, h = 460, sw = 1920, sh = 1080) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, screenWidth: sw, screenHeight: sh, deviceScaleFactor: 1, mobile: false });
await send("Page.enable"); await send("Runtime.enable");
const exc = new Set(); ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.method === "Runtime.exceptionThrown") exc.add(m.params.exceptionDetails.exception?.description?.split("\n").slice(0, 2).join(" | ")); });

await view(340, 460);
await send("Page.navigate", { url: nativeUrl }); await sleep(4500);
await ev(`setInterval(()=>{ nextFidAt=1e15; info.voice_native=!!window.__native; info.tts=true; },50); await post('/api/settings',{idle_mode:'off'}); if(window.setIdle) setIdle('full');
  window.__calls=[]; window.__sfx=0; window.__tick=0; window.__native=true; window.__go=true; window.__autoend=true;
  const of=window.fetch;
  window.fetch=(u,o)=>{ const p=String(u).split('?')[0];
    if(['/api/say','/api/tts','/api/stop','/api/listen','/api/say/stop','/api/agent-say/check'].includes(p)){ __calls.push([p,o&&o.body?JSON.parse(o.body):null]);
      if(p==='/api/agent-say/check') return Promise.resolve(new Response(JSON.stringify({go:window.__go}),{status:200}));
      if(p==='/api/tts') return window.__autoend?Promise.resolve(new Response(null,{status:204})):new Promise(()=>{});   // (never answers: a stuck sentence)
      return Promise.resolve(new Response('{"ok":true}',{status:200})); }
    return of(u,o); };
  const s0=sfx, t0=tick; sfx=(...a)=>{ __sfx++; return s0(...a); }; tick=(...a)=>{ __tick++; return t0(...a); };
  setInterval(()=>{ if(window.__autoend) for(const id of [...spkMap.keys()]) onEvent({t:'spk_done',id}); },40);
  return 1`);
const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const calls = async (...p) => (await ev("return __calls.slice()")).filter(c => !p.length || p.includes(c[0]));
const reset = async (native = true) => { await ev(`agentStop(); agentLog.length=0; busy=false; muted=false; hiddenNow=false; AGENT_GUARD=30000; AGENT_STALE=120000; __native=${native}; __go=true; __autoend=true; __calls.length=0; __sfx=0; __tick=0; return 1`); await sleep(120); await ev("__calls.length=0; return 1"); };
let n = 0;
const say = (text, turn = "ab12cd34-" + (++n), from = "claude") => ev(`onEvent({t:'agent_say',from:${JSON.stringify(from)},name:'proj',turn:${JSON.stringify(turn)},text:${JSON.stringify(text)},kind:'short'}); return 1`);
const waitFor = async (js, ms = 4000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await ev(`return !!(${js})`)) return true; await sleep(60); } return false; };
const idle = () => waitFor("!agentCur&&!agentQ.length&&!playing");
const ls = () => ev("return JSON.stringify([localStorage,sessionStorage].map(s=>Object.keys(s).sort().map(k=>k+'='+s.getItem(k))))");

for (const native of [true, false]) {
  const mode = native ? "native" : "page", ep = native ? "/api/say" : "/api/tts";

  // 1. a summary is spoken sentence by sentence, strict, no follow window, one check each, no chime, nothing stored
  { await reset(native); const l0 = await ls();
    await say("First one. Second one."); await idle();
    const sp = await calls(ep), ck = await calls("/api/agent-say/check");
    check(sp.length === 2 && sp.every(c => c[1].strict === true) && sp[0][1].text === "First one." && sp[1][1].text === "Second one." && (!native || sp.every(c => c[1].follow === false)),
      `${mode}: each sentence is sent strict`, JSON.stringify(sp));
    check(ck.length === 2, `${mode}: a check before every sentence`, String(ck.length));
    check((await ev("return [__sfx,__tick]")).join() === "0,0", `${mode}: no chime and no tick`);
    check(await ls() === l0 && (await ev("return agentLog.length")) === 1, `${mode}: nothing stored, one replay entry`);
  }

  // 2. check says stop: nothing spoken, the rest of that summary dropped, the next summary still gets its check
  { await reset(native); await ev("__go=false; return 1");
    await say("Never said. Nor this."); await idle();
    check((await calls(ep)).length === 0 && (await calls("/api/agent-say/check")).length === 1, `${mode}: a stop from check drops the summary`);
    check((await ev("return agentLog.length")) === 1, `${mode}: ...which stays in replay`);
  }

  // 3. muted: caption, no speech and no check
  { await reset(native); await ev("muted=true; return 1");
    await say("Shown only."); await idle();
    check((await calls()).length === 0 && (await ev("return himEl.textContent")).includes("Shown only"), `${mode}: muted shows the caption and says nothing`);
    await ev("muted=false; return 1");
  }

  // 4. hidden: queue dropped, silent
  { await reset(native); await ev("hiddenNow=true; return 1");
    await say("Hidden one."); await sleep(700);
    check((await calls()).length === 0 && (await ev("return agentQ.length+(agentCur?1:0)")) === 0, `${mode}: hidden drops the queue silently`);
    await ev("hiddenNow=false; return 1");
  }

  // 5. busy: waits, then speaks. A 4th summary pushes out the oldest, which stays in replay only
  { await reset(native); await ev("busy=true; return 1");
    for (const w of ["Alpha.", "Bravo.", "Charlie.", "Delta."]) await say(w);
    await sleep(500);
    const w = await ev("return [agentQ.length, agentLog.length, __calls.length]");
    check(w.join() === "3,4,0", `${mode}: busy waits; the 4th keeps 3 queued, 4 in replay`, w.join());
    await ev("busy=false; return 1"); await idle();
    const sp = (await calls(ep)).map(c => c[1].text);
    check(sp.join() === "Bravo.,Charlie.,Delta.", `${mode}: spoken in order without the oldest`, sp.join());
  }

  // 6. 120 s unstarted goes to replay only (shortened)
  { await reset(native); await ev("busy=true; AGENT_STALE=250; return 1");
    await say("Too late."); await sleep(700); await ev("busy=false; return 1"); await sleep(600);
    check((await calls()).length === 0 && (await ev("return agentLog.length")) === 1, `${mode}: a stale summary is replay only`);
  }

  // 7. the 30 s guard (shortened): a sentence that never ends is cut and given up
  { await reset(native); await ev("__autoend=false; AGENT_GUARD=400; return 1");
    await say("Stuck one. Never reached."); await waitFor("playing", 2000);
    const ok = await waitFor("!agentCur&&!playing", 4000); await sleep(300);
    const sp = await calls(ep);
    check(ok && sp.length === 1, `${mode}: the guard stops a stuck summary`, JSON.stringify(sp));
    await ev("__autoend=true; return 1");
  }

  // 8. click, Space and Esc stop only the speech: no /api/stop, no recording
  for (const [name, fire] of [["click", "E.body.dispatchEvent(new MouseEvent('click',{bubbles:true}))"],
      ["Space", "dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true}))"],
      ["Esc", "dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"]]) {
    await reset(native); await ev("__autoend=false; return 1");
    await say("Long one. Another."); await waitFor("agentCur&&playing", 3000);
    await ev(`${fire}; return 1`); await sleep(500);
    const st = await ev("return [!!agentCur, agentQ.length, !!rec, playing]");
    const bad = await calls("/api/stop", "/api/listen");
    check(st.join() === "false,0,false,false" && bad.length === 0, `${mode}: ${name} stops only the speech`, JSON.stringify([st, bad]));
    await ev("dispatchEvent(new KeyboardEvent('keyup',{code:'Space',bubbles:true})); __autoend=true; return 1");
  }

  // 9. something you start yourself ends it
  { await reset(native); await ev("__autoend=false; return 1");
    await say("Talking. More."); await waitFor("agentCur&&playing", 3000);
    await ev("input.value=''; ask.dispatchEvent(new Event('submit',{cancelable:true})); return 1"); await sleep(300);
    check((await ev("return !agentCur&&!agentQ.length&&!playing")), `${mode}: sending a message ends the summary`);
    await ev("__autoend=true; return 1");
  }
}

// 10. a reload clears the queue and the replay
{ await reset(true); await ev("busy=true; return 1"); await say("Gone after reload.");
  await send("Page.reload"); await sleep(4500);
  check((await ev("return agentLog.length+agentQ.length")) === 0, "a reload clears the queue and the replay");
}

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
