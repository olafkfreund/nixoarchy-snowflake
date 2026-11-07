// The Settings panel (#175): panelSize() size owner, default cap, pure-CSS clamp, open/close transitions and click region.
//   node tests/settings_fit.mjs <cdp-port> <page-url>
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
await ev(`setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full');
  window.__msgs=[]; window.webkit={messageHandlers:{nixiui:{postMessage:m=>__msgs.push(String(m))}}};
  Object.defineProperty(screen,'availWidth',{get:()=>window.__aw||1920,configurable:true});
  Object.defineProperty(screen,'availHeight',{get:()=>window.__ah||1080,configurable:true});
  return 1`);

const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const msgs = () => ev("return __msgs.slice()");
const clearMsgs = () => ev("__msgs.length=0; return 1");
const nonRegion = list => list.filter(m => !m.startsWith("region:"));
const lastSize = list => [...list].reverse().find(m => m.startsWith("size:"));
const lastWide = list => [...list].reverse().find(m => m.startsWith("wide:"));

// 1. Opening Settings sends size:244,266 and wide:off (never wide:on), and sets setWant = [244, 266]
{ await clearMsgs();
  await ev("setW=0; setH=0; settings(true); return 1");
  const m = await msgs(), nr = nonRegion(m);
  const w = await ev("return [setW, setH, setWant[0], setWant[1], setEl.classList.contains('on'), document.body.classList.contains('pnl')]");
  check(w[0] === 560 && w[1] === 680 && w[2] === 244 && w[3] === 266 && w[4] && w[5] && lastSize(nr) === "size:244,266" && lastWide(nr) === "wide:off" && !nr.includes("wide:on"),
    "opening Settings sends size:244,266 and wide:off, no wide:on", JSON.stringify({ w, nr }));
}

// 2. Default cap when screen.availWidth / screen.availHeight is smaller than 560x680
{ await ev("settings(false); window.__aw=500; window.__ah=600; setW=0; setH=0; settings(true); return 1");
  const c = await ev("return [setW, setH, setWant[0], setWant[1]]");
  check(c[0] === 460 && c[1] === 510 && c[2] === 460 - 340 + 24 && c[3] === 510 - 460 + 46,
    "default size is capped to screen.availWidth-40 and 0.85*screen.availHeight", JSON.stringify(c));
  await ev("window.__aw=1920; window.__ah=1080; setW=0; setH=0; settings(false); return 1");
}

// 3. The box is 560x680 in a large viewport and clamped in a small one, while setW/setH/setWant stay 560/680/[244,266]
{ await view(584, 726);
  await ev("settings(true); nixiLayout(122, 133); return 1"); await sleep(450);
  const big = await ev("const r=setEl.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height), setW, setH, setWant[0], setWant[1]]");
  check(big[0] === 12 && big[1] === 34 && big[2] === 560 && big[3] === 680 && big[4] === 560 && big[5] === 680 && big[6] === 244 && big[7] === 266,
    "box is 560x680 at (12,34) in a large viewport", JSON.stringify(big));

  // smaller viewport (e.g. near a monitor edge): clamped to innerWidth-24 and innerHeight-46, wanted size never reduced
  await view(440, 520); await sleep(100);
  const sm = await ev("const r=setEl.getBoundingClientRect(), bd=setEl.querySelector('.bd'); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height), setW, setH, setWant[0], setWant[1], bd.scrollHeight>bd.clientHeight]");
  check(sm[0] === 12 && sm[1] === 34 && sm[2] === 416 && sm[3] === 474 && sm[4] === 560 && sm[5] === 680 && sm[6] === 244 && sm[7] === 266 && sm[8],
    "late resize to a smaller viewport clamps the shown box while keeping setW/setH/setWant", JSON.stringify(sm));

  // growing the viewport back lets the box grow back to 560x680
  await view(700, 800); await sleep(100);
  const grown = await ev("const r=setEl.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), setW, setH]");
  check(grown[0] === 560 && grown[1] === 680 && grown[2] === 560 && grown[3] === 680,
    "growing the viewport restores the full 560x680 box", JSON.stringify(grown));
  await ev("settings(false); return 1");
  await view(340, 460);
}

// 4. Out-of-order / stale size answer: a stale resize/nixiLayout followed by the latest one leaves the box matching the latest request
{ await ev("settings(true); return 1");
  // Simulate an older small window allocation arriving, then the real 584x726 allocation
  await view(400, 500);
  await ev("nixiLayout(30, 20); return 1");
  await view(584, 726);
  await ev("nixiLayout(122, 133); return 1"); await sleep(450);
  const oo1 = await ev("const r=setEl.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), setWant[0], setWant[1]]");
  // And if a stale resize arrives while Settings is open, setWant still holds the latest wanted size so sizeWindow() re-requests it
  await view(460, 540); await sleep(80);
  const oo2 = await ev("const r=setEl.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), setW, setH, setWant[0], setWant[1]]");
  await view(584, 726); await sleep(80);
  const oo3 = await ev("const r=setEl.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]");
  check(oo1[0] === 560 && oo1[1] === 680 && oo2[0] === 436 && oo2[1] === 494 && oo2[2] === 560 && oo2[3] === 680 && oo2[4] === 244 && oo2[5] === 266 && oo3[0] === 560 && oo3[1] === 680,
    "out-of-order size answer leaves the box matching the latest state and never reduces setW/setH", JSON.stringify({ oo1, oo2, oo3 }));
  await ev("settings(false); nixiLayout(0,0); return 1");
  await view(340, 460);
}

// 5. Click region with ?native=1 covers the full Settings box
{ await view(584, 726);
  await ev("info.click_through=true; settings(true); nixiLayout(122,133); return 1"); await sleep(500);
  await clearMsgs();
  await ev("sendRegion(true); return 1");
  const rg = await ev("const m=[...__msgs].reverse().find(x=>x.startsWith('region:')), sr=setEl.getBoundingClientRect(); return {rs:m?JSON.parse(m.slice(7)):null, sr:[sr.left,sr.top,sr.right,sr.bottom,sr.width,sr.height]}");
  const covers = Array.isArray(rg.rs) && rg.rs.some(([x, y, w, h]) => x <= rg.sr[0] && y <= rg.sr[1] && x + w >= rg.sr[2] && y + h >= rg.sr[3]);
  check(covers && Math.round(rg.sr[4]) === 560 && Math.round(rg.sr[5]) === 680,
    "sendRegion covers the 560x680 Settings box with ?native=1", JSON.stringify(rg));
  await ev("settings(false); nixiLayout(0,0); return 1");
  await view(340, 460);
}

