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
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map(a => a.value || a.description).join(" ")); });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 820, height: 620, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4000);

process.on("exit", () => errors.length && console.log("PAGE ERRORS", errors));
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
const wk = (from, name, project) => `onEvent({t:'attention',kind:'working',from:'${from}',name:'${name}',project:'${project}'});`;
await ev(`if(notifyRow) notifyClear(); $('#mailPop').classList.remove('on'); return 1;`); await settle();
await sleep(8000); await settle();   // (the mail card's event hold runs out)
await ev(wk("claude","Claude","p1") + wk("codex","Codex","p2") + "return 1;"); await settle();
const two = await ev(`return {n:CP.n(),focus:document.body.dataset.focus,on:$('#code').classList.contains('on'),rows:document.querySelectorAll('#code .lines .st').length};`);
check(two.n===2&&two.focus==='work'&&two.on&&two.rows===2, "two working agents: two entries, work focus, sheet on", two);
await ev(`onEvent({t:'attention',kind:'done',from:'codex',name:'Codex',project:'p2',text:''}); return 1;`); await settle();
eq(await ev(`return CP.n();`), 1, "done ends only that agent's entry");
await ev(`onEvent({t:'attention',kind:'ask',from:'claude',name:'Claude',project:'p1',text:'needs you'}); return 1;`); await settle();
eq(await ev(`return [CP.n(),$('#code').classList.contains('on'),sheetWant,AM&&AM.kind];`), [0,false,[0,0],'ask'], "ask ends the last entry: sheet off, window room released, the ask mark still shows");
await ev(wk("claude","Claude","p1") + wk("codex","Codex","p2") + wk("zed","Zed","p3") + "return 1;"); await sleep(3000); await settle();   // (the ask above holds the event focus for 2.5 s)
const look = await ev(`const c=$('#code'), B=document.body.classList, d=e=>getComputedStyle(c.querySelector(e)).display;
  const r={st:c.querySelectorAll('.lines .st').length,icons:c.querySelectorAll('.icons > *').length,ini:c.querySelector('.icons .ini')&&c.querySelector('.icons .ini').textContent,deco:d('.deco'),bg:getComputedStyle(c).backgroundColor,pe:getComputedStyle(c).pointerEvents};
  B.add('calm'); r.calm=getComputedStyle(c).display; B.remove('calm'); B.add('bar'); r.barDeco=d('.deco'); r.barIcons=d('.icons'); B.remove('bar'); return r;`);
check(look.st===3&&look.icons===3&&look.ini==='Z'&&look.deco!=='none'&&look.bg==='rgb(13, 17, 23)'&&look.pe==='none', "terminal: three status lines, three icons (unknown = initial), dark window", look);
check(look.calm==='none'&&look.barDeco==='none'&&look.barIcons==='none', "calm hides the terminal; the notch hides deco and icons", look);
// music + work: only the work reaction shows, the chip stays, the glasses fade even with coding on
await ev(`sit({music:true,coding:true}); return 1;`); await sleep(3600); await settle();
const mw = await ev(`return {focus:document.body.dataset.focus,sky:$('#rxSky').children.length,front:$('#rxFront').children.length,chip:!$('#musChip').hidden,glasses:+SIT_P.gl.getAttribute('opacity')};`);
check(mw.focus==='work'&&mw.sky===0&&mw.front===0&&mw.chip&&mw.glasses<.01, "music + work: no reaction art, the music chip stays, glasses at 0", mw);
await ev(`sit({music:false,coding:false}); return 1;`);
// a mail notification during work: the terminal steps aside, then comes back
await ev(`onEvent({t:'notify',key:'work-mail',category:'mail',app:'thunderbird',summary:'Mail in work'}); return 1;`); await sleep(400); await settle();
const mailDuring = await ev(`return {focus:document.body.dataset.focus,on:$('#code').classList.contains('on'),want:sheetWant};`);
check(mailDuring.focus==='event'&&!mailDuring.on&&JSON.stringify(mailDuring.want)==='[0,0]', "mail during work: event focus, the terminal steps aside", mailDuring);
await sleep(6500); await settle();
const mailAfter = await ev(`return {focus:document.body.dataset.focus,on:$('#code').classList.contains('on')};`);
check(mailAfter.focus==='work'&&mailAfter.on, "after the mail the terminal comes back", mailAfter);
// an approval card during work: answer focus, no sheet
await ev(`onEvent({t:'approve',id:'work-a1',agent:'codex',tool:'Bash',detail:'true',confirm:'click',always:false}); return 1;`); await settle();
eq(await ev(`return [document.body.dataset.focus,$('#code').classList.contains('on')];`), ["answer",false], "approval card during work: answer focus, no sheet");
await ev(`approvalGone('work-a1'); return 1;`); await sleep(500); await settle();
for (const c of ["snowflake", "terminal", "robot", "devil"]) {   // Nixi at work: his eyes become the code screen, the keyboard shows
  await ev(`setCharacter('${c}'); return 1;`); await settle();
  const w = await ev(`const B=document.body.classList, d=e=>getComputedStyle($(e)).display, v=e=>getComputedStyle($(e)).visibility;
    transient=null; const r={focus:B.contains('bar')?'bar':document.body.dataset.focus,eL:d('#eL'),ce:d('#codeEyes'),kbd:d('#kbd'),mood:mood(performance.now())};
    B.add('bar'); r.barCe=d('#codeEyes'); r.barKbd=d('#kbd'); B.remove('bar'); return r;`);
  check(w.focus === "work" && w.eL === "none" && w.ce !== "none" && w.kbd !== "none" && w.mood === "working" && w.barCe === "none" && w.barKbd === "none", `work look on ${c}`, w);
}
await ev(`setCharacter('snowflake'); return 1;`);
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await settle();
eq(await ev(`return document.getAnimations().filter(a=>a.playState==='running'&&a.effect&&a.effect.target&&a.effect.target.closest&&a.effect.target.closest('#code,#codeEyes,#kbd')).length;`), 0, "reduced motion: no running animation in the terminal, his screen or the keyboard");
await send("Emulation.setEmulatedMedia", { features: [] });
if (process.env.NIXI_SHOTS) {   // screenshots for the PR: the sheet with two agents, dark and light theme
  const { writeFileSync, mkdirSync } = await import("node:fs"); mkdirSync(process.env.NIXI_SHOTS, { recursive: true });
  const shot = async n => { await sleep(3500); await settle(); const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(`${process.env.NIXI_SHOTS}/${n}.png`, Buffer.from(r.result.data, "base64")); };
  await ev(`onEvent({t:'attention',kind:'done',from:'zed',name:'Zed',project:'p3',text:''}); document.body.style.background='#1b1e24'; return 1;`); await shot("terminal-dark");
  await ev(`applyThemeVars({mode:'light',background:'#f5f5f5',darker_background:'#e5e5e5',lighter_background:'#fafafa',foreground:'#222',accent:'#2060d0',red:'#c00',green:'#080',yellow:'#a80',selection:'#ccc'}); document.body.style.background='#f0f0f0'; return 1;`); await shot("terminal-light");
  for (const c of ["snowflake", "terminal", "robot", "devil"]) for (const z of [60, 100]) {   // work look at the 60% and 100% size (page zoom stands in for the window zoom)
    await ev(`setCharacter('${c}'); document.documentElement.style.zoom=${z / 100}; return 1;`); await shot(`work-${c}-${z}`); }
}
// his own turn: a spoken reply with no tool is not work; his own tool run shows the tool, then returns to the agents' line
await ev(`for(const f of ['claude','codex','zed']) CP.agentEnd(f,''); CP.answer(); focusSync(performance.now()); return 1;`); await sleep(2800); await settle();
eq(await ev(`return [CP.n(),document.body.dataset.focus];`), [0,"ambient"], "his spoken reply with no tool use: not work");
await ev(`CP.done(); `+wk("codex","Codex","p2")+` return 1;`); await settle();
const run = await ev(`CP.tool({t:'tool',id:'own1',name:'Bash',input:{command:'true',description:'own run'}}); await new Promise(r=>setTimeout(r,80)); focusSync(performance.now());
  return {focus:document.body.dataset.focus,title:$('#code .tb b').textContent,on:$('#code').classList.contains('on')};`);
