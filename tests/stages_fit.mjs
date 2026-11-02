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