// 6. Transitions:
// 6a. Settings -> openPanel('history') -> close
{ await clearMsgs();
  await ev("settings(true); return 1");
  const m1 = nonRegion(await msgs());
  await clearMsgs();
  await ev("await openPanel('history'); return 1");
  const m2 = nonRegion(await msgs());
  const st2 = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), setWant[0], setWant[1], document.body.classList.contains('pnl')]");
  await clearMsgs();
  await ev("closePanels(); return 1");
  const m3 = nonRegion(await msgs());
  const st3 = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), setWant[0], setWant[1], document.body.classList.contains('pnl')]");
  check(lastSize(m1) === "size:244,266" && lastWide(m1) === "wide:off"
    && !st2[0] && st2[1] && st2[2] === 0 && st2[3] === 0 && st2[4] && m2.join(",") === "size:0,0,wide:on"
    && !st3[0] && !st3[1] && st3[2] === 0 && st3[3] === 0 && !st3[4] && m3.join(",") === "wide:off,size:0,0",
    "transition: Settings -> panel -> close (shrink size:0,0 before wide:on)", JSON.stringify({ m1, m2, st2, m3, st3 }));
}

// 6b.Settings -> Memory/History via data-open button inside Settings (line 3361) -> close
{ for (const kind of ["memory", "history"]) {
    await ev("settings(true,'more'); return 1");
    await clearMsgs();
    await ev(`setEl.querySelector('[data-open="${kind}"]').click(); await new Promise(r=>setTimeout(r,150)); return 1`);
    const m = nonRegion(await msgs());
    const st = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), panelKind, setWant[0], setWant[1]]");
    check(!st[0] && st[1] && st[2] === kind && st[3] === 0 && st[4] === 0 && m.join(",") === "size:0,0,wide:on",
      `transition: Settings -> ${kind} (data-open) sends size:0,0 then wide:on`, JSON.stringify({ m, st }));
    await ev("closePanels(); return 1");
  }
}

// 6c. panel -> Settings (and Quick actions #qaEditBtn -> Settings) -> close via ✕
{ await ev("await openPanel('actions'); return 1");
  await clearMsgs();
  await ev("document.getElementById('qaEditBtn').click(); return 1");
  const m1 = nonRegion(await msgs());
  const st1 = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), document.querySelector('#set .tab[data-tab=brain]').classList.contains('on'), setWant[0], setWant[1]]");
  await clearMsgs();
  await ev("setEl.querySelector('[data-close]').click(); return 1");
  const m2 = nonRegion(await msgs());
  const st2 = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), setWant[0], setWant[1], document.body.classList.contains('pnl')]");
  check(st1[0] && !st1[1] && st1[2] && st1[3] === 244 && st1[4] === 266 && m1.join(",") === "wide:off,size:244,266"
    && !st2[0] && !st2[1] && st2[2] === 0 && st2[3] === 0 && !st2[4] && m2.join(",") === "wide:off,size:0,0",
    "transition: Quick actions (#qaEditBtn) -> Settings (wide:off before size:244,266) -> ✕ close", JSON.stringify({ m1, st1, m2, st2 }));
}

// 6d. Esc closes Settings and returns request to base
{ await ev("settings(true); return 1");
  await clearMsgs();
  await ev("window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})); return 1");
  const m = nonRegion(await msgs());
  const st = await ev("return [setEl.classList.contains('on'), setWant[0], setWant[1], document.body.classList.contains('pnl')]");
  check(!st[0] && st[1] === 0 && st[2] === 0 && !st[3] && lastSize(m) === "size:0,0" && lastWide(m) === "wide:off",
    "transition: Esc closes Settings and resets size", JSON.stringify({ m, st }));
}

// 6e. Click outside .pn closes Settings and returns request to base
{ await ev("settings(true); return 1");
  await clearMsgs();
  await ev("document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true})); return 1");
  const m = nonRegion(await msgs());
  const st = await ev("return [setEl.classList.contains('on'), setWant[0], setWant[1], document.body.classList.contains('pnl')]");
  check(!st[0] && st[1] === 0 && st[2] === 0 && !st[3] && lastSize(m) === "size:0,0" && lastWide(m) === "wide:off",
    "transition: click outside .pn closes Settings and resets size", JSON.stringify({ m, st }));
  // 6e-guard. closePanels() when neither panel nor Settings is open does not send wide:/size:/region:
  await clearMsgs();
  await ev("closePanels(); document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true})); showAsk(); hideAsk(); return 1");
  const mGuard = await msgs();
  check(!mGuard.some(x => x.startsWith("wide:") || x.startsWith("size:")),
    "closePanels() is a no-op when neither panel nor Settings was open", JSON.stringify(mGuard));
}

// 6f. Radial menu opens and closes Settings cleanly
{ await ev("menu(true); return 1");
  await clearMsgs();
  await ev("document.querySelector('#menu .mb[data-a=\"set\"]').click(); return 1");
  const m1 = nonRegion(await msgs());
  await clearMsgs();
  await ev("menu(true); return 1");
  const m2 = nonRegion(await msgs());
  check(lastSize(m1) === "size:244,266" && lastWide(m1) === "wide:off" && lastSize(m2) === "size:0,0" && lastWide(m2) === "wide:off",
    "transition: radial menu -> Settings -> radial menu resets size", JSON.stringify({ m1, m2 }));
  await ev("menu(false); return 1");
}

// 6g. Stage card open: map card's Settings button collapses stage to tab (stageHide(true)) and opens Settings (a panel asks for no board room: size:244,266); closing Settings returns to the tab's want (size:300,0)
{ const mapUnset = { t: "stage", v: 1, kind: "place", trust: "mechanic", dest: "@home", unset: "home" };
  await ev(`stageClose(); await new Promise(r=>setTimeout(r,260)); onEvent(${JSON.stringify(mapUnset)}); await new Promise(r=>setTimeout(r,150)); return 1`);
  await clearMsgs();
  await ev(`[...document.querySelectorAll('#stg .sb')].find(b=>b.textContent==='Settings').click(); return 1`);
  const mOpen = nonRegion(await msgs());
  const stOpen = await ev("return [stgState, stageWant[0], stageWant[1], setEl.classList.contains('on'), setWant[0], setWant[1]]");
  await clearMsgs();
  await ev("settings(false); return 1");
  const mClose = nonRegion(await msgs());
  const stClose = await ev("return [stgState, stageWant[0], setEl.classList.contains('on'), setWant[0], setWant[1]]");
  check(stOpen[0] === "tab" && stOpen[1] === 300 && stOpen[3] && stOpen[4] === 244 && stOpen[5] === 266
    && lastSize(mOpen) === "size:244,266" && lastWide(mOpen) === "wide:off"
    && stClose[0] === "tab" && stClose[1] === 300 && !stClose[2] && stClose[3] === 0 && stClose[4] === 0
    && lastSize(mClose) === "size:300,0" && lastWide(mClose) === "wide:off",
    "transition: map stage Settings button collapses stage to tab (stageHide(true)) and closing Settings returns to size:300,0 (a panel asks for no board room: 244,266 open)",
    JSON.stringify({ mOpen, stOpen, mClose, stClose }));
  await ev("stageClose(); await new Promise(r=>setTimeout(r,260)); return 1");
}


