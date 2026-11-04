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
let id = 0; const pend = new Map(), reqs = [];
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } if (m.method === "Network.requestWillBeSent") reqs.push(m.params?.request?.url || ""); });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => { const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
const view = (w, h = 460) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
await send("Page.enable"); await send("Network.enable");
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
  "video": { t: "stage", v: 1, kind: "video", trust: "mechanic", query: "<b>cats</b>", search: "s1", items: [1, 2, 3].map(i => ({ title: long, channel: "Chan", duration: "3:0" + i, play: "p" + i, thumb: "h" + i })) },
  "video (failed)": { t: "stage", v: 1, kind: "video", trust: "mechanic", query: "cats", search: "s1", items: [] },
  "weather": { t: "stage", v: 1, kind: "weather", source: "open-meteo", sky: "rain", heavy: true, temp: 4, feel: 1, wind: 14, dir: "SW", at: "14:32", day: true },
  "weather (empty)": { t: "stage", v: 1, kind: "weather", empty: true },
  "calendar": { t: "stage", v: 1, kind: "calendar", open: "o1", at: "09:55", events: [{ when: "10:40", title: long, join: "j1" }, ...[1, 2, 3].map(i => ({ when: "Wed 1" + i + ":00", title: long, join: i === 2 ? undefined : "j" + (i + 1) }))] },
  "calendar (off)": { t: "stage", v: 1, kind: "calendar", open: "o1", off: true, events: [] },
  "calendar (empty)": { t: "stage", v: 1, kind: "calendar", open: "o1", at: "09:55", events: [] },
  "status": { t: "stage", v: 1, kind: "status", term: "t0", sys_on: true, failed: Array.from({ length: 5 }, (_, i) => "unit-" + i + ".service"), failed_n: 7, sessions: Array.from({ length: 5 }, (_, i) => ({ title: long, status: "working", open: "s" + i })) },
  "status (empty)": { t: "stage", v: 1, kind: "status", term: "t0", sys_on: false, failed: [], failed_n: 0, sessions: [] },
  "day (full)": { t: "stage", v: 1, kind: "day", wd: "Wednesday", md: "28 Sep", at: "09:55", cal: "ok", next: { when: "10:40", title: long, in: "in 45 min", open: "n1", join: "j1" },
    rows: [["today", "Today", 12, "ok", "14:00", false], ["tasks", "Tasks", 9, "ok", "overdue", true], ["github", "GitHub", 11, "ok", "some-long-repository-name#1234", false]].map(([key, label, n, st, when, bad]) =>
      ({ key, label, n, st, items: Array.from({ length: 8 }, (_, i) => ({ when, title: long, bad: bad && i < 2, open: "o" + key + i })) })) },
  "day (stale and off)": { t: "stage", v: 1, kind: "day", wd: "Wednesday", md: "28 Sep", at: "09:55", cal: "stale@09:30", next: { when: "10:40", title: "Stand-up", in: "in 45 min", open: null, join: null },
    rows: [{ key: "today", label: "Today", n: 1, st: "stale@09:30", items: [{ when: "all day", title: "Release day", open: "o1" }] }, { key: "tasks", label: "Tasks", n: 0, st: "stale@09:55", items: [] }, { key: "github", label: "GitHub", n: 0, st: "off", items: [] }] },
  "day (empty)": { t: "stage", v: 1, kind: "day", wd: "Sunday", md: "1 Jan", at: "09:55", cal: "ok", next: null, rows: ["today", "tasks", "github"].map(key => ({ key, label: key, n: 0, st: "ok", items: [] })) },
  "facts": { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: "Tides", token: "f1", points: ["Two highs a day", "Two lows a day", "Springs at new moon"], source: "NOAA" },
  "facts (5 long)": { t: "stage", v: 1, kind: "facts", trust: "mechanic", title: long, token: "f1", points: Array.from({ length: 5 }, () => long), source: long },
  "gauges": { t: "stage", v: 1, kind: "gauges", title: "System status", source: "p620", live: true, token: "c1", refresh: "r1", hosts: [{ name: "p620", state: "up", badges: [{ k: "gen", v: "412" }], meters: [{ label: "CPU", pct: 18, text: "4 cores" }, { label: "MEM", pct: null, text: "n/a" }, { label: "NET\u2193", pct: null, v: 1200, text: "1.2 kB/s" }], lists: [{ title: "Failed", items: ["x.service"], tone: "bad" }] }] },
  "gauges (3 hosts, 8 meters)": { t: "stage", v: 1, kind: "gauges", title: long, token: "c1", hosts: ["a", "b", "c"].map(n => ({ name: n.repeat(32), state: "stale", badges: Array.from({ length: 6 }, (_, i) => ({ k: "k" + i, v: long.slice(0, 60) })), meters: Array.from({ length: 8 }, (_, i) => ({ label: "M" + i, pct: i * 12, text: long.slice(0, 40) })), lists: [{ title: "L", items: Array.from({ length: 5 }, () => long.slice(0, 80)), tone: "bad" }] })) },
  "headlines": { t: "stage", v: 1, kind: "headlines", title: "News", source: "3 feeds \u00b7 1 couldn't be reached", copy: "c1", items: [{ title: "Kernel 6.19 released", source: "Hacker News", at: Math.floor(Date.now() / 1000) - 7200, open: "h1" }, { title: "Storm crosses the north", source: "BBC News", at: Math.floor(Date.now() / 1000) - 300, open: "h2" }, { title: "Local council budget", source: "The Guardian", at: null }] },
  "headlines (5 long)": { t: "stage", v: 1, kind: "headlines", title: long.slice(0, 80), source: long, copy: "c1", items: Array.from({ length: 5 }, (_, i) => ({ title: long, source: "Feed " + (i + 1), at: Math.floor(Date.now() / 1000) - (i + 1) * 3600, open: "h" + i })) },
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

// the cinema: numbered posters with Play, the search in the footer as text, popcorn; or the failure with a browser search
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await show(FIX.video, w => 0);
  const c = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('cinema'), f.querySelectorAll('b').length, document.getElementById('stgFn').textContent, [...f.querySelectorAll('.sb')].map(b=>b.textContent).join(), f.querySelectorAll('.pw').length, document.getElementById('pop').classList.contains('on'), getComputedStyle(f,'::before').animationName, getComputedStyle(f.querySelector('.pw'),'::before').content]`);
  check(c[0] && c[1] === 0 && c[2] === "Searched YouTube for: <b>cats</b>" && c[3] === "Play,Play,Play" && c[4] === 3 && c[5] && c[6] === "stgCurL" && c[7].includes("▶"), "cinema set", JSON.stringify(c));
  await show(FIX["video (failed)"], w => 0);
  check(await ev("return document.getElementById('stg').classList.contains('bare') && document.getElementById('stg').getBoundingClientRect().height < 250"), "cinema: empty state shrinks to its content");
  const e = await ev(`return [document.getElementById('stg').textContent.includes("Couldn't search right now"), [...document.querySelectorAll('#stg .sb')].map(b=>b.textContent).join()]`);
  check(e[0] && e[1] === "Search in browser", "cinema: failure offers a browser search", JSON.stringify(e));
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
  await show(FIX.video, w => 0);
  const r3 = await ev(`return getComputedStyle(document.getElementById('stg'),'::before').animationName`);
  check(r3 === "none", "cinema: curtains still under reduced motion", r3);
  await send("Emulation.setEmulatedMedia", { features: [] }); }

// the sky: day and night by SIT.day, the source and time as text, no buttons; the desk: a flip page, Join only with a link, markup as text
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await ev("SIT.day=true; return 1"); await show({ ...FIX.weather, source: "<b>x</b>" }, w => 0);
  const d = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('sky'), f.classList.contains('night'), f.querySelectorAll('b').length, document.getElementById('stgFn').textContent, f.querySelectorAll('.sb').length, f.querySelector('.tmp').textContent, f.textContent.includes('Wind 14 km/h SW')]`);
  check(d[0] && !d[1] && d[2] === 0 && d[3] === "<b>x</b> \u00b7 as of 14:32" && d[4] === 0 && d[5] === "4\u00b0C" && d[6], "sky set (day)", JSON.stringify(d));
  await ev("SIT.day=false; return 1"); await show(FIX.weather, w => 0);
  const n = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('night'), getComputedStyle(f).backgroundImage.includes('radial-gradient'), document.getElementById('stgFn').textContent]`);
  check(n[0] && n[1] && n[2] === "Open-Meteo \u00b7 as of 14:32", "sky set (night)", JSON.stringify(n));
  await ev("SIT.day=true; return 1");
  await show(FIX["weather (empty)"], w => 0);
  check(await ev("return document.getElementById('stg').textContent.includes('No weather reading yet')"), "sky: no reading says so");
  await show({ ...FIX["weather (empty)"], off: true }, w => 0);
  check(await ev("return document.getElementById('stg').textContent.includes('Weather is off')"), "sky: weather off says so");
  await show({ ...FIX.weather, sky: null }, w => 0);
  check(await ev("return ![...document.querySelectorAll('#stg svg circle')].some(c=>c.getAttribute('fill')==='#ffd23f')"), "sky: unknown sky draws no sun");
  await show({ ...FIX.weather, sky: "clear" }, w => 0);
  check(await ev("return [...document.querySelectorAll('#stg svg circle')].some(c=>c.getAttribute('fill')==='#ffd23f')"), "sky: clear draws a sun");
  await show({ ...FIX["calendar (empty)"], unread: true, at: null }, w => 0);
  check(await ev("return document.getElementById('stg').textContent.includes('couldn\\u2019t be read')"), "desk: calendar unread says so");
  check(await ev("const t=stageText({kind:'status',sessions:[],sys_on:true,failed:['a.service'],failed_n:3}), u=stageText({kind:'status',sessions:[],sys_on:false,failed:[]}); return t.includes('Failed services: a.service +2 more') && u.includes('Services not checked')"), "desk: status text has services");
  await show({ ...FIX.calendar, events: [{ when: "10:40", title: "<b>Stand-up</b>", join: "j1" }, { when: "Wed 11:00", title: "A" }, { when: "Wed 12:00", title: "B", join: "j3" }] }, w => 0);
  const c = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('desk'), f.querySelectorAll('b').length, f.querySelector('.pg .lb').textContent, [...f.querySelectorAll('.sb')].map(b=>b.textContent).join(), f.querySelectorAll('.tk').length, getComputedStyle(f.querySelector('.pg')).animationName]`);
  check(c[0] && c[1] === 0 && c[2] === "<b>Stand-up</b>" && c[3] === "Join,Join,Open calendar" && c[4] === 2 && c[5] === "stgFlip", "desk: calendar", JSON.stringify(c));
  await show(FIX["calendar (off)"], w => 0);
  check(await ev("return document.getElementById('stg').textContent.includes('Calendar is off') && [...document.querySelectorAll('#stg .sb')].map(b=>b.textContent).join()==='Open calendar'"), "desk: calendar off says so");
  await show(FIX.status, w => 0);
  const t = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('desk'), f.querySelectorAll('.it').length, [...f.querySelectorAll('.sb')].map(b=>b.textContent).filter((x,i,a)=>a.indexOf(x)===i).join(), f.querySelector('.src.bad').textContent]`);
  check(t[0] && t[1] === 5 && t[2] === "Open session,Open terminal" && /\+2 more$/.test(t[3]), "desk: status", JSON.stringify(t));
  await show(FIX["status (empty)"], w => 0);
  check(await ev("const x=document.getElementById('stg').textContent; return x.includes('No herdr sessions running') && x.includes('Services not checked')"), "desk: empty status");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
  await show(FIX.calendar, w => 0);
  check(await ev("return getComputedStyle(document.querySelector('#stg .pg')).animationName") === "none", "desk: flip still under reduced motion");
  await send("Emulation.setEmulatedMedia", { features: [] }); }

// the day desk: a date tab that flips once, a Next card with Join, three rows that open a detail view in the same frame
{ await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  const D = FIX["day (full)"];
  await show({ ...D, wd: "<b>Wed</b>", next: { ...D.next, title: "<b>Stand-up</b>" }, rows: D.rows.map((r, i) => i ? r : { ...r, items: r.items.map(x => ({ ...x, title: "<i>t</i>" })) }) }, w => 0);
  const d = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('desk'), f.querySelectorAll('b,i').length, f.querySelector('.pgd').textContent, f.querySelector('.nxl').textContent, [...f.querySelectorAll('.nxa .sb')].map(b=>b.textContent).join(), f.querySelectorAll('.rw').length, [...f.querySelectorAll('.rwc')].map(x=>x.textContent).join(), getComputedStyle(f.querySelector('.pg')).animationName, document.getElementById('stgT').textContent, document.getElementById('wtc').classList.contains('on'), f.querySelectorAll('.rw')[0].querySelectorAll('.rwl').length]`);
  check(d[0] && d[1] === 0 && d[2] === "<b>Wed</b>" && d[3] === "<b>Stand-up</b>" && d[4] === "Join,Open" && d[5] === 3 && d[6] === "12,9,11" && d[7] === "stgFlip" && d[8] === "Your day" && d[9] && d[10] === 2, "day desk: layout and markup as text", JSON.stringify(d));
  await show({ ...D, rows: D.rows.map(r => ({ ...r, items: r.items.slice(0, 2).map(x => ({ ...x, title: "Short title" })) })), next: { ...D.next, title: "Stand-up" } }, w => 0);
  const nf = await ev("const b=document.querySelector('#stg .bd'); return [b.scrollHeight, b.clientHeight]");
  check(nf[0] <= nf[1], "day desk: a normal day shows all three rows without scrolling", JSON.stringify(nf));
  await show({ ...D, wd: "<b>Wed</b>", next: { ...D.next, title: "<b>Stand-up</b>" }, rows: D.rows.map((r, i) => i ? r : { ...r, items: r.items.map(x => ({ ...x, title: "<i>t</i>" })) }) }, w => 0);
  await ev("document.querySelectorAll('#stg .rw')[1].click(); return 1"); await sleep(80);
  const v = await ev(`const f=document.getElementById('stg'), r=f.getBoundingClientRect(); return [f.querySelectorAll('.tk').length, [...f.querySelectorAll('.sb')].map(b=>b.textContent).filter((x,i,a)=>a.indexOf(x)===i).join(), f.querySelectorAll('.tt.od').length, f.textContent.includes('+ 1 more'), r.height, f.querySelectorAll('.pg').length, f.querySelector('.bd').scrollHeight>=f.querySelector('.bd').clientHeight]`);
  check(v[0] === 8 && v[1] === "Open,\u2190 Day" && v[2] === 2 && v[3] && v[4] <= 440 && v[5] === 0, "day desk: detail view", JSON.stringify(v));
  await ev("[...document.querySelectorAll('#stg .sb')].find(b=>b.textContent.includes('Day')).click(); return 1"); await sleep(80);
  check(await ev("const f=document.getElementById('stg'); return f.querySelectorAll('.rw').length===3 && getComputedStyle(f.querySelector('.pg')).animationName==='none'"), "day desk: back to the day, no second flip");
  await show(FIX["day (stale and off)"], w => 0);
  const o = await ev(`const f=document.getElementById('stg'); return [[...f.querySelectorAll('.rwm')].map(x=>x.textContent).join('|'), [...f.querySelectorAll('.nxa .sb')].length, f.querySelectorAll('.rwc')[2].textContent]`);
  check(o[0] === "couldn\u2019t refresh \u00b7 09:30|couldn\u2019t refresh \u00b7 09:55|not set up" && o[1] === 0 && o[2] === "", "day desk: stale and off rows say so", JSON.stringify(o));
  await show(FIX["day (empty)"], w => 0);
  check(await ev("const x=document.getElementById('stg').textContent; return x.includes('Nothing else timed today') && x.includes('Nothing')"), "day desk: empty day");
  check(await ev("const t=stageText(" + JSON.stringify(FIX["day (stale and off)"]) + "); return t.includes('GitHub: not set up') && t.includes('Next: 10:40 Stand-up') && t.includes('Release day')"), "day desk: text fallback");
  check(await ev("const t=stageText({kind:'day',wd:'Wed',md:'4 Nov',next:{when:'now',title:'Stand-up',in:'now'},rows:[]}); return t.includes('Next: now Stand-up') && !t.includes('now)')"), "day desk: an event under way says now once");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(200);
  await show(D, w => 0);
  check(await ev("return getComputedStyle(document.querySelector('#stg .pg')).animationName") === "none", "day desk: flip still under reduced motion");
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

