// The answer-stage frame (#144) fits the window the page asks for, shows markup as text, and stays still for reduced motion.
//   node tests/stages_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). The window is simulated: the page asks for stageWant[0] extra width, the real
// window then grows by that much split round Nixi (all to the right at the left screen edge, half each side in the
// middle, all to the left at the right edge), so each case sets the viewport to 340+want and tells the page how far
// he moved (nixiLayout). Exit 0 = pass.
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
const view = (w, h = 460) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
await send("Page.enable");
await view(340);
await send("Page.navigate", { url }); await sleep(4500);
await ev("setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full'); return 1");

const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const long = "x".repeat(120);
const FIX = {
  "commands (mechanic)": { t: "stage", v: 1, kind: "commands", trust: "mechanic", title: "Install Firefox", items: [{ label: "Install it", cmd: "nix profile install nixpkgs#firefox", token: "t1" }, { label: "Or just try it", cmd: "nix run nixpkgs#firefox", token: "t2" }] },
  "commands (guide)": { t: "stage", v: 1, kind: "commands", trust: "guide", items: [{ label: "Install it", cmd: "nix profile install nixpkgs#firefox", token: "t1" }] },
  "commands (yolo)": { t: "stage", v: 1, kind: "commands", trust: "yolo", items: [{ label: "List", cmd: "ls -la", token: "t1" }] },
  "commands (5 long)": { t: "stage", v: 1, kind: "commands", trust: "mechanic", title: long, items: Array.from({ length: 5 }, (_, i) => ({ label: long, cmd: "c".repeat(500), token: "t" + i })) },
  "place": { t: "stage", v: 1, kind: "place", trust: "mechanic", dest: long + long, mode: "walking", open: "o1", copy: "c1" },
  "facts": { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: "Tides", token: "f1", points: ["Two highs a day", "Two lows a day", "Springs at new moon"], source: "NOAA" },
  "facts (5 long)": { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: long, token: "f1", points: Array.from({ length: 5 }, () => long), source: long },
};
const show = async (fx, ox) => {                       // the frame as drawn once the window has grown the way the page asked
  await ev(`stageClose(); await new Promise(r=>setTimeout(r,320)); onEvent(${JSON.stringify(fx)}); return 1`);
  await sleep(60);
  const want = await ev("return stageWant[0]");
  await view(340 + want);
  await ev(`window.nixiLayout(${ox(want)},0); return 1`);
  await sleep(700);
  return { want, box: await ev(`const r=document.getElementById('stg').getBoundingClientRect(); return [r.left,r.top,r.right,r.bottom,innerWidth,innerHeight]`) };
};
const POS = { "Nixi at the left edge": w => 0, "Nixi in the middle": w => w / 2, "Nixi at the right edge": w => w };
for (const [pn, ox] of Object.entries(POS)) for (const [fn, fx] of Object.entries(FIX)) {
  const { want, box } = await show(fx, ox), [l, tp, r, b, W, H] = box, strip = [ox(want), ox(want) + 340];
  const inside = l >= 0 && r <= W && tp >= 0 && b <= H, clear = r <= strip[0] || l >= strip[1];
  check(want > 0 && inside && clear, `${fn} / ${pn}`, `box ${[l, tp, r, b].map(v => v.toFixed(0))} in ${W}x${H}, Nixi ${strip}`);
}

// markup in a field is text
{ await show({ ...FIX.facts, title: "<b>x</b>", points: ["<b>y</b>", "<img src=x onerror=window.__pwn=1>"], source: "<i>s</i>" }, w => 0);
  const r = await ev(`const f=document.getElementById('stg'); return [f.querySelectorAll('b,i,img').length, document.getElementById('stgT').textContent, f.textContent.includes('<b>y</b>'), !!window.__pwn]`);
  check(r[0] === 0 && r[1] === "<b>x</b>" && r[2] && !r[3], "markup shows as text", JSON.stringify(r));
  await show({ ...FIX["commands (mechanic)"], items: [{ label: "<b>l</b>", cmd: "echo '<b>c</b>'", token: "t1" }] }, w => 0);
  const c = await ev(`const f=document.getElementById('stg'); return [f.querySelectorAll('b').length, f.querySelector('code').textContent]`);
  check(c[0] === 0 && c[1] === "echo '<b>c</b>'", "command markup shows as text", JSON.stringify(c)); }