// #196: while a panel is open (body.pnl) a board asks for no room, hides, holds a new board, and comes back on close
{ const B1 = { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: "Board one", points: ["a", "b"] },
    B2 = { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: "Board two", points: ["c"] },
    B3 = { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: "Board three", points: ["d"] };
  const reset = () => ev(`settings(false); closePanels(); info.hover=false; setHoverClass(false); hiddenNow=false; stageClose(); await new Promise(r=>setTimeout(r,300)); return 1`);
  const show = e => ev(`onEvent(${JSON.stringify(e)}); await new Promise(r=>setTimeout(r,250)); return 1`);
  const disp = sel => ev(`return getComputedStyle(document.querySelector('${sel}')).display`);
  const st = () => ev("return [stgState, stg&&stg.title, document.body.classList.contains('calm'), document.body.classList.contains('pnl')]");
  await reset();
  // baseline: Settings with no board
  await ev("settings(true); return 1"); await sleep(450);
  const baseLeft = await ev("return Math.round(setEl.getBoundingClientRect().left)");
  await reset();

  // open board, then Settings
  await show(B1); await clearMsgs();
  await ev("settings(true); return 1"); await sleep(450);
  let m = nonRegion(await msgs()), left = await ev("return Math.round(setEl.getBoundingClientRect().left)");
  check(lastSize(m) === "size:244,266", "#196 open board, then Settings asks only for Settings' room (the fake window never resizes, so position is a live check)", JSON.stringify({ m, left, baseLeft }));
  check((await disp("#stg")) === "none", "#196 the board is hidden while Settings is open", await disp("#stg"));
  await clearMsgs(); await ev("settings(false); return 1"); await sleep(300);
  m = nonRegion(await msgs());
  let s2 = await st();
  check(lastSize(m) === "size:800,0" && s2[0] === "open" && !s2[2] && (await disp("#stg")) !== "none" && await ev("return stgEl.classList.contains('on')"),
    "#196 closing Settings: size:800,0 and the board is open and visible", JSON.stringify({ m, s2 }));

  // tab, then Settings
  await ev("stageHide(true); await new Promise(r=>setTimeout(r,300)); return 1"); await clearMsgs();
  await ev("settings(true); return 1"); await sleep(300);
  m = nonRegion(await msgs());
  check(lastSize(m) === "size:244,266" && (await disp("#stgTab")) === "none", "#196 tab, then Settings: size:244,266 and the tab is hidden", JSON.stringify({ m, d: await disp("#stgTab") }));
  await clearMsgs(); await ev("settings(false); return 1"); await sleep(300);
  m = nonRegion(await msgs());
  check(lastSize(m) === "size:300,0" && (await st())[0] === "tab" && (await disp("#stgTab")) !== "none", "#196 closing Settings: size:300,0 and the tab is back", JSON.stringify({ m, s: await st() }));
  await reset();

  // stgSize(0) during Settings
  await show(B1);
  await ev("settings(true); return 1"); await clearMsgs();
  await ev("stgSize(800); stgSize(0); stgSize(800); return 1");
  m = nonRegion(await msgs());
  check(m.filter(x => x.startsWith("size:")).every(x => x === "size:244,266"), "#196 a board's room changing during Settings sends no change of width", JSON.stringify(m));
  await ev("stgSize(800); return 1");
  await reset();

  // the other rooms a board or a mail pop asks for (width and height) are left out too, and the chalk hides with the board
  await show(B1); await ev("settings(true); return 1"); await clearMsgs();
  const rooms = [];
  for (const js of ["popWant=[260,0]", "popWant=[0,500]", "stageWant=[800,0]", "stageWant=[0,500]"]) {
    await ev(`${js}; sizeWindow(); return 1`); rooms.push(lastSize(nonRegion(await msgs()))); await clearMsgs(); }
  await ev("popWant=[0,0]; stageWant=[0,0]; return 1");
  check(rooms.every(r => r === "size:244,266"), "#196 popWant and stageWant, width and height, add no room during Settings", JSON.stringify(rooms));
  await reset();
  await show({ t: "stage", v: 1, kind: "commands", trust: "mechanic", title: "Cmds", items: [{ label: "x", cmd: "ls" }] });
  const chalkOn = await ev("return chalkEl.classList.contains('on')&&getComputedStyle(chalkEl).display!=='none'");
  await ev("settings(true); return 1"); await sleep(300);
  check(chalkOn && (await disp("#chalk")) === "none", "#196 the chalk hides while Settings is open", JSON.stringify({ chalkOn, d: await disp("#chalk") }));
  await reset();

  // a stage event during Settings: held, no caption, old board untouched; shown on close
  await show(B1); await ev("settings(true); return 1"); await sleep(300);
  const him0 = await ev("return himEl.textContent");
  await ev(`onEvent(${JSON.stringify(B2)}); return 1`);
  const him1 = await ev("return himEl.textContent"); s2 = await st();
  check(him1 === him0 && s2[1] === "Board one" && s2[0] === "open", "#196 a stage event during Settings: no caption, the old board untouched", JSON.stringify({ him0, him1, s2 }));
  await ev("settings(false); return 1"); await sleep(400); s2 = await st();
  check(s2[0] === "open" && s2[1] === "Board two" && !s2[2], "#196 closing Settings shows the held board", JSON.stringify(s2));
  await reset();
  // two events: the newest
  await show(B1); await ev("settings(true); return 1"); await sleep(300);
  await ev(`onEvent(${JSON.stringify(B2)}); onEvent(${JSON.stringify(B3)}); return 1`);
  await ev("settings(false); return 1"); await sleep(400); s2 = await st();
  check(s2[0] === "open" && s2[1] === "Board three", "#196 two events during Settings: the newest wins", JSON.stringify(s2));
  await reset();
  // stage_close afterwards: none shown
  await show(B1); await ev("settings(true); return 1"); await sleep(300);
  await ev(`onEvent(${JSON.stringify(B2)}); onEvent({t:'stage_close'}); return 1`);
  await ev("settings(false); return 1"); await sleep(400); s2 = await st();
  check(s2[0] === "closed", "#196 stage_close during Settings drops the held board and closes", JSON.stringify(s2));
  await reset();

  // stageTick with an old stgUse during Settings
  await show(B1); await ev("settings(true); return 1"); await sleep(300);
  const tk = await ev("const old=performance.now()-100000; stgUse=stgQuiet=old; stageTick(); return [stgState, performance.now()-stgUse, performance.now()-stgQuiet]");
  check(tk[0] === "open" && tk[1] < 1000 && tk[2] < 1000, "#196 stageTick during Settings keeps the board and refreshes stgUse/stgQuiet", JSON.stringify(tk));
  await ev("settings(false); return 1"); await sleep(300);
  await ev("stageTick(); return 1"); s2 = await st();
  check(s2[0] === "open", "#196 after Settings closes the board doesn't close on the next tick", JSON.stringify(s2));
  await reset();

  // history panel, and Settings -> panel keeps the board hidden
  await show(B1); await clearMsgs();
  await ev("await openPanel('history'); return 1"); await sleep(400);
  m = nonRegion(await msgs());
  check(lastSize(m) === "size:0,0" && (await disp("#stg")) === "none", "#196 history panel: no board room and the board hidden", JSON.stringify({ m, d: await disp("#stg") }));
  await ev("settings(true); return 1"); await sleep(300);
  check((await disp("#stg")) === "none" && lastSize(nonRegion(await msgs())) === "size:244,266", "#196 Settings from the panel keeps the board hidden", String(await disp("#stg")));
  await ev("settings(false); return 1"); await sleep(300); s2 = await st();
  check(s2[0] === "open" && (await disp("#stg")) !== "none", "#196 after both close the board is back", JSON.stringify(s2));
  await reset();

  // a held board when Settings closes in hover, and with hiddenNow: today's rule (a caption, no board)
  for (const [why, setup, undo] of [["hover", "info.hover=true; setHoverClass(true);", "info.hover=false; setHoverClass(false);"], ["hiddenNow", "hiddenNow=true;", "hiddenNow=false;"]]) {
    await ev("settings(true); return 1"); await sleep(300);
    await ev(`onEvent(${JSON.stringify(B2)}); ${setup} return 1`);
    const h0 = await ev("return himEl.textContent");
    await ev("settings(false); return 1"); await sleep(300);
    const h1 = await ev("return himEl.textContent"); s2 = await st();
    check(s2[0] === "closed" && h1.includes("Board two") && h1 !== h0, `#196 a held board closing in ${why}: a caption instead of a board`, JSON.stringify({ s2, h1 }));
    await ev(`${undo} return 1`); await reset();
  }

  // hover turned on inside Settings with a board up, then closing
  await show(B1); await ev("settings(true); return 1"); await sleep(300);
  await ev("info.hover=true; setHoverClass(true); return 1");
  await clearMsgs(); await ev("settings(false); return 1"); await sleep(300);
  m = nonRegion(await msgs()); s2 = await st();
  check(s2[0] === "open" && (await disp("#stg")) === "none", "#196 hover turned on inside Settings, then close: the board stays open and hidden (the window ignores room in hover)", JSON.stringify({ m, s2 }));
  await reset();

  // a late update to a held board is kept (the server doesn't resend it)
  await ev("settings(true); return 1"); await sleep(200);
  await ev(`onEvent(${JSON.stringify({ ...B1, kind: "headlines", copy: "c196", items: [] })}); onEvent({t:'stage_update',kind:'headlines',copy:'c196',clips:['late']}); onEvent({t:'stage_update',kind:'headlines',copy:'other',clips:['wrong']}); return 1`);
  check((await ev("return [stgHeld.t, stgHeld.clips.join()]")).join() === "stage,late", "#196 a held board keeps its late update, and only its own", JSON.stringify(await ev("return stgHeld&&[stgHeld.t,stgHeld.clips]")));
  await ev("stgHeld=null; settings(false); return 1"); await sleep(200); await reset();

  // going away with a panel open: the held board doesn't open unseen
  await show(B1); await ev("settings(true); return 1"); await sleep(200);
  await ev(`onEvent(${JSON.stringify({ ...B1, title: "Board held" })}); himSet(''); dismiss(); hiddenNow=true; return 1`); await sleep(350);
  s2 = await st();
  check(s2[0] === "closed" && (await ev("return stgHeld===null")), "#196 hiding him with a panel open follows the hidden rule: no board opens", JSON.stringify(s2));
  await ev("hiddenNow=false; return 1"); await reset();
}

