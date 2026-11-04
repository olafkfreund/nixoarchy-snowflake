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
    && !st2[0] && st2[1] && st2[2] === 0 && st2[3] === 0 && st2[4] && lastWide(m2) === "wide:on" && lastSize(m2) === "size:0,0"
    && !st3[0] && !st3[1] && st3[2] === 0 && st3[3] === 0 && !st3[4] && lastWide(m3) === "wide:off" && lastSize(m3) === "size:0,0",
    "transition: Settings -> panel -> close", JSON.stringify({ m1, m2, st2, m3, st3 }));
}

// 6b.Settings -> Memory/History via data-open button inside Settings (line 3361) -> close
{ for (const kind of ["memory", "history"]) {
    await ev("settings(true,'more'); return 1");
    await clearMsgs();
    await ev(`setEl.querySelector('[data-open="${kind}"]').click(); await new Promise(r=>setTimeout(r,150)); return 1`);
    const m = nonRegion(await msgs());
    const st = await ev("return [setEl.classList.contains('on'), panelEl.classList.contains('on'), panelKind, setWant[0], setWant[1]]");
    check(!st[0] && st[1] && st[2] === kind && st[3] === 0 && st[4] === 0 && lastWide(m) === "wide:on" && lastSize(m) === "size:0,0" && !m.includes("wide:off"),
      `transition: Settings -> ${kind} (data-open) goes straight to wide:on without wide:off`, JSON.stringify({ m, st }));
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
  check(st1[0] && !st1[1] && st1[2] && st1[3] === 244 && st1[4] === 266 && lastWide(m1) === "wide:off" && lastSize(m1) === "size:244,266"
    && !st2[0] && !st2[1] && st2[2] === 0 && st2[3] === 0 && !st2[4] && lastWide(m2) === "wide:off" && lastSize(m2) === "size:0,0",
    "transition: Quick actions (#qaEditBtn) -> Settings -> ✕ close", JSON.stringify({ m1, st1, m2, st2 }));
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

// 6g. Stage card open: map card's Settings button collapses stage to tab (stageHide(true), stageWant=[300,0]) and opens Settings; closing Settings returns to the tab's want (size:300,0)
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
    && lastSize(mOpen) === "size:300,266" && lastWide(mOpen) === "wide:off"
    && stClose[0] === "tab" && stClose[1] === 300 && !stClose[2] && stClose[3] === 0 && stClose[4] === 0
    && lastSize(mClose) === "size:300,0" && lastWide(mClose) === "wide:off",
    "transition: map stage Settings button collapses stage to tab (stageHide(true)) and closing Settings returns to size:300,0",
    JSON.stringify({ mOpen, stOpen, mClose, stClose }));
  await ev("stageClose(); await new Promise(r=>setTimeout(r,260)); return 1");
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

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
