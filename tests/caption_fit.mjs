// Nixi's captions and notification card are readable and fit (#155): contrast of the caption colours, one plate that
// hugs the text, no mask, a bordered notification card, a width that only grows while a caption streams.
//   node tests/caption_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). Fails with `CUT <what>` and exit 1.
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
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4500);

const fails = [];
const check = (ok, what, got) => { if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + got}`); } };

// WCAG in Node, independent of the page's own helpers
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const lin = v => (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
const L = h => { const [r, g, b] = rgb(h).map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const [x, y] = [L(a), L(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const over = (c, a, bg) => "#" + rgb(c).map((v, i) => Math.round(v * a + rgb(bg)[i] * (1 - a)).toString(16).padStart(2, "0")).join("");

// contrast: four themes, every caption colour against the backing over both a black and a white window
const full = (bg, fg, dfg, mode) => ({ mode, background: bg, foreground: fg, dark_foreground: dfg, darker_background: bg, lighter_background: bg, selection: dfg,
  accent: "#3e5993", red: "#f00", green: "#0f0", yellow: "#ff0", blue: "#3e5993", cyan: "#6d9bbc", bright_foreground: fg });
const THEMES = { default: null, light: full("#f4f1ea", "#2a2a2a", "#8a8a8a", "light"), "dim ≈ bg": full("#1f1f2f", "#cdd6f4", "#1e1e2e", "dark"), "mid grey": full("#727272", "#ffffff", "#ffffff", "dark") };
for (const [name, th] of Object.entries(THEMES)) {
  const r = await ev(`applyThemeVars(${JSON.stringify(th)}); const c=capColors(); return {c, panel:getComputedStyle(document.documentElement).getPropertyValue('--panel').trim()||'#0b0b0b'}`);
  const panel = r.panel.length === 4 ? "#" + [...r.panel.slice(1)].map(v => v + v).join("") : r.panel;
  for (const k of ["text", "dim", "err", "code"]) for (const bg of ["#000000", "#ffffff"]) {
    const got = ratio(r.c[k], over(panel, r.c.a, bg));
    check(got >= 4.5, `contrast ${name}/${k} over ${bg}`, got.toFixed(2));
  }
}
await ev(`applyLook(LOOK); return 1`);

// the plate: hugs the text, hides when empty, no mask
const p1 = await ev(`himSet('hi'); capShow(); await new Promise(r=>setTimeout(r,100));
  const cs=getComputedStyle(plate); return {bg:cs.backgroundColor, w:plate.getBoundingClientRect().width, cw:cap.getBoundingClientRect().width, mask:getComputedStyle(cap).maskImage, wmask:getComputedStyle(cap).webkitMaskImage}`);
check(p1.bg !== "rgba(0, 0, 0, 0)" && p1.bg !== "transparent", "plate has no background", p1.bg);
check(p1.w < p1.cw, "plate does not hug the text", `${p1.w} vs ${p1.cw}`);
check(p1.mask === "none" && p1.wmask === "none", "the caption still has a mask", p1.mask);
check(await ev(`himSet(''); setYou(''); return getComputedStyle(plate).display`) === "none", "an empty plate is shown");

// the notification card
const SHOW = `const row={key:'k',span:null}; notifyRow=row; notifyShow(row,'Notification · test',{});`;
const n1 = await ev(`${SHOW} const pr=plate.getBoundingClientRect(), cr=cap.getBoundingClientRect(), el=document.elementFromPoint(cr.left+2,pr.top+pr.height/2);
  return {ntf:cap.classList.contains('ntf'), note:cap.classList.contains('note'), border:getComputedStyle(plate).borderTopWidth, hitPlate:!!el&&(el===plate||plate.contains(el)), same:notifyRow===row, narrow:pr.width<cr.width-8}`);
check(n1.ntf && !n1.note, "card class is not ntf", JSON.stringify(n1));
check(n1.border === "1px", "card has no 1px border", n1.border);
check(n1.narrow && !n1.hitPlate, "a click beside the card lands on the card", JSON.stringify(n1));
check(n1.same, "notifyShow dropped its own row");
const n2 = await ev(`notifyClear(); return [cap.classList.contains('ntf'), cap.classList.contains('off')]`);
check(n2.join() === "false,true", "notifyClear leaves the card up", n2.join());

// replaced early: the next caption, and an unvoiced nudge, drop the notification
const n3 = await ev(`${SHOW} himSet('next'); return [cap.classList.contains('ntf'), notifyRow, himEl.textContent]`);
check(n3[0] === false && n3[1] === null && n3[2] === "next", "himSet leaves the notification up", JSON.stringify(n3));
const n4 = await ev(`${SHOW} nudgeQ.set('x',{text:'hello',rt:performance.now()}); notifyAt=0; nudgeDrain(performance.now()+1);
  return [cap.classList.contains('ntf'), notifyRow, himEl.textContent]`);
check(n4[0] === false && n4[1] === null && n4[2] === "hello", "a nudge leaves the notification up", JSON.stringify(n4));

// streaming: min-width only grows
const WORDS = "The quick brown fox jumps over the lazy dog and then runs far away".split(" ");
const widths = await ev(`himSet(''); const W=${JSON.stringify(WORDS)}, out=[];
  for(let i=1;i<=12;i++){ showHim(W.slice(0,i).join(' ')+(i<12?' ':''),i===12); out.push(parseFloat(plate.style.minWidth)); await new Promise(r=>setTimeout(r,40)); }
  return out`);
const wd = widths.filter(Number.isFinite);   // (the first prefix has no finished word yet: nothing is shown)
check(wd.length >= 10 && wd.every((w, i) => w > 0 && (i === 0 || w >= wd[i - 1])), "streaming min-width shrinks or is unset", widths.join());

// three lines stay inside the plate; a short caption after a long one shrinks back
const LONG = "Here is a rather long answer that goes on and on so that it has to wrap onto at least three lines inside the little caption window he has";
const g = await ev(`himSet(${JSON.stringify(LONG)}); capShow(); await new Promise(r=>setTimeout(r,1200));
  const pb=plate.getBoundingClientRect(), hb=himEl.getBoundingClientRect(), I=(b)=>b.left>=pb.left-.5&&b.right<=pb.right+.5&&b.top>=pb.top-.5&&b.bottom<=pb.bottom+.5;
  const bad=[...himEl.querySelectorAll('.w')].filter(w=>{ const b=w.getBoundingClientRect(); return b.bottom>hb.top+3&&b.top<hb.bottom-3&&!I(b); }).length;
  return {inside:I(hb), bad,  lines:Math.round(hb.height/(14.5*1.3)), w:pb.width}`);
check(g.inside && g.bad === 0, "three lines spill out of the plate", JSON.stringify(g));
check(g.w > 150, "long caption plate is not wide", g.w);
const sh = await ev(`himSet('hi'); await new Promise(r=>setTimeout(r,300)); return plate.getBoundingClientRect().width`);
check(sh < 100, "plate stays wide after a short caption", sh);
await ev(`himSet(''); return 1`);

// #wk is a pill, hidden when empty
const wk = await ev(`const w=document.getElementById('wk'); w.textContent=''; const e=getComputedStyle(w).display; w.textContent='working: Read'; const b=getComputedStyle(w).backgroundColor; w.textContent=''; return [e,b]`);
check(wk[0] === "none" && wk[1] !== "rgba(0, 0, 0, 0)", "#wk pill", wk.join(" | "));

// the notch stays one black shape
const bar = await ev(`document.body.classList.add('bar'); himSet('hi'); const cs=getComputedStyle(plate), w=document.getElementById('wk'); w.textContent='x';
  const r={bg:cs.backgroundColor, pad:parseFloat(cs.paddingLeft)+parseFloat(cs.paddingTop), bd:(cap.classList.add('ntf'),parseFloat(getComputedStyle(plate).borderTopWidth)||0), wk:getComputedStyle(w).display}; cap.classList.remove('ntf'); w.textContent=''; document.body.classList.remove('bar'); himSet(''); return r`);
check(bar.bg === "rgba(0, 0, 0, 0)" && bar.pad === 0 && bar.bd === 0 && bar.wk === "none", "notch plate/#wk", JSON.stringify(bar));

// the region: only the card (not the 316 px caption) takes clicks. NATIVE is a const set on load: navigate again with ?native=1
const [base, hash = ""] = url.split("#");
await send("Page.navigate", { url: `${base}${base.includes("?") ? "&" : "?"}native=1${hash ? "#" + hash : ""}` }); await sleep(4500);
const rg = await ev(`window.webkit={messageHandlers:{nixiui:{postMessage:m=>(window.__m=window.__m||[]).push(m)}}};
  info.click_through=true; ${SHOW} sendRegion(true);
  const last=[...window.__m].reverse().find(m=>String(m).startsWith('region:')), pb=plate.getBoundingClientRect();
  return {rs:last?JSON.parse(last.slice(7)):null, pb:{l:pb.left,t:pb.top,r:pb.right,b:pb.bottom}, cw:cap.getBoundingClientRect().width, cy0:cap.getBoundingClientRect().top, cy1:cap.getBoundingClientRect().bottom}`);
check(Array.isArray(rg.rs) && rg.rs.some(([x, y, w, h]) => x <= rg.pb.l && y <= rg.pb.t && x + w >= rg.pb.r && y + h >= rg.pb.b), "region does not cover the card", JSON.stringify(rg));
check(Array.isArray(rg.rs) && rg.rs.filter(r => r[1] + r[3] > rg.pb.t && r[1] < rg.pb.b).every(r => r[2] < rg.cw), "region is as wide as the caption", JSON.stringify(rg));

await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