// 7. At 320x400 (fitK < 1), Settings is reachable and its body scrolls (pixel size not checked)
{ await view(320, 400); await sleep(100);
  await ev("settings(true,'look'); return 1"); await sleep(450);
  const f = await ev(`const r=setEl.getBoundingClientRect(), bd=setEl.querySelector('.bd');
    bd.scrollTop=0; bd.scrollTop=40; const after=bd.scrollTop;
    return [fitK<1, setEl.classList.contains('on'), r.width>0&&r.height>0, r.left<innerWidth&&r.top<innerHeight&&r.right>0&&r.bottom>0, bd.scrollHeight>bd.clientHeight, after>0]`);
  check(f.every(Boolean), "at 320x400 (fitK < 1), Settings is reachable and its body scrolls", JSON.stringify(f));
  await ev("settings(false); return 1");
  await view(340, 460);
}

// 8. Five tabs; Plugins tab (between Brain and More, with puzzle icon) holds #peersRow, #plugCons, #plugList, #plugErr, #plugReload in a .row wrapper, and More does not
{ const t5 = await ev(`const bs=[...document.querySelectorAll('#tabs button')], ps=[...document.querySelectorAll('#set .tab')];
    const plugTab=document.querySelector('#set .tab[data-tab="plugins"]'), moreTab=document.querySelector('#set .tab[data-tab="more"]');
    const ids=['peersRow','plugCons','plugList','plugErr','plugReload'];
    const inPlug=ids.every(id=>plugTab.contains(document.getElementById(id)) && document.getElementById(id).closest('.row')?.parentElement===plugTab);
    const inMore=ids.some(id=>moreTab.contains(document.getElementById(id)));
    const pb=document.querySelector('#tabs button[data-tab="plugins"]');
    return {
      tabs: bs.map(b=>b.dataset.tab),
      panels: ps.map(p=>p.dataset.tab),
      tablistRole: document.getElementById('tabs').getAttribute('role'),
      tabRoles: bs.map(b=>b.getAttribute('role')),
      panelRoles: ps.map(p=>p.getAttribute('role')),
      controls: bs.map(b=>document.getElementById(b.getAttribute('aria-controls'))?.dataset?.tab),
      hasPuzzleSvg: !!pb?.querySelector('svg path'),
      inPlug, inMore
    }`);
  check(t5.tabs.join() === "look,voice,brain,plugins,more"
    && t5.panels.join() === "look,voice,brain,plugins,more"
    && t5.tablistRole === "tablist"
    && t5.tabRoles.every(r => r === "tab")
    && t5.panelRoles.every(r => r === "tabpanel")
    && t5.controls.join() === "look,voice,brain,plugins,more"
    && t5.hasPuzzleSvg && t5.inPlug && !t5.inMore,
    "five tabs with ARIA roles; Plugins holds the five plugin IDs in .row and More does not", JSON.stringify(t5));
}

