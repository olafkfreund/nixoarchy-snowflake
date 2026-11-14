// Who controls the desktop (#145): the ai-mirror marks, the revoke click, the menu item and the signals in every mode.
//   node tests/mirror_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). The server state is simulated by calling the page's own mirSet(); /api/mirror/off
// is a stubbed fetch, and /api/state (which the page polls) is made to say the same. Exit 0 = pass.
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
await send("Page.enable"); await send("Runtime.enable");
const exc = new Set(); ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.method === "Runtime.exceptionThrown") exc.add(m.params.exceptionDetails.exception?.description?.split("\n").slice(0,2).join(" | ")); });
await send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4500);
await ev("setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full'); return 1");
// the revoke is stubbed: window.__rev = {ok, calls}
await ev(`window.__rev={ok:true,calls:[]}; const f0=window.fetch.bind(window);
  window.fetch=(u,o)=>{ if(String(u).includes('/api/mirror/off')){ __rev.calls.push(String(u)); return Promise.resolve(new Response(JSON.stringify(__rev.ok?{ok:true}:{ok:false,error:'nope'}),{status:200})); } if(String(u).includes('/api/state')) return f0(u,o).then(async r=>{ const j=await r.json(); j.mirror=window.__mir; return new Response(JSON.stringify(j),{status:200}); });
    return f0(u,o); };
  window.MS=(o,w)=>{ window.__mir=o; mirSet(o); return new Promise(r=>setTimeout(r,w||700)); };
  window.opa=e=>+e.getAttribute('opacity');
  window.ins=e=>{ const r=e.getBoundingClientRect(); return r.left>=3&&r.top>=3&&r.right<=337&&r.bottom<=457&&r.width>0; };
  return 1`);

const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const run = async (name, js) => { const r = await ev(js); check(r.every(Boolean), name, r.join()); };

// idle timing first (no caption on screen yet): he stays up while an agent holds control, and idle still works after off
await ev("info.idle_mode='shrink'; nixiIdleScale(.01); idleHoldUntil=0; lastUser=0; return 1");
await ev("await MS({owner:'off',watching:false},1500); return 1");
check(await ev("const end=performance.now()+6000; while(!document.body.classList.contains('peek') && performance.now()<end) await new Promise(r=>setTimeout(r,100)); return document.body.classList.contains('peek')"), "idle shrinks after off (timing still works)");
await run("idleActive while pending and agent; not after off", `
  await MS({owner:'pending',watching:false},1500); const p=[idleActive(), !document.body.classList.contains('peek')];
  await MS({owner:'agent',watching:false},1500); const a=[idleActive(), !document.body.classList.contains('peek')];
  await MS({owner:'off',watching:false},1500); lastUser=0; idleHoldUntil=0; await new Promise(r=>setTimeout(r,1500));
  return [...p,...a,!idleActive()]`);
await ev("info.idle_mode='off'; nixiIdleScale(1); setIdle('full'); return 1");

// the marks sit inside the window, with the exact tooltip strings
for (const [k, o, txt] of [["pending", { owner: "pending", watching: false }, "An agent is asking to control your desktop"],
  ["agent", { owner: "agent", watching: false }, "An agent controls your desktop — click to take control back"],
  ["watching", { owner: "off", watching: true }, "ai-mirror read your screen recently"]]) {
  await run(`${k}: mark drawn inside the window, tooltip text`, `
    await MS(${JSON.stringify(o)},900); const r=[]; for(let i=0;i<12;i++){ r.push(ins(MX.mk)&&opa(MX.mk)>.5); await new Promise(x=>setTimeout(x,120)); }
    return [r.every(Boolean), MX.ttl.textContent==${JSON.stringify(txt)}, MX.mk.getAttribute('aria-label')===${JSON.stringify(txt)}, !MX.mk.getAttribute('aria-label').includes('is watching'),
      MX.mk.getAttribute('pointer-events')===${JSON.stringify(k === "agent" ? "all" : "none")}]`);
}
await ev("await MS({owner:'off',watching:false},800); return 1");