check(run.focus==='work'&&run.title==='own run'&&run.on, "his own tool run shows on the sheet (work focus)", run);
await sleep(2500); await settle();
const back = await ev(`return {title:$('#code .tb b').textContent,rows:document.querySelectorAll('#code .lines .st').length,on:$('#code').classList.contains('on')};`);
check(back.title==='Codex'&&back.rows===1&&back.on, "after his run the sheet returns to codex's line", back);
// (Codex review) an approval during his own tool run: the sheet steps aside and comes back for the rest of the run
const yi = await ev(`const fr=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  CP.tool({t:'tool',id:'own2',name:'Bash',input:{command:'true',description:'own run 2'}}); await new Promise(r=>setTimeout(r,80)); await fr();
  onEvent({t:'approve',id:'focus-a2',agent:'codex',tool:'Bash',detail:'true',confirm:'click',always:false}); await fr();
  const during=[document.body.dataset.focus,$('#code').classList.contains('on')]; approvalGone('focus-a2'); await fr();
  return [...during,$('#code').classList.contains('on')];`);
eq(yi, ["answer", false, true], "his own run's sheet yields to an approval card and comes back");
await sleep(2500); await settle();
// peek: after a long idle he shrinks; a working agent brings him back to full size
await ev(`CP.agentEnd('codex',''); chip.classList.remove('act'); AM=null; attnPend=null; propOn=null; if(notifyRow) notifyClear(); $('#mailPop').classList.remove('on'); idleHoldUntil=0; lastUser=0; nixiIdleScale(.001); return 1;`);   // (clear what keeps him up: the cues earlier checks left)
let peeked = false; for (let i = 0; i < 40 && !peeked; i++) { await sleep(250); peeked = await ev(`return document.body.classList.contains('peek');`); }
check(peeked, "idle: he goes to peek", await ev(`return {active:idleActive(),showing:idleShowing(),mode:info.idle_mode,capOn,playing,hold:idleHoldUntil-performance.now()};`));
await ev(wk("claude","Claude","p1") + "return 1;"); await sleep(1500);
eq(await ev(`return document.body.classList.contains('peek');`), false, "a working event wakes him from peek to full size");
await ev(`nixiIdleScale(1000); return 1;`);
// (agy review) his streamed reply while an agent works: CP.answer() runs per delta and must not resize the window each time
const spam = await ev(`const fr=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  evUntil=0; onEvent({t:'attention',kind:'working',from:'codex',name:'Codex',project:'pz'}); await fr(); focusSync(performance.now()); await fr();
  const s0=window.sizeWindow; let n=0; window.sizeWindow=(...a)=>{ n++; return s0(...a); };
  for(let i=0;i<5;i++) CP.answer(); await fr(); window.sizeWindow=s0;
  const on=$('#code').classList.contains('on'); CP.done(); CP.agentEnd('codex',''); return [n,on];`);
eq(spam, [0, true], "five streamed deltas while an agent works: no window resize, the sheet stays");
eq(errors, [], "no console errors");

await ev(`window.fetch=window.fetch0; return 1;`);
if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("stage focus fit ok");
process.exit(0);