// 9. ArrowLeft/ArrowRight wrap, Home and End move between tabs, updating aria-selected, roving tabindex, and focus
{ await ev("settings(true,'look'); return 1");
  const nav = await ev(`const tabsEl=document.getElementById('tabs'), key=k=>tabsEl.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
    const state=()=>[document.activeElement?.dataset?.tab, document.querySelector('#tabs button.on')?.dataset?.tab, document.querySelector('#set .tab.on')?.dataset?.tab,
      [...document.querySelectorAll('#tabs button')].map(b=>b.getAttribute('aria-selected')+':'+b.tabIndex).join(',')];
    const s0=state();
    key('ArrowLeft'); const s1=state();
    key('ArrowRight'); const s2=state();
    key('End'); const s3=state();
    key('ArrowLeft'); const s4=state();
    key('Home'); const s5=state();
    return {s0,s1,s2,s3,s4,s5}`);
  check(nav.s0[0] === "look" && nav.s0[1] === "look" && nav.s0[2] === "look" && nav.s0[3] === "true:0,false:-1,false:-1,false:-1,false:-1"
    && nav.s1[0] === "more" && nav.s1[1] === "more" && nav.s1[2] === "more" && nav.s1[3] === "false:-1,false:-1,false:-1,false:-1,true:0"
    && nav.s2[0] === "look" && nav.s2[1] === "look" && nav.s2[2] === "look"
    && nav.s3[0] === "more" && nav.s3[1] === "more"
    && nav.s4[0] === "plugins" && nav.s4[1] === "plugins" && nav.s4[2] === "plugins" && nav.s4[3] === "false:-1,false:-1,false:-1,true:0,false:-1"
    && nav.s5[0] === "look" && nav.s5[1] === "look",
    "ArrowLeft/ArrowRight wrap and Home/End select, show and focus tabs with roving tabindex", JSON.stringify(nav));
  await ev("settings(false); return 1");
}

// 10. nixi.tab='bogus' and settings(true,'bogus') fall back to Look, and nixi.tab='plugins' opens Plugins
{ const fb = await ev(`localStorage.setItem('nixi.tab','bogus'); settings(true);
    const a=[document.querySelector('#tabs button.on')?.dataset?.tab, document.querySelector('#set .tab.on')?.dataset?.tab, localStorage.getItem('nixi.tab'), document.activeElement?.dataset?.tab];
    settings(false);
    settings(true,'bogus');
    const b=[document.querySelector('#tabs button.on')?.dataset?.tab, document.querySelector('#set .tab.on')?.dataset?.tab, localStorage.getItem('nixi.tab'), document.activeElement?.dataset?.tab];
    settings(false);
    localStorage.setItem('nixi.tab','plugins'); settings(true);
    const c=[document.querySelector('#tabs button.on')?.dataset?.tab, document.querySelector('#set .tab.on')?.dataset?.tab, document.activeElement?.dataset?.tab];
    settings(false);
    localStorage.setItem('nixi.tab','look');
    return {a,b,c}`);
  check(fb.a.join() === "look,look,look,look" && fb.b.join() === "look,look,look,look" && fb.c.join() === "plugins,plugins,plugins",
    "nixi.tab='bogus' and settings(true,'bogus') fall back to Look; nixi.tab='plugins' selects Plugins", JSON.stringify(fb));
}

// 11. Opening Settings saves document.activeElement and focuses the selected tab; closing (every path) restores focus if still connected
{ const foc = await ev(`const probe=document.createElement('button'); probe.id='focusProbe'; document.body.appendChild(probe);
    const out={};
    probe.focus(); settings(true,'brain');
    out.open=[document.activeElement?.dataset?.tab];
    settings(false);
    out.afterSettingsFalse=document.activeElement===probe;
    probe.focus(); settings(true,'plugins');
    setEl.querySelector('[data-close]').click();
    out.afterX=document.activeElement===probe;
    probe.focus(); settings(true,'voice');
    setEl.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    out.afterEsc=document.activeElement===probe;
    probe.focus(); settings(true,'more');
    document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));
    out.afterOutside=document.activeElement===probe;
    probe.focus(); settings(true,'look');
    closePanels();
    out.afterClosePanels=document.activeElement===probe;
    // disconnected element does not throw
    probe.focus(); settings(true,'look'); probe.remove(); settings(false);
    out.afterRemoved=!setEl.classList.contains('on');
    // ask #input focused before settings(true): hideAsk() blurs #input inside settings(), so focus must be captured before hideAsk()
    showAsk('hi');
    out.inputFocusedBefore=document.activeElement===input;
    settings(true,'look');
    settings(false);
    out.afterAskInput=document.activeElement===input;
    hideAsk();
    return out`);
  check(foc.open[0] === "brain" && foc.afterSettingsFalse && foc.afterX && foc.afterEsc && foc.afterOutside && foc.afterClosePanels && foc.afterRemoved && foc.inputFocusedBefore && foc.afterAskInput,
    "opening focuses selected tab and closing restores previous focus (including #input when ask box was open)", JSON.stringify(foc));
}

// 12. setEl keydown isolation: Enter, Space, typing and Ctrl+N/H/M inside Settings do not reach showAsk, PTT or global shortcuts; Esc and Ctrl+, still reach window
{ const iso = await ev(`settings(true,'plugins');
    const tabBtn=document.querySelector('#tabs button.on'), reloadBtn=document.getElementById('plugReload');
    for(const el of [tabBtn, reloadBtn]){
      el.focus();
      for(const [k,code,ctrl] of [['Enter','Enter',false],[' ','Space',false],['a','KeyA',false],['n','KeyN',true],['h','KeyH',true]]){
        el.dispatchEvent(new KeyboardEvent('keydown',{key:k,code,ctrlKey:ctrl,bubbles:true,cancelable:true}));
      }
    }
    const during=[setEl.classList.contains('on'), ask.classList.contains('on'), panelEl.classList.contains('on'), !!rec, spaceHeld];
    // Esc inside setEl still bubbles to window and closes Settings
    reloadBtn.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true,cancelable:true}));
    const afterEsc=setEl.classList.contains('on');
    // Ctrl+, bubbles to window
    let ctrlCommaBubbled=false;
    const h=e=>{ if(e.ctrlKey&&e.key===',') ctrlCommaBubbled=true; };
    window.addEventListener('keydown',h,{once:true});
    settings(true,'look');
    document.querySelector('#tabs button.on').dispatchEvent(new KeyboardEvent('keydown',{key:',',ctrlKey:true,bubbles:true,cancelable:true}));
    window.removeEventListener('keydown',h);
    settings(false);
    return {during, afterEsc, ctrlCommaBubbled}`);
  check(iso.during[0] === true && iso.during[1] === false && iso.during[2] === false && iso.during[3] === false && iso.during[4] === false
    && iso.afterEsc === false && iso.ctrlCommaBubbled === true,
    "Enter, Space, typing and shortcuts inside Settings are isolated; Esc and Ctrl+, still work", JSON.stringify(iso));
}