// Location (#152): the map card's unset and "From" states, and the settings section
{ await show({ ...FIX.place, dest: "@home", unset: "home", open: undefined, copy: undefined }, w => 0);
  const u = await ev(`const f=document.getElementById('stg'); return [f.querySelector('.dst').textContent, [...f.querySelectorAll('.sb')].map(b=>b.textContent).join(), f.classList.contains('map')]`);
  check(u[0] === "Set Home in Nixi\u2019s settings" && u[1] === "Settings" && u[2], "map: unset Home asks for settings, no Maps button", JSON.stringify(u));
  await ev(`[...document.querySelectorAll('#stg .sb')].find(b=>b.textContent==='Settings').click(); return 1`); await sleep(400);
  const o = await ev(`return [setEl.classList.contains('on'), document.querySelector('#set .tab[data-tab=voice]').classList.contains('on'), !!document.getElementById('locRow')]`);
  check(o[0] && o[1] && o[2], "map: Settings opens the Location section", JSON.stringify(o));
  await ev(`settings(false); return 1`); await sleep(300);
  await show({ ...FIX.place, dest: "Oslo", from: "<b>Lisbon</b>" }, w => 0);
  const fr = await ev(`const f=document.getElementById('stg'); return [document.getElementById('stgFn').textContent, f.querySelectorAll('b').length, [...f.querySelectorAll('.sb')].map(b=>b.textContent).join()]`);
  check(fr[0] === "From <b>Lisbon</b> \u00b7 a sketch, not the route" && fr[1] === 0 && fr[2] === "Open in Google Maps,Copy address", "map: footnote names where from, as text", JSON.stringify(fr));
  await ev(`settings(true,'voice'); await locLoad(); return 1`);
  const l = await ev(`const w=document.getElementById('locWifi'); return [document.getElementById('locNow').textContent, [...document.querySelectorAll('#locChips button')].map(b=>b.textContent).join(), (w.style.display==='none')===!(loc.wifi&&loc.wifi.device), document.getElementById('locHome').placeholder]`);
  check(/^Now: /.test(l[0]) && l[1] === "Home,Work,Auto" && l[2], "settings: Location section draws, Wi-Fi block follows the device", JSON.stringify(l));
  await ev(`await locAct({act:'set',place:'home',name:'<b>x</b>'}); return 1`);
  const w = await ev(`return [document.getElementById('locErr').textContent, document.getElementById('locHome').value, document.querySelectorAll('#locRow b').length]`);
  check(w[0] === "needs nixarchy-location (update nixarchy)" && w[2] === 0, "settings: a write without the command says what to update", JSON.stringify(w));
  // suggestions: an answer to an old question is dropped, and picking puts the name in the field
  const sg = await ev(`const mk=(n)=>({name:n,admin:'',country:'',latitude:1,longitude:2}); const i=document.getElementById('locHome');
    locSug.home=[mk('Oxford'),mk('Oslo')]; locIdx.home=-1; locSugShow('home');
    const g0=locGen.home; locAsk('home','ox'); const stale=g0!==locGen.home;
    locDrop('home'); const dropped=locGen.home>g0+1 && document.getElementById('locHomeSug').children.length===0;
    locSug.home=[mk('Oxford'),mk('Oslo')]; locSugShow('home'); locPick('home',1);
    return [stale, dropped, i.value, document.getElementById('locHomeSug').children.length]`);
  check(sg[0] && sg[1] && sg[2] === "Oslo" && sg[3] === 0, "settings: stale suggestions are ignored, a pick fills the field", JSON.stringify(sg));
  await ev(`settings(false); return 1`); }