// the map: fixed footnote, two buttons, the destination as text, a hat; the trail is drawn by dashoffset only under motion
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await show({ ...FIX.place, dest: "<b>Oslo</b>" }, w => 0);
  const m = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('map'), f.querySelectorAll('b').length, f.querySelector('.dst').textContent, document.getElementById('stgFn').textContent, [...f.querySelectorAll('.sb')].map(b=>b.textContent), document.getElementById('stgT').textContent, document.getElementById('hat').classList.contains('on'), getComputedStyle(f.querySelector('.tm')).animationName, getComputedStyle(f).fontFamily.length>0]`);
  check(m[0] && m[1] === 0 && m[2] === "<b>Oslo</b>" && /^A sketch, not the route/.test(m[3]) && m[4].join() === "Open in Google Maps,Copy address" && m[5] === "Trip preview" && m[6] && m[7] === "stgTrail", "map set", JSON.stringify(m));
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
  await show(FIX.place, w => 0);
  const r2 = await ev(`return getComputedStyle(document.querySelector('#stg .tm')).animationName`);
  check(r2 === "none", "map: trail still under reduced motion", r2);
  await send("Emulation.setEmulatedMedia", { features: [] }); }

// trust notes and Run
{ for (const [k, run, note] of [["commands (guide)", false, /Guide doesn't run commands/], ["commands (mechanic)", true, /Mechanic/], ["commands (yolo)", true, /YOLO/]]) {
    await show(FIX[k], w => 0);
    const r = await ev(`return [[...document.querySelectorAll('#stg .sb')].find(b=>b.textContent==='Run').disabled, document.getElementById('stgFn').textContent]`);
    check(r[0] === !run && note.test(r[1]), `Run and its note: ${k}`, JSON.stringify(r)); } }

// a refused command shows its message on the running item (with the token, and without it)
{ await show(FIX["commands (mechanic)"], w => 0);
  const r = await ev(`stageStatus({token:'t2',state:'running'}); stageStatus({token:'t2',state:'other'}); const a=document.querySelectorAll('#stg .st')[1].textContent;
    stageStatus({token:'t1',state:'running'}); stageStatus({state:'other'}); return [a, document.querySelectorAll('#stg .st')[0].textContent, document.querySelectorAll('#stg .st')[1].textContent]`);
  const m = "Nixi tried to run something else — stopped.";
  check(r[0] === m && r[1] === m && r[2] === m, "'other' shows on the running item", JSON.stringify(r)); }

// ← only when there is an earlier stage to go back to
{ await show(FIX["commands (mechanic)"], w => 0);
  const a = await ev("return document.getElementById('stgBack').hidden");
  await show({ ...FIX["commands (mechanic)"], has_prev: true }, w => 0);
  const b = await ev("return document.getElementById('stgBack').hidden");
  check(a === true && b === false, "back button only with has_prev", JSON.stringify([a, b])); }

// a stage the page can't show now (fullscreen) is not lost: it becomes caption text
{ await ev("stageClose(); await new Promise(r=>setTimeout(r,320)); SIT.fullscreen=true; himSet(''); return 1");
  for (const [k, want] of [["commands (mechanic)", ["1. Install it: nix profile install nixpkgs#firefox", "2. Or just try it: nix run nixpkgs#firefox"]], ["facts", ["Tides", "Two highs a day", "Source: NOAA"]]]) {
    await ev(`himSet(''); onEvent(${JSON.stringify(FIX[k])}); await new Promise(r=>setTimeout(r,500)); return 1`);
    const r = await ev("return [stgState, document.getElementById('stg').classList.contains('on'), document.getElementById('him').textContent.replace(/\\s+/g,' ')]");
    check(r[0] === "closed" && !r[1] && want.every(w => r[2].includes(w)), `declined stage becomes a caption: ${k}`, JSON.stringify(r)); }
  await ev("SIT.fullscreen=false; himSet(''); return 1"); }

// what the page tells the server about visibility, inertness, and the window's keys
await ev("window.__acts=[]; const of=window.fetch; window.fetch=(u,o)=>{ if(String(u).includes('/api/stage/act')) __acts.push(JSON.parse(o.body).act); return of(u,o); }; return 1");
const acts = () => ev("return __acts.slice()");
{ await ev("stageClose(); await new Promise(r=>setTimeout(r,320)); __acts.length=0; return 1");
  await show(FIX["commands (mechanic)"], w => 0);
  check((await acts()).includes("shown"), "a drawn stage reports shown", JSON.stringify(await acts()));
  const i0 = await ev("return [document.getElementById('stg').inert, document.getElementById('stgTab').inert]");
  check(i0[0] === false && i0[1] === true, "open: frame live, tab inert", JSON.stringify(i0));
  // Enter and Space on a focused stage button don't reach the window's shortcuts (ask box, recording)
  const k = await ev(`const b=document.querySelector('#stg .sb'); b.focus(); let ran=0; b.addEventListener('click',()=>ran++);
    for(const key of ['Enter',' ']) b.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
    await new Promise(r=>setTimeout(r,200)); return [ask.classList.contains('on'), !!rec]`);
  check(k[0] === false && k[1] === false, "Enter/Space in a stage button don't trigger window shortcuts", JSON.stringify(k));
  // Settings open (body.calm) hides the frame: say so, and say shown again when it is back
  await ev("__acts.length=0; setEl.classList.add('on'); await new Promise(r=>setTimeout(r,1000)); return 1");
  const a1 = await acts();
  await ev("setEl.classList.remove('on'); await new Promise(r=>setTimeout(r,1000)); return 1");
  const a2 = await acts();
  check(a1.at(-1) === "hidden" && a2.at(-1) === "shown", "calm reports hidden, then shown", JSON.stringify([a1, a2]));
  // a stage that arrives while calm is a caption, not a frame, and the old frame is put away locally (no close sent)
  await ev("__acts.length=0; himSet(''); setEl.classList.add('on'); await new Promise(r=>setTimeout(r,500)); return 1");
  await ev(`onEvent(${JSON.stringify(FIX["facts"])}); await new Promise(r=>setTimeout(r,500)); return 1`);
  const d = await ev("return [stgState, stgTimer, document.getElementById('stg').inert, document.getElementById('him').textContent.replace(/\\s+/g,' ').includes('Two highs a day')]");
  const a3 = await acts();
  await ev("setEl.classList.remove('on'); await new Promise(r=>setTimeout(r,800)); return 1");
  check(d[0] === "closed" && d[1] === null && d[2] === true && d[3] && !a3.includes("close") && !a3.includes("shown"), "declined replacement: old frame gone locally, no close, no shown", JSON.stringify([d, a3]));
  // shrunk to the tab: the frame is inert and the tab is live; restoring flips it back
  await show(FIX["commands (mechanic)"], w => 0);
  const t1 = await ev("stageHide(true); await new Promise(r=>setTimeout(r,300)); return [document.getElementById('stg').inert, document.getElementById('stgTab').inert]");
  await ev("stageRestore(); await new Promise(r=>setTimeout(r,400)); return 1");
  const t2 = await ev("return [document.getElementById('stg').inert, document.getElementById('stgTab').inert]");
  check(t1[0] === true && t1[1] === false && t2[0] === false && t2[1] === true, "tab state is inert-correct both ways", JSON.stringify([t1, t2])); }

// motion: the flourish runs normally, and not at all under reduced motion
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await show(FIX["commands (mechanic)"], w => 0);
  const on = await ev(`return [document.getElementById('stg').classList.contains('go'), getComputedStyle(document.querySelector('#stg .ul path')).animationName, getComputedStyle(document.getElementById('chalk')).display]`);
  check(on[0] && on[1] === "stgUl" && on[2] !== "none", "flourish runs by default", JSON.stringify(on));
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await sleep(200);
  await show(FIX["commands (mechanic)"], w => 0);
  const off = await ev(`return [document.getElementById('stg').classList.contains('go'), getComputedStyle(document.querySelector('#stg .ul path')).animationName, getComputedStyle(document.getElementById('chalk')).display, document.querySelectorAll('#stg .it.pt').length, getComputedStyle(document.getElementById('stg')).transform]`);
  check(!off[0] && off[1] === "none" && off[2] === "none" && off[3] === 0 && (off[4] === "none" || off[4] === "matrix(1, 0, 0, 1, 0, 0)"), "reduced motion: a fade only", JSON.stringify(off));
  await send("Emulation.setEmulatedMedia", { features: [] }); }

await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