// 13. Radial-menu item and openPanel('plugins') title are "Claude Code plug-ins"
{ const lbl = await ev(`const mb=document.querySelector('#menu .mb[data-a="plugins"]');
    const menuTitle=mb?.getAttribute('title'), menuSpan=mb?.querySelector('span')?.textContent;
    await openPanel('plugins');
    const pTitle=document.getElementById('pTitle').textContent;
    closePanels();
    return {menuTitle, menuSpan, pTitle}`);
  check(lbl.menuTitle === "Claude Code plug-ins" && lbl.menuSpan === "Claude Code plug-ins" && lbl.pTitle === "Claude Code plug-ins",
    "radial menu and openPanel('plugins') title use 'Claude Code plug-ins'", JSON.stringify(lbl));
}

// #175 live evidence: consent card open + 6 plugins + a long settings path — nothing clipped, rows don't overlap, switches line up
{ await ev("settings(true,'plugins'); return 1"); await sleep(200);
  const long = "/home/someone/.config/nixi-companion/plugin-config/" + "very-long-folder-name/".repeat(4) + "news.json";
  const items = Array.from({ length: 6 }, (_, i) => ({ id: "p-" + i, name: "Plugin " + i, version: "1.0.0", source: i % 2 ? "Nix" : "Folder", enabled: i % 2 === 0,
    caps: ["Runs a program when you ask for it and uses the network", "Can read your system status"], error: "", config: i === 0 ? long : "", config_note: "" }));
  const r = await ev(`plugRender(${JSON.stringify({ items })}); plugConsent({id:'p-0',name:'Nix status',sha256:'x',network:true,what:'${"Shows a live board of this machine. ".repeat(6)}',hint:'system status',runs:'run',reads:['system-status'],config:''});
    const pre=document.querySelector('#plugCons pre'), rows=[...document.querySelectorAll('#plugList label.tg')].map(l=>l.getBoundingClientRect()),
      sw=[...document.querySelectorAll('#plugList label.tg')].map(l=>[l.querySelector('.sw').getBoundingClientRect().top,l.querySelector('.l').getBoundingClientRect().top]);
    return [pre.scrollHeight<=pre.clientHeight+1, rows.every((b,i)=>i===0||b.top>=rows[i-1].bottom-1), sw.every(([a,b])=>Math.abs(a-b)<=6), rows.every(b=>b.width>0)]`);
  check(r.every(Boolean), "plugins: consent text fully shown, rows don't overlap, switches line up with long paths", JSON.stringify(r));
  await ev("plugConsent(null); settings(false); return 1"); }