// the system board (#166): the term set, the in-place update and the refresh loop
{ const G = FIX.gauges, upd = (cpu, extra = {}) => ({ ...G, t: "stage_update", hosts: [{ ...G.hosts[0], meters: [{ label: "CPU", pct: cpu, text: "4 cores" }, ...G.hosts[0].meters.slice(1)], ...extra }] });
  const motion = v => send("Emulation.setEmulatedMedia", { features: v ? [{ name: "prefers-reduced-motion", value: v }] : [] });
  await ev("window.__ref=[]; window.__ans={ok:true}; window.__delay=0; const of2=window.fetch; window.fetch=(u,o)=>{ if(String(u).includes('/api/stage/act')&&o&&o.body&&JSON.parse(o.body).act==='refresh'){ __ref.push(JSON.parse(o.body).token); return new Promise(r=>setTimeout(()=>r(new Response(JSON.stringify(__ans))),__delay)); } return of2(u,o); }; GAUGE_MS=600000; return 1");
  const refs = () => ev("return __ref.length"), fast = ms => ev(`clearInterval(gaugeRef.t); gaugeRef.t=setInterval(gaugeLoop,${ms}); __ref.length=0; return 1`);
  await motion("no-preference");
  await show(G, w => 0);
  const r = await ev(`const f=document.getElementById('stg'), w=f.querySelector('.tmw'); return [f.classList.contains('term'), f.getBoundingClientRect().width, f.querySelectorAll('.tmh').length, f.querySelector('.tmn').textContent, w.getAttribute('aria-label'), w.getAttribute('role'), [...f.querySelectorAll('.tmv')].map(x=>x.textContent).join(), f.querySelector('.tms').getAttribute('aria-hidden'), f.querySelector('.tmli.bad .tmit').textContent, document.getElementById('stgFn').textContent, [...f.querySelectorAll('.sb')].map(b=>b.textContent).join(), getComputedStyle(f).fontFamily.includes('JetBrains')||getComputedStyle(f).fontFamily.includes('monospace'), getComputedStyle(w).animationName, getComputedStyle(f.querySelector('.tmh')).animationName, getComputedStyle(f.querySelector('.tmbar i')).animationName]`);
  check(r[0] && r[1] === 340 && r[2] === 1 && r[3] === "┤ p620 ├" && r[4] === "CPU 18 percent" && r[5] === "group" && r[6] === "18%,—,—" && r[7] === "true" && r[8] === "x.service" && r[9] === "Source: p620" && r[10] === "Copy" && r[11] && r[12] === "stgRow" && r[13] === "stgPow" && r[14] === "stgBar", "term: a gauges stage renders", JSON.stringify(r));
  check(await ev(`const t=stageText(${JSON.stringify(G)}); return t.includes('System status') && t.includes('CPU: 18% · 4 cores') && t.includes('MEM: n/a')`), "term: text fallback has a line per meter");
  check(await ev(`const t=stageText(${JSON.stringify(G)}); return t.includes('Failed: x.service')`), "term: text fallback keeps the failed-unit list");
  // in place: the same nodes, new numbers, no entrance, focus and timers untouched
  await ev("document.querySelector('#stg .sb').focus(); window.__row=document.querySelector('#stg .tmw'); window.__t0=[stgUse,stgQuiet,stgTimer,document.getElementById('stg').className]; return 1");
  await ev(`onEvent(${JSON.stringify(upd(77, { badges: [{ k: "gen", v: "413" }] }))}); return 1`);
  const u = await ev(`const f=document.getElementById('stg'); return [document.querySelector('#stg .tmw')===__row, __row.querySelector('.tmv').textContent, __row.getAttribute('aria-label'), __row.querySelector('.tms').textContent.length, f.querySelector('.tmg').textContent, document.activeElement===document.querySelector('#stg .sb'), stgUse===__t0[0]&&stgQuiet===__t0[1]&&stgTimer===__t0[2], f.className===__t0[3], f.getAnimations({subtree:true}).filter(a=>a.playState==='running').length, f.querySelectorAll('.tmh').length]`);
  check(u[0] && u[1] === "77%" && u[2] === "CPU 77 percent" && u[3] === 2 && u[4] === "gen 413" && u[5] && u[6] && u[7] && u[8] === 0 && u[9] === 1, "term: stage_update changes values in place", JSON.stringify(u));
  const extra = { ...G, t: 'stage_update', hosts: [{ ...G.hosts[0], meters: [...G.hosts[0].meters, { label: 'DISK', pct: 42 }] }, { name: 'razer', meters: [{ label: 'CPU', pct: 9 }] }] };
  await ev(`onEvent(${JSON.stringify(extra)}); return 1`);
  const added = await ev("const f=document.getElementById('stg'); return [f.querySelectorAll('.tmh').length, f.querySelector('[data-label=DISK] .tmv')?.textContent, f.classList.contains('go'), f.querySelectorAll('.sb').length, gaugeHist['p620\\0CPU'].length, stgTimer===__t0[2]]");
  check(added[0] === 2 && added[1] === '42%' && !added[2] && added[3] === 1 && added[4] === 3 && added[5], "term: new meter and host rebuild without entrance or duplicate Copy", JSON.stringify(added));
  await ev(`onEvent(${JSON.stringify({ ...extra, hosts: [extra.hosts[0]] })}); return 1`);
  check(await ev("return document.querySelectorAll('#stg .tmh').length===1 && !document.getElementById('stg').classList.contains('go') && document.querySelectorAll('#stg .sb').length===1"), "term: a removed host disappears without entrance");
  await ev(`onEvent({...${JSON.stringify(upd(5))}, refresh: "other"}); return 1`);
  check(await ev("return __row.querySelector('.tmv').textContent") === "77%", "term: an update for another board is ignored");
  await ev(`stageClose(); await new Promise(r=>setTimeout(r,320)); onEvent(${JSON.stringify(upd(5))}); return 1`);
  check(await ev("return __row.querySelector('.tmv').textContent") === "77%", "term: an update with no board open is ignored");
  await show(FIX.facts, w => 0);
  await ev(`onEvent(${JSON.stringify(upd(5))}); return 1`);
  check(await ev("return [document.getElementById('stgT').textContent, document.querySelectorAll('#stg .tmh').length]").then(x => x.join()) === "Tides,0", "term: an update over another kind of board changes nothing");
  // the refresh loop
  await ev("__ans={ok:true,skipped:true}; return 1");
  await show(G, w => 0); await fast(40); await sleep(1800);
  check(await refs() === 24 && await ev("return [gaugeRef===null, stgState]").then(x => x.join()) === "true,open", "loop: stops after 24 (a skipped answer carries on)", String(await refs()));
  await ev("__ans={ok:true}; return 1");
  await show(G, w => 0); await fast(60); await sleep(250);
  const c0 = await ev("stageClose(); return __ref.length"); await sleep(300);
  check(c0 > 0 && await refs() === c0 && await ev("return gaugeRef===null"), "loop: stops on close", String(c0));
  await show(G, w => 0); await fast(200); await sleep(300);
  await ev("stgUse=performance.now()-100000; return 1"); await sleep(1200);
  check(await ev("return stgState") === "open", "loop: a refreshing board holds for 2 min, not 30 s");
  await ev("stgUse=performance.now()-130000; return 1"); await sleep(1300);
  const c1 = await refs(); await sleep(500);
  check(await ev("return [stgState, gaugeRef===null]").then(x => x.join()) === "tab,true" && await refs() === c1, "loop: stops on collapse after 2 min", String(c1));
  await show(G, w => 0); await fast(60); await sleep(250);
  await ev("Object.defineProperty(document,'hidden',{get:()=>true,configurable:true}); return 1"); await sleep(150);
  const h0 = await refs(); await sleep(400); const h1 = await refs();
  await ev("delete document.hidden; return 1"); await sleep(300);
  check(h0 > 0 && h1 === h0 && await refs() > h1, "loop: none while document.hidden, back when shown", JSON.stringify([h0, h1, await refs()]));
  await show(G, w => 0); await fast(60); await sleep(250);
  await ev("setEl.classList.add('on'); return 1"); await sleep(1200);      // Settings open: the page reports hidden, stgPosted goes false
  const p0 = await refs(), pf = await ev("return stgPosted"); await sleep(400);
  const p1 = await refs(); await ev("setEl.classList.remove('on'); return 1"); await sleep(1200);
  check(p0 > 0 && pf === false && p1 === p0 && await refs() > p1, "loop: none while stgPosted is false, back after", JSON.stringify([p0, pf, p1, await refs()]));
  await show(G, w => 0);
  await ev("clearInterval(gaugeRef.t); __ans={ok:false,error:'locked'}; gaugeLoop(); return 1"); await sleep(40);
  check(await ev("return gaugeRef!==null && gaugeRef.failed===1"), "loop: one failed answer keeps refreshing");
  await ev("__ans={ok:true}; gaugeLoop(); return 1"); await sleep(40);
  check(await ev("return gaugeRef!==null && gaugeRef.failed===0"), "loop: a successful answer resets failures");
  await ev("__ans={ok:false,error:'locked'}; gaugeLoop(); return 1"); await sleep(40);
  check(await ev("return gaugeRef!==null && gaugeRef.failed===1"), "loop: first failure after success keeps refreshing");
  await ev("gaugeLoop(); return 1"); await sleep(40);
  check(await ev("return gaugeRef===null"), "loop: stops after two consecutive failed answers");
  check(await ev(`const g={...${JSON.stringify(G)}}; delete g.refresh; return 1`) && (await show({ ...G, refresh: undefined }, w => 0), await ev("return gaugeRef===null")), "loop: nothing without a refresh token");
  // an answer that arrives after close changes nothing (not even a newer board's loop)
  await ev("__ans={ok:false}; __delay=300; return 1");
  await show(G, w => 0); await fast(60); await sleep(120);
  await ev("stageClose(); return 1"); await show(G, w => 0); await sleep(500);
  check(await ev("return [gaugeRef!==null, stgState]").then(x => x.join()) === "true,open", "loop: a late answer after close leaves the new board alone");
  await ev("__delay=0; __ans={ok:true}; stageClose(); return 1"); await sleep(320);
  // reduced motion: no animation at all
  await motion("reduce"); await sleep(200);
  await show(G, w => 0);
  const m = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('go'), getComputedStyle(f.querySelector('.tmw')).animationName, getComputedStyle(f.querySelector('.tmh')).animationName, getComputedStyle(f.querySelector('.tmbar i')).animationName]`);
  check(!m[0] && m[1] === "none" && m[2] === "none" && m[3] === "none", "term: reduced motion has no animation", JSON.stringify(m));
  await motion(null);
  // colours: the fallbacks when the theme is off, the theme's when on
  await ev("applyThemeVars(null); return 1"); await show(G, w => 0);
  const col = () => ev(`const f=document.getElementById('stg'); return [getComputedStyle(f.querySelector('.tmli.bad .tmit')).color, getComputedStyle(f.querySelector('.tmn')).color, getComputedStyle(f).color, getComputedStyle(f).backgroundColor]`);
  const c2 = await col();
  check(c2[0] === "rgb(224, 108, 117)" && c2[1] === "rgb(97, 175, 239)" && c2[2] === "rgb(215, 218, 224)" && /0\.96|0\.9\d/.test(c2[3]), "term: fallback colours with the theme off", JSON.stringify(c2));
  await ev("applyThemeVars({background:'#101010',foreground:'#eeeeee',darker_background:'#000000',accent:'#00ff00',red:'#ff0000',green:'#00ff00',yellow:'#ffff00'}); return 1");
  const c3 = await col();
  check(c3[0] === "rgb(255, 0, 0)" && c3[1] === "rgb(0, 255, 0)" && c3[2] === "rgb(238, 238, 238)", "term: the theme's colours with it on", JSON.stringify(c3));
  await ev("applyThemeVars({background:'#fff',foreground:'#222',darker_background:'#fff',accent:'#36f',red:'#f66',green:'#6f6',yellow:'#ff6'}); return 1");
  const c4 = await col();
  check(c4[0] === "rgb(224, 108, 117)" && c4[2] === "rgb(215, 218, 224)" && await ev("return document.getElementById('stg').classList.contains('fixed')"), "term: a light theme gets the fixed dark palette", JSON.stringify(c4));
  await ev("applyThemeVars(null); stageClose(); return 1"); await sleep(320); }

// the press set (#167): newsprint look, small-caps source + age, Tab reaches each Open, reduced motion, no external requests
{ const H = FIX.headlines;
  const motion = v => send("Emulation.setEmulatedMedia", { features: v ? [{ name: "prefers-reduced-motion", value: v }] : [] });
  const key = async k => { await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, windowsVirtualKeyCode: k === "Tab" ? 9 : 27 }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, windowsVirtualKeyCode: k === "Tab" ? 9 : 27 }); };
  await motion("no-preference");
  reqs.length = 0;
  await show(H, w => 0);
  const p = await ev(`const f=document.getElementById('stg'), r=f.querySelector('.prw'); return [f.classList.contains('press'), f.getBoundingClientRect().width, document.getElementById('stgT').textContent, document.getElementById('stgDt').textContent.length>0, getComputedStyle(f.querySelector('header')).borderBottomStyle, f.querySelectorAll('.prw').length, [...f.querySelectorAll('.prm')].map(x=>x.textContent).join('|'), getComputedStyle(f.querySelector('.prt')).fontFamily.includes('Georgia'), getComputedStyle(f.querySelector('.prm')).fontVariantCaps, document.getElementById('stgFn').textContent, getComputedStyle(f).animationName, getComputedStyle(f.querySelector('.bd')).animationName, getComputedStyle(r).animationName]`);
  check(p[0] && p[1] === 340 && p[2] === "News" && p[3] && p[4] === "double" && p[5] === 3 && p[6] === "Hacker News \u00b7 2 h ago|BBC News \u00b7 5 min ago|The Guardian \u00b7 time unknown" && p[7] && p[8] === "small-caps" && p[9] === "3 feeds \u00b7 1 couldn't be reached" && p[10] === "stgSlip" && p[11] === "stgUnfold" && p[12] === "stgRow", "press: a headlines stage renders with source and age per row", JSON.stringify(p));
  const cr = await ev(`const f=document.getElementById('stg'), bg=lumOf(getComputedStyle(f).backgroundColor), ratio=c=>{ const l=lumOf(c); return (Math.max(bg,l)+.05)/(Math.min(bg,l)+.05); }; return [ratio(getComputedStyle(f.querySelector('.prt')).color), ratio(getComputedStyle(f.querySelector('.prm')).color), ratio(getComputedStyle(f.querySelector('.sb')).color)]`);
  check(cr.every(x => x >= 4.5), "press: contrast >= 4.5:1", JSON.stringify(cr));
  // Tab reaches each Open button in order, and Open posts /api/stage/act {token, act:"open"}
  await ev("document.getElementById('stgX').focus(); return 1");
  await key("Tab"); const f1 = await ev("return [document.activeElement.tagName, document.activeElement.getAttribute('aria-label')]");
  await key("Tab"); const f2 = await ev("return [document.activeElement.tagName, document.activeElement.getAttribute('aria-label')]");
  await ev("window.__openAct=null; const of3=window.fetch; window.fetch=(u,o)=>{ if(String(u).includes('/api/stage/act')&&o?.body){ const b=JSON.parse(o.body); if(b.act==='open') __openAct=b; } return of3(u,o); }; document.querySelector('#stg .prw .sb').click(); return 1");
  await sleep(60);
  const act = await ev("return __openAct");
  check(f1[0] === "BUTTON" && f1[1] === "Open: Kernel 6.19 released" && f2[0] === "BUTTON" && f2[1] === "Open: Storm crosses the north" && act?.token === "h1" && act?.act === "open", "press: Tab reaches each Open and Open posts its token", JSON.stringify([f1, f2, act]));
  // minute-tick refreshes ages; stageText formats "headline — source, age"; 30 s collapse and Esc close
  const ageUpd = await ev("stg.items[1].at=Math.floor(Date.now()/1000)-420; stageTick(); return document.querySelectorAll('#stg .prm')[1].textContent");
  check(ageUpd === "BBC News \u00b7 7 min ago", "press: minute tick refreshes age", ageUpd);
  check(await ev(`const t=stageText(${JSON.stringify(H)}); return t.includes('Kernel 6.19 released \u2014 Hacker News, 2 h ago') && t.includes('Storm crosses the north \u2014 BBC News, 5 min ago') && t.includes('Local council budget \u2014 The Guardian, time unknown')`), "press: stageText branch formats headline \u2014 source, age");
  await ev("stgUse=performance.now()-31000; stageTick(); return 1");
  check(await ev("return stgState") === "tab", "press: collapses to its tab after 30 s");
  await ev("stageRestore(); return 1"); await sleep(200);
  await key("Escape"); await sleep(60);
  check(await ev("return stgState") === "closed", "press: Esc closes");
  // reduced motion: no animation
  await motion("reduce"); await sleep(200);
  await show({ ...H, items: [{ title: "<img src='https://feeds.bbci.co.uk/x.png'>", source: "<b>BBC News</b>", at: null, open: "h1" }] }, w => 0);
  const rm = await ev(`const f=document.getElementById('stg'); return [f.classList.contains('go'), getComputedStyle(f).animationName, getComputedStyle(f.querySelector('.bd')).animationName, getComputedStyle(f.querySelector('.prw')).animationName, f.querySelectorAll('img,b').length]`);
  check(!rm[0] && rm[1] === "none" && rm[2] === "none" && rm[3] === "none" && rm[4] === 0, "press: reduced motion has no animation and markup stays text", JSON.stringify(rm));
  const ext = reqs.filter(u => u && !u.startsWith(`http://127.0.0.1:${port}/`) && !u.startsWith("data:") && !u.startsWith("about:"));
  check(ext.length === 0, "press: no request leaves the page for a news site", JSON.stringify(ext));
  await motion(null); await ev("stageClose(); return 1"); await sleep(320); }

await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
