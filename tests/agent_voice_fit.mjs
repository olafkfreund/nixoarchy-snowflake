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
  window.__calls=[]; window.__sfx=0; window.__tick=0; window.__native=true; window.__go=true; window.__autoend=true; window.__chk=0;
  const of=window.fetch;
  window.fetch=(u,o)=>{ const p=String(u).split('?')[0];
    if(['/api/say','/api/tts','/api/stop','/api/listen','/api/say/stop','/api/agent-say/check','/api/agent-say/more'].includes(p)){ __calls.push([p,o&&o.body?JSON.parse(o.body):null]);
      if(p==='/api/agent-say/check') return new Promise(r=>setTimeout(()=>r(new Response(JSON.stringify({go:window.__go}),{status:200})),window.__chk));
      if(p==='/api/tts') return window.__autoend?Promise.resolve(new Response(null,{status:204})):new Promise(()=>{});   // (never answers: a stuck sentence)
      return Promise.resolve(new Response('{"ok":true}',{status:200})); }
    return of(u,o); };
  const s0=sfx, t0=tick; sfx=(...a)=>{ __sfx++; return s0(...a); }; tick=(...a)=>{ __tick++; return t0(...a); };
  setInterval(()=>{ if(window.__autoend) for(const id of [...spkMap.keys()]) onEvent({t:'spk_done',id}); },40);
  return 1`);
const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const calls = async (...p) => (await ev("return __calls.slice()")).filter(c => !p.length || p.includes(c[0]));
const reset = async (native = true) => { await ev(`agentStop(); agentLog.length=0; busy=false; muted=false; hiddenNow=false; AGENT_GUARD=30000; AGENT_STALE=120000; __native=${native}; __go=true; __autoend=true; __chk=0; __calls.length=0; __sfx=0; __tick=0; return 1`); await sleep(120); await ev("__calls.length=0; return 1"); };
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
    check(sp.length === 2 && !!sp[0][1].reply && sp[0][1].reply === sp[1][1].reply, `${mode}: one reply id for the whole summary`, JSON.stringify(sp.map(c => c[1].reply)));
    await say("Third one."); await idle();
    const sp2 = await calls(ep);
    check(sp2.length === 3 && sp2[2][1].reply !== sp2[0][1].reply, `${mode}: the next summary gets a new reply id`);
    check(await ls() === l0 && (await ev("return agentLog.length")) === 2, `${mode}: nothing stored, two replay entries`);
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

  // 9b. a sentence is split only at punctuation followed by a space
  { const sp = await ev(`return [agentSplit("Version 1.5 of server.py passed. Next one!"), agentSplit("No stop")]`);
    check(sp[0].join("|") === "Version 1.5 of server.py passed.|Next one!" && sp[1].join("|") === "No stop", `${mode}: a dot inside a word is no sentence end`, JSON.stringify(sp)); }

  // 9c. hover mode: the tick must not re-enter while he comes back, so sentence 0 is said once
  { await reset(native); await ev("window.__cb=comeBack; comeBack=async()=>{ await sleep(700); }; info.hover=true; return 1");
    await say("Hovering. Again."); await idle();
    const sp = (await calls(ep)).map(c => c[1].text);
    check(sp.join("|") === "Hovering.|Again.", `${mode}: hover mode says sentence 0 once`, sp.join("|"));
    await ev("comeBack=window.__cb; info.hover=false; return 1");
  }

  // 9d. something starts mid-summary (an approval, the mic) while the next check is out: the rest is dropped
  { await reset(native); await ev("__chk=600; return 1");
    await say("One here. Two there."); await waitFor("__calls.some(c=>c[0]==='"+ep+"')", 3000); await sleep(450);
    await ev("busy=true; return 1"); await sleep(1200);
    check((await calls(ep)).length === 1 && (await ev("return !agentCur")), `${mode}: busy after the check drops the rest of the summary`);
    await ev("busy=false; __chk=0; return 1");
  }

  // 9e. cut off by something that is not agentStop (a spoken question, a barge-in): the rest is dropped
  { await reset(native); await ev("__autoend=false; return 1");
    await say("Cut me. Never said."); await waitFor("agentCur&&playing", 3000);
    await ev("shush(); return 1"); await sleep(900);
    check((await calls(ep)).length === 1 && (await ev("return !agentCur&&!agentQ.length")), `${mode}: a cut-off ends the summary, it is not "finished"`);
    await ev("__autoend=true; return 1");
  }

  // 9f. typing into the ask box ends a running summary
  { await reset(native); await ev("__autoend=false; return 1");
    await say("Typing over. Me."); await waitFor("agentCur&&playing", 3000);
    await ev("dispatchEvent(new KeyboardEvent('keydown',{key:'a',bubbles:true})); return 1"); await sleep(300);
    check((await ev("return !agentCur&&!playing")), `${mode}: typing ends the summary`);
    await ev("hideAsk(); input.value=''; __autoend=true; return 1");
  }

  // 9g. a strict sentence that is skipped still shows its words
  { await reset(native); await ev("himSet(''); __autoend=false; return 1");
    await say("Words stay."); 
    if (native) { await waitFor("spkMap.size", 3000); await ev("for(const id of [...spkMap.keys()]) onEvent({t:'spk_skip',id}); return 1"); }
    else await ev("__autoend=true; return 1");
    const shown = await waitFor("(himEl.textContent+cap.textContent).includes('Words stay')", 3000);
    check(shown, `${mode}: a skipped strict sentence shows as a caption`, await ev("return himEl.textContent+'|'+cap.textContent"));
    await ev("__autoend=true; return 1");
  }
}

// 10. Settings -> Voice -> Agents row (#191 step 4): switches, live list, Replay with strict, More on newest only, long title fit at 420x420, and <b> stays text
{ await view(584, 726); await reset(true);
  await ev("settings(true,'voice'); return 1"); await sleep(200);
  const rowOk = await ev(`const r=document.getElementById('agentRow'), pv=document.getElementById('panel-voice');
    const sw=[...r.querySelectorAll('input[data-agent]')].map(x=>x.dataset.agent+':'+x.checked);
    return pv&&pv.contains(r)&&sw.join()==='claude:true,codex:true,agy:true'&&document.getElementById('agentList').textContent.length>0`);
  check(rowOk, "Settings -> Voice has #agentRow with claude/codex/agy switches", String(rowOk));

  // switches set agent_voice_mute via /api/settings
  const muteRes = await ev(`document.getElementById('agentCodexSw').click();
    await new Promise(r=>setTimeout(r,150));
    const m1=(info.agent_voice_mute||[]).slice();
    document.getElementById('agentAgySw').click();
    await new Promise(r=>setTimeout(r,150));
    const m2=(info.agent_voice_mute||[]).slice();
    document.getElementById('agentCodexSw').click();
    await new Promise(r=>setTimeout(r,150));
    document.getElementById('agentAgySw').click();
    await new Promise(r=>setTimeout(r,150));
    const m3=(info.agent_voice_mute||[]).slice();
    return {m1,m2,m3}`);
  check(muteRes.m1.join() === "codex" && muteRes.m2.join() === "codex,agy" && muteRes.m3.length === 0,
    "Agents switches update agent_voice_mute in settings", JSON.stringify(muteRes));

  // summaries arriving while Settings is open refresh #agentList; text/name with <b> stays literal text; More only on newest
  const longName = "very-long-workspace-folder-name-".repeat(3).slice(0, 80);
  await ev(`muted=true;
    onEvent({t:'agent_say',from:'claude',name:'<b>bold-name</b>',turn:'t1',text:'First <b>bold</b> summary.',kind:'short'});
    onEvent({t:'agent_say',from:'codex',name:${JSON.stringify(longName)},turn:'t2',text:'Second summary for replay.',kind:'short'});
    return 1`);
  const listSt = await ev(`const al=document.getElementById('agentList'), rows=[...al.querySelectorAll('.el-v')];
    const mores=al.querySelectorAll('[data-amore]'), replays=al.querySelectorAll('[data-areplay]');
    const firstMore=rows[0]?.querySelector('[data-amore]'), secondMore=rows[1]?.querySelector('[data-amore]');
    const hasBTag=!!al.querySelector('b');
    const texts=rows.map(r=>[r.querySelector('.ag-t')?.textContent, r.querySelector('.el-vt small')?.textContent]);
    return {count:rows.length, mores:mores.length, replays:replays.length, firstMore:!!firstMore, secondMore:!!secondMore, hasBTag, texts}`);
  check(listSt.count === 2 && listSt.replays === 2 && listSt.mores === 1 && listSt.firstMore && !listSt.secondMore,
    "live summary refresh shows newest first with Tell me more only on newest row", JSON.stringify(listSt));
  check(!listSt.hasBTag && listSt.texts[1][0].includes("<b>bold-name</b>") && listSt.texts[1][1] === "First <b>bold</b> summary.",
    "summary text and name with <b> stay literal text via textContent", JSON.stringify(listSt.texts));

  // Replay queues with strict (and follow:false, cap:true)
  await ev("agentQ.length=0; agentCur=null; muted=false; __calls.length=0; document.querySelector('#agentList [data-areplay]').click(); return 1");
  await idle();
  const repSp = await calls("/api/say");
  check(repSp.length === 1 && repSp[0][1].text === "Second summary for replay." && repSp[0][1].strict === true && repSp[0][1].follow === false,
    "Replay queues summary with strict:true and follow:false", JSON.stringify(repSp));

  // Replay goes through the queue (check, guard): click and Space stop only the speech, and never open the mic
  for (const [name, fire] of [["click", "E.body.dispatchEvent(new MouseEvent('click',{bubbles:true}))"],
      ["Space", "dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true}))"]]) {
    await ev("__autoend=false; agentStop(); __calls.length=0; document.querySelector('#agentList [data-areplay]').click(); return 1");
    const started = await waitFor("agentCur&&playing", 3000);
    const ck = await calls("/api/agent-say/check");
    await ev(`settings(false); ${fire}; return 1`); await sleep(500);
    const st = await ev("return [!!agentCur, agentQ.length, !!rec, playing]");
    const bad = await calls("/api/stop", "/api/listen");
    check(started && ck.length >= 1 && st.join() === "false,0,false,false" && bad.length === 0, `Replay: ${name} stops only the speech`, JSON.stringify([started, ck.length, st, bad]));
    await ev("dispatchEvent(new KeyboardEvent('keyup',{code:'Space',bubbles:true})); __autoend=true; settings(true,'voice'); return 1"); await sleep(200);
  }

  // More posts to /api/agent-say/more
  await ev("__calls.length=0; document.querySelector('#agentList [data-amore]').click(); return 1");
  await sleep(100);
  const moreCalls = await calls("/api/agent-say/more");
  check(moreCalls.length === 1 && moreCalls[0][1].turn === "t2", "Tell me more posts the newest turn to /api/agent-say/more", JSON.stringify(moreCalls));

  // Long title fits at the smallest Settings size (420x420 and 320x400 viewport)
  await ev("setResize(420,420); return 1"); await sleep(300);
  const fit420 = await ev(`const bd=setEl.querySelector('.bd'), ar=document.getElementById('agentRow'), pv=document.getElementById('panel-voice');
    const rows=[...document.querySelectorAll('#agentList .el-v')].map(e=>e.getBoundingClientRect());
    const t0=document.querySelector('#agentList .ag-t').getBoundingClientRect(), pvr=pv.getBoundingClientRect();
    return {w:setW, h:setH, noHScroll:bd.scrollWidth<=bd.clientWidth+1, titleFits:t0.right<=pvr.right+1&&t0.width>0,
      noOverlap:rows.every((b,i)=>i===0||b.top>=rows[i-1].bottom-1)}`);
  check(fit420.w === 420 && fit420.h === 420 && fit420.noHScroll && fit420.titleFits && fit420.noOverlap,
    "long title fits at smallest Settings size (420x420)", JSON.stringify(fit420));

  await ev("settings(false); localStorage.removeItem('nixi.setSize'); setW=0; setH=0; return 1");
  await view(340, 460);
}

// 10b. final-review fixes: a long sentence outlasts the guard; "stop" clears the queue; push-to-talk stops only the summary; muting partway prints nothing more
{ await reset(true);
  check((await ev("__autoend=false; AGENT_GUARD=300; return 1")) === 1, "guard setup");
  await say("x".repeat(40) + ". Next one.");
  await sleep(700);
  check((await ev("return !!agentCur&&playing")) === true, "the guard allows for a long sentence", "");
  await reset(true);
  await ev("__autoend=false; return 1"); await say("One here. Two here."); await say("Second summary.");
  await sleep(500);
  await ev("playing=true; onEvent({t:'barge',listen:false,text:''}); return 1"); await sleep(400);
  check((await ev("return [agentQ.length, !!agentCur]")).join() === "0,false", "saying stop clears the queue too", "");
  await reset(true);
  await ev("__autoend=false; return 1"); await say("One here. Two here."); await sleep(500);
  await ev("__calls.length=0; return 1");
  await ev("nixiCmd('ptt-down'); return 1"); await sleep(300);
  check((await calls("/api/stop")).length === 0 && (await ev("return agentCur===null")) === true, "push-to-talk stops only the summary, with no /api/stop", "");
  await ev("if(typeof stopRec==='function'&&rec) stopRec(true); return 1");
  await reset(true);
  await ev("__autoend=true; return 1"); await say("One here. Two here. Three here."); await waitFor("agentCur&&agentCur.i>=1");
  await ev("muted=true; himSet('held'); return 1"); await sleep(600);
  check((await ev("return [himEl.textContent.includes('Three here'), agentCur===null]")).join() === "false,true", "muting partway stops him without printing it all", "");
  await reset(true);
}

// 11. a reload clears the queue and the replay
{ await reset(true); await ev("busy=true; return 1"); await say("Gone after reload.");
  await send("Page.reload"); await sleep(4500);
  check((await ev("return agentLog.length+agentQ.length")) === 0, "a reload clears the queue and the replay");
}

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