// 14. A corner drag updates wanted size, coalesces size requests, persists, and expands the click region.
{ await view(900, 900); await ev("settings(true); info.click_through=true; return 1"); await sleep(450);
  // Right edge strip (.sgrip.r) and #set .bd scrollbar do not overlap
  const sb = await ev(`const bd=setEl.querySelector('.bd'), gr=setEl.querySelector('.sgrip.r');
    const br=bd.getBoundingClientRect(), grr=gr.getBoundingClientRect();
    return {bdRight:Math.round(br.right), gripLeft:Math.round(grr.left), gripRight:Math.round(grr.right), noOverlap:br.right<=grr.left}`);
  check(sb.noOverlap, "right resize strip (.sgrip.r) does not overlap #set .bd scrollbar", JSON.stringify(sb));

  await clearMsgs();
  const drag = await ev(`const g=document.querySelector('#set .sgrip.corner'); let captured=false;
    g.setPointerCapture=()=>{ captured=true; };
    const pointer=(type,x,y,buttons=type==='pointerup'?0:1)=>g.dispatchEvent(new PointerEvent(type,{pointerId:7,button:0,buttons,clientX:x,clientY:y,bubbles:true,cancelable:true}));
    pointer('pointerdown',560,680); pointer('pointermove',600,710); pointer('pointermove',640,750);
    const before=__msgs.filter(m=>m.startsWith('size:')).length;
    pointer('pointerup',640,750);
    await new Promise(requestAnimationFrame);
    const r=setEl.getBoundingClientRect(), msg=[...__msgs].reverse().find(m=>m.startsWith('region:'));
    return {captured,before, sizes:__msgs.filter(m=>m.startsWith('size:')), w:setW,h:setH,
      css:[setEl.style.getPropertyValue('--setW'),setEl.style.getPropertyValue('--setH')],
      saved:JSON.parse(localStorage.getItem('nixi.setSize')),
      covers:JSON.parse(msg.slice(7)).some(([x,y,w,h])=>x<=r.left&&y<=r.top&&x+w>=r.right&&y+h>=r.bottom)}`);
  check(drag.captured && drag.before===0 && drag.sizes.length===1 && drag.w===640 && drag.h===750
    && drag.css[0]==='640px' && drag.css[1]==='750px' && JSON.stringify(drag.saved)==='[640,750]' && drag.covers,
    "corner drag changes wanted/CSS size, one size per frame, saves, and updates region", JSON.stringify(drag));

  // Resize drag does not feed back when the window moves left/up (nixiLayout(L+d, T+d) + clientX+d / clientY+d keeps size unchanged)
  const noFeedback = await ev(`const g=document.querySelector('#set .sgrip.corner'); g.setPointerCapture=()=>{};
    nixiLayout(100, 80);
    const p=(type,x,y,buttons=type==='pointerup'?0:1)=>g.dispatchEvent(new PointerEvent(type,{pointerId:11,button:0,buttons,clientX:x,clientY:y,bubbles:true}));
    p('pointerdown',500,600);
    p('pointermove',540,630);
    const after1=[setW,setH];
    nixiLayout(100+40, 80+30);
    p('pointermove',540+40,630+30);
    const after2=[setW,setH];
    p('pointerup',580,660);
    nixiLayout(0,0);
    return {after1,after2}`);
  check(noFeedback.after1[0]===680 && noFeedback.after1[1]===780 && noFeedback.after2[0]===noFeedback.after1[0] && noFeedback.after2[1]===noFeedback.after1[1],
    "resize drag in layout-offset frame: nixiLayout(L+d,T+d) with clientX+d/clientY+d leaves size unchanged", JSON.stringify(noFeedback));

  const min = await ev(`const g=document.querySelector('#set .sgrip.corner');
    const p=(type,x,y,buttons=type==='pointerup'?0:1)=>g.dispatchEvent(new PointerEvent(type,{pointerId:8,button:0,buttons,clientX:x,clientY:y,bubbles:true}));
    p('pointerdown',640,750); p('pointermove',-100,-100); p('pointerup',-100,-100);
    return [setW,setH,JSON.parse(localStorage.getItem('nixi.setSize'))]`);
  check(min[0]===420 && min[1]===420 && JSON.stringify(min[2])==='[420,420]',
    "drag clamps both axes to 420", JSON.stringify(min));

  const edges = await ev(`const drag=(axis,id,dx,dy)=>{ const g=document.querySelector('#set .sgrip.'+axis); g.setPointerCapture=()=>{};
      const p=(type,x,y,buttons=type==='pointerup'?0:1)=>g.dispatchEvent(new PointerEvent(type,{pointerId:id,button:0,buttons,clientX:x,clientY:y,bubbles:true}));
      p('pointerdown',0,0); p('pointermove',dx,dy); p('pointerup',dx,dy); };
    drag('r',9,80,90); const right=[setW,setH]; drag('b',10,90,80);
    return {right,bottom:[setW,setH]}`);
  check(JSON.stringify(edges.right)==='[500,420]' && JSON.stringify(edges.bottom)==='[500,500]',
    "right and bottom strips resize only their own axes", JSON.stringify(edges));

  // Grip robustness: click without movement does not save; pointermove with buttons===0 is ignored; lostpointercapture ends drag
  const robust = await ev(`const g=document.querySelector('#set .sgrip.corner'); g.setPointerCapture=()=>{};
    localStorage.removeItem('nixi.setSize');
    const p=(type,x,y,buttons=1)=>g.dispatchEvent(new PointerEvent(type,{pointerId:12,button:0,buttons,clientX:x,clientY:y,bubbles:true}));
    p('pointerdown',200,200,1); p('pointerup',200,200,0);
    const savedAfterClick=localStorage.getItem('nixi.setSize');
    p('pointerdown',200,200,1); p('pointermove',260,260,0);
    const afterButtons0=[setW,setH];
    p('pointermove',250,240,1);
    const afterMove=[setW,setH];
    g.dispatchEvent(new PointerEvent('lostpointercapture',{pointerId:12,bubbles:true}));
    const savedAfterLost=JSON.parse(localStorage.getItem('nixi.setSize'));
    p('pointermove',350,350,1);
    const afterLostMove=[setW,setH];
    return {savedAfterClick,afterButtons0,afterMove,savedAfterLost,afterLostMove}`);
  check(robust.savedAfterClick===null && JSON.stringify(robust.afterButtons0)==='[500,500]'
    && JSON.stringify(robust.afterMove)==='[550,540]' && JSON.stringify(robust.savedAfterLost)==='[550,540]'
    && JSON.stringify(robust.afterLostMove)==='[550,540]',
    "grip robustness: click does not save, buttons===0 move ignored, lostpointercapture ends drag", JSON.stringify(robust));

  const keys = await ev(`const g=document.querySelector('#set .sgrip.corner'); g.focus();
    const key=(k,shift=false)=>{ const e=new KeyboardEvent('keydown',{key:k,shiftKey:shift,bubbles:true,cancelable:true}); g.dispatchEvent(e); return e.defaultPrevented; };
    const right=key('ArrowRight'), down=key('ArrowDown',true), grown=[setW,setH];
    const enter=key('Enter'), reset=[setW,setH,localStorage.getItem('nixi.setSize'),setEl.classList.contains('on'),ask.classList.contains('on')];
    key('ArrowLeft'); g.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));
    return {right,down,enter,grown,reset,dbl:[setW,setH,localStorage.getItem('nixi.setSize')]}`);
  check(keys.right && keys.down && keys.enter && JSON.stringify(keys.grown)==='[566,604]'
    && JSON.stringify(keys.reset)==='[560,680,null,true,false]' && JSON.stringify(keys.dbl)==='[560,680,null]',
    "arrows prevent scroll and resize; Enter and double-click reset without closing", JSON.stringify(keys));

  await ev(`settings(false); localStorage.setItem('nixi.setSize','[900,850]'); setW=0; setH=0; return 1`);
  await view(440,520); await ev("settings(true); return 1"); await sleep(450);
  const saved = await ev(`const r=setEl.getBoundingClientRect(); return [setW,setH,Math.round(r.width),Math.round(r.height),localStorage.getItem('nixi.setSize')]`);
  check(JSON.stringify(saved)==='[900,850,416,474,"[900,850]"]',
    "saved size opens CSS-clamped while storage and wanted size stay intact", JSON.stringify(saved));
  await ev("settings(false); localStorage.removeItem('nixi.setSize'); setW=0; setH=0; return 1"); await view(340,460);
}