// moods: curious/scared once, then worried (never sleepy) while agent holds; looking for watching
await run("pending is curious; agent is scared, then worried and never sleepy", `
  const n=()=>performance.now(); await MS({owner:'pending',watching:false},200); const c=mood(n())==='curious';
  await MS({owner:'agent',watching:false},200); const sc=mood(n())==='scared';
  await new Promise(r=>setTimeout(r,1600)); lastActive=0; transient=null;
  const w=mood(n()); await new Promise(r=>setTimeout(r,200));
  return [c,sc,w==='worried',document.body.classList.contains('m-worried'),!document.body.classList.contains('m-sleepy'),!!MOODS.worried,!!AURA.worried,!'worried'.startsWith('t_'),!isTalk('worried')]`);
await run("watching is looking and silent", `
  await MS({owner:'off',watching:false},300); transient=null; const q=window.enqueue; let said=0; window.enqueue=(...a)=>{ said++; return q(...a); };
  await MS({owner:'off',watching:true},300); const m=mood(performance.now()); window.enqueue=q; return [m==='looking',said===0]`);

// the revoke click
await run("click posts /api/mirror/off; success fades the mark, happy, caption", `
  __rev.ok=true; __rev.calls=[]; await MS({owner:'agent',watching:false},900);
  MX.mk.dispatchEvent(new MouseEvent('click',{bubbles:true})); await new Promise(r=>setTimeout(r,300));
  const mid=mirV; const happy=mood(performance.now())==='happy'; const cap=(himEl.textContent||'').includes('Control is back with you.');
  await new Promise(r=>setTimeout(r,900));
  return [__rev.calls.length===1, __rev.calls[0].endsWith('/api/mirror/off'), MIR.owner==='off', happy, cap, mid<1, opa(MX.mk)===0, mirV===0]`);
await run("failure: error caption and the red mark stays", `
  __rev.ok=false; __rev.calls=[]; await MS({owner:'agent',watching:false},900);
  MX.mk.dispatchEvent(new MouseEvent('click',{bubbles:true})); await new Promise(r=>setTimeout(r,900));
  __rev.ok=true;
  return [__rev.calls.length===1, MIR.owner==='agent', opa(MX.mk)>.5, (himEl.textContent||'').includes("Couldn't take control back — press Super+Shift+Esc."), himEl.classList.contains('err')]`);
await run("pending caption", `
  await MS({owner:'off',watching:false},400); await MS({owner:'pending',watching:false},900);
  return [(himEl.textContent||'').includes("An agent is asking to control your desktop — answer in ai-mirror's dialog.")]`);

// the menu item only while it applies, in the orb and notch layouts
await run("menu: item only while pending or agent; arcs cover the visible buttons", `
  const vis=()=>[...document.querySelectorAll('#menu .mb')].filter(b=>getComputedStyle(b).display!=='none');
  const has=()=>vis().some(b=>b.dataset.a==='mirror'), out=[];
  await MS({owner:'off',watching:false},300); layoutMenu(); const n0=vis().length; out.push(!has(), MENU_XY.length===n0);
  await MS({owner:'agent',watching:false},300); layoutMenu(); out.push(has(), vis().length===n0+1, MENU_XY.length===n0+1);
  const xs=new Set(vis().map(b=>b.style.getPropertyValue('--x')+b.style.getPropertyValue('--y'))); out.push(xs.size===n0+1);
  document.body.classList.add('bar','e-top'); layoutMenu(); out.push(has(), MENU_XY.length===n0+1, new Set(vis().map(b=>b.style.getPropertyValue('--x')+b.style.getPropertyValue('--y'))).size===n0+1);
  await MS({owner:'off',watching:false},300); layoutMenu(); out.push(!has(), MENU_XY.length===n0);
  document.body.classList.remove('bar','e-top'); layoutMenu();
  await MS({owner:'pending',watching:false},300); layoutMenu(); out.push(has()); await MS({owner:'off',watching:false},300);
  return out`);