// #187: the weather cloud moves aside while a notification mark shows, and comes back after
{ const dx = () => ev("return Math.abs(+(/translate\\((-?[\\d.]+)/.exec(wxEl.getAttribute('transform'))||[0,0])[1])+''").then(Number);
  const until = async (ok, ms = 4000) => { const t0 = Date.now(); let v = await dx(); while (!ok(v) && Date.now() - t0 < ms) { await sleep(100); v = await dx(); } return v; };
  await ev("for(const k of ['snow','clear','partly','cloudy']) sitOn[k]=false; sitOn.rain=true; return 1"); await sleep(300);
  await ev("agentMark('claude','ask'); return 1");
  const out = await until(v => v > 80);
  const on = await ev("const a=wxEl.getBoundingClientRect(), b=document.querySelector('#agentMark').getBoundingClientRect(); return [a.left, b.right]");
  check(out > 80 && on[0] >= on[1] - 1, "weather: the cloud stands clear of the notification mark", JSON.stringify([out, on]));
  await ev("AM.until=0; AM=null; renderCue(); return 1");
  const back = await until(v => v < 12);
  const another = await ev("return wxAside(performance.now())");   // (an ambient cue can legitimately appear in the test: then it rightly stays aside)
  check(back < 12 || another, "weather: the cloud comes back when the mark goes", JSON.stringify([back, another]));
  // (Codex: only the sun shows on a clear day and it doesn't overlap; the situation logic resets sitOn, so ask the rule directly)
  // with a hat the cloud is already left of the marks: +90 would put it on them (Codex, PR #44; LOOK.skin, because the situation logic resets sitOn)
  const hatted = await ev("const was=LOOK.skin; LOOK.skin='halo'; AM={from:'claude',kind:'ask',t0:0,until:performance.now()+9000}; await new Promise(r=>setTimeout(r,1500)); const dx=Number(wxEl.getAttribute('transform').match(/translate\\(([-\\d.]+)/)[1]); AM=null; LOOK.skin=was; return dx");
  check(hatted < 12, "weather: with a hat the cloud stays left of the marks", String(hatted));
  // heavy rain's small extra clouds land on the marks once the sky has moved aside (Codex, PR #44), so they go while a mark is up
  const extras = await ev("const skies=['snow','rain','clear','partly','cloudy'].map(k=>[k,sitOn[k]]), wasH=SIT.heavy, wasL=lowFx, wasOn=wxOn; skies.forEach(([k])=>sitOn[k]=k==='rain'); SIT.heavy=true; lowFx=false; const shown=on=>{ wxOn=on; wxStep(1,1); const op=+(WX.ex[0].getAttribute('opacity')||0), d=WX.ex[0].getAttribute('display'); return d!=='none'&&op>0; }; const a=shown(false), b=shown(true); skies.forEach(([k,v])=>sitOn[k]=v); SIT.heavy=wasH; lowFx=wasL; wxOn=wasOn; return [a,b]");
  check(extras[0] === true && extras[1] === false, "weather: heavy rain's small clouds leave while a mark is up", JSON.stringify(extras));
  const clear = await ev("sitOn.clear=true; AM={from:'claude',kind:'ask',t0:0,until:performance.now()+9000}; const r=wxAside(performance.now()); AM=null; sitOn.clear=false; return r");
  check(clear === false, "weather: a clear sky stays put under a mark", String(clear));
  await ev("sitOn.rain=false; renderCue(); return 1"); }
// Two-click bug (live on p620): the REAL path. Right-click him, click the gear, with a fake window that really grows and moves.
{ await view(340, 460);
  await ev(`closePanels(); menu(false);
    window.__log=[]; const stamp=m=>__log.push(Math.round(performance.now())+' '+m);
    new MutationObserver(()=>stamp('set.on='+setEl.classList.contains('on'))).observe(setEl,{attributes:true,attributeFilter:['class']});
    new MutationObserver(()=>stamp('menu='+document.body.classList.contains('menu'))).observe(document.body,{attributes:true,attributeFilter:['class']});
    for(const n of ['mousedown','mouseup','click','contextmenu']) addEventListener(n,e=>stamp(n+' on '+(e.target.id||e.target.className||e.target.tagName)),true);
    const op=closePanels; return 1`);
  const mouse = async (type, x, y, button = "left", clickCount = 1) => send("Input.dispatchMouseEvent", { type, x, y, button, clickCount, buttons: type === "mouseReleased" ? 0 : (button === "left" ? 1 : 2) });
  const click = async (x, y, button = "left") => { await mouse("mouseMoved", x, y, "none", 0); await mouse("mousePressed", x, y, button); await mouse("mouseReleased", x, y, button); };
  // the fake window: answer a size: request as window.py does (grow, then tell the page how far he moved)
  const pump = setInterval(async () => { try {
    const m = await ev("const a=__msgs.filter(x=>x.startsWith('size:')); __msgs.length=0; return a.length?a[a.length-1]:''");
    if (m) { const [w, h] = m.slice(5).split(",").map(Number), L = Math.ceil(w / 2);
      await view(340 + w, 460 + h); await ev(`nixiLayout(${w ? L : 0},0); return 1`); } } catch (e) {} }, 40);
  const b = await ev("const r=document.getElementById('body').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]");
  await click(b[0], b[1], "right"); await sleep(700);
  const g = await ev("const r=document.querySelector('#menu .mb[data-a=set]').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2, r.width, document.body.classList.contains('menu')]");
  await click(g[0], g[1]); await sleep(1500);
  const after = await ev("return [setEl.classList.contains('on'), getComputedStyle(setEl).opacity, getComputedStyle(setEl).visibility, Math.round(setEl.getBoundingClientRect().width), __log]");
  clearInterval(pump);
  check(after[0] === true && +after[1] > .5 && after[3] > 400, "gear: one click opens Settings, and it stays open", JSON.stringify(after.slice(0, 4)));
  await ev("closePanels(); return 1"); await view(340, 460); }

// #175: a feature refused with 403 must not reload the page (that lost the open panel); only a refused token asks for a new one
{ const r = await ev(`const of=window.fetch; let body='{"error":"off in nixi mode"}';
    window.fetch=(u,o)=>String(u)==='/x403'?Promise.resolve(new Response(body,{status:403})):of(u,o);
    try{ sessionStorage.removeItem('nixi-reload'); __msgs.length=0; await post('/x403'); await new Promise(r=>setTimeout(r,80));
      const off=__msgs.includes('reauth'); sessionStorage.removeItem('nixi-reload'); body='{"error":"forbidden"}'; __msgs.length=0;
      await post('/x403'); await new Promise(r=>setTimeout(r,80)); const tok=__msgs.includes('reauth'); return [off,tok]; }
    finally{ window.fetch=of; sessionStorage.removeItem('nixi-reload'); }`);
  check(r[0] === false && r[1] === true, "a 403 that isn't about the token doesn't reload the page", JSON.stringify(r)); }

// #208: the Reactions switch: off by default, disabled while Proactive is off, saves, help names the signal switches that are off
{ await ev("await post('/api/settings',{proactive:false,reactions:false}).then(r=>r.json()).then(j=>{info=j;}); settings(true); renderSettings(); return 1");
  const q = "const e=document.getElementById('reactSw'); return [e.checked, e.disabled, document.getElementById('reactHelp').textContent]";
  const a = await ev(q);
  check(a[0] === false && a[1] === true && /Silent\./.test(a[2]) && /Headphones for music/.test(a[2]), "Reactions: off by default, disabled without Proactive, help names the switches that are off", JSON.stringify(a));
  await ev("await setSetting({proactive:true}); renderSettings(); return 1");
  const b = await ev(q);
  check(b[1] === false, "Reactions: enabled once Proactive is on", JSON.stringify(b));
  await ev("document.getElementById('reactSw').click(); await new Promise(r=>setTimeout(r,500)); return 1");
  const c = await ev("return [info.reactions, document.getElementById('reactSw').checked]");
  check(c[0] === true && c[1] === true, "Reactions: the switch saves", JSON.stringify(c));
  await ev("await post('/api/settings',{proactive:false,reactions:false}); settings(false); return 1"); }

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