await run("menu item runs the revoke", `
  __rev.calls=[]; await MS({owner:'agent',watching:false},300); menu(true); await new Promise(r=>setTimeout(r,200));
  document.querySelector('#menu .mb[data-a="mirror"]').click(); await new Promise(r=>setTimeout(r,500));
  return [__rev.calls.length===1, !menuOn]`);

// notch: mark hidden, the pill glows red; hover: the ring; calm: the bar
await run("notch: mark hidden, pill border red", `
  await MS({owner:'agent',watching:false},900); document.body.classList.add('bar','e-top'); await new Promise(r=>setTimeout(r,800));
  const sh=getComputedStyle($('#barPill')).boxShadow, hid=opa(MX.mk)===0, cue=getComputedStyle(MX.mk).opacity;
  document.body.classList.remove('bar','e-top'); await new Promise(r=>setTimeout(r,800));
  return [hid, sh.includes('255, 59, 59'), opa(MX.mk)>.5]`);
await run("hover: red ring round him, mark hidden", `
  await MS({owner:'agent',watching:false},900); document.body.classList.add('hover'); const r=[];
  for(let i=0;i<10;i++){ await new Promise(x=>setTimeout(x,120)); r.push(+getComputedStyle(MX.hov).opacity>0); }
  const d=getComputedStyle(MX.hov).display, m=getComputedStyle(MX.mk).display, box=MX.hov.getBoundingClientRect();
  document.body.classList.remove('hover'); await MS({owner:'off',watching:false},800);
  return [r.some(Boolean), d!=='none', m==='none', true, opa(MX.hov)===0]`);
await run("calm: red bar on the open settings panel with its button; not when off", `
  await MS({owner:'agent',watching:false},600); settings(true); await new Promise(r=>setTimeout(r,900)); calmCheck();
  const b=$('#mirBar'), cs=getComputedStyle(b), r=b.getBoundingClientRect(), sr=setEl.getBoundingClientRect();
  const out=[document.body.classList.contains('calm'), cs.display!=='none', b.querySelector('span').textContent==='An agent controls your desktop', b.querySelector('button').textContent==='Take control back',
    Math.abs(r.left-sr.left)<2, r.bottom<=sr.top+31, r.top>=0];
  __rev.calls=[]; b.querySelector('button').click(); await new Promise(r=>setTimeout(r,500));
  out.push(__rev.calls.length===1, MIR.owner==='off'); calmCheck(); out.push(getComputedStyle(b).display==='none');
  settings(false); await new Promise(r=>setTimeout(r,500)); return out`);

// the tip: the mirror mark wins over AM and #cue; they come back when it goes off
await run("tip: AM and #cue yield while a mirror mark shows, and return after", `
  await MS({owner:'off',watching:false},400); AMB.cal={time:'10:00',title:'x'}; renderCue(); const cue=$('#cue');
  const c0=cue.getAttribute('display')==='';
  await MS({owner:'agent',watching:false},600); const c1=cue.getAttribute('display')==='none';
  await MS({owner:'off',watching:false},700); const c2=cue.getAttribute('display')==='';
  AMB.cal=null; renderCue();
  agentMark('claude','ask'); await new Promise(r=>setTimeout(r,1500)); const a0=opa(AMX.mk)>.5;
  await MS({owner:'agent',watching:false},1500); const a1=opa(AMX.mk)<.05, still=!!AM, ptr=AMX.mk.getAttribute('pointer-events')==='none';
  await MS({owner:'off',watching:false},1500); const a2=opa(AMX.mk)>.5;
  AM.until=0; await new Promise(r=>setTimeout(r,900));
  return [c0,c1,c2,a0,a1,still,ptr,a2]`);

// the server's state endpoint feeds the same function
check(await ev("mirSet(null); await new Promise(r=>setTimeout(r,500)); return MIR.owner===null&&mirKind()===''&&opa(MX.mk)===0"), "no ai-mirror: nothing shows");
check(await ev("mirSet({owner:'weird'}); return MIR.owner===null"), "an unknown owner shows nothing");

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall ok");
process.exit(fails.length ? 1 : 0);
