// Approvals for other agents (#211): the card fits, the click key goes only with a trusted click on yes, result lines,
// the working signal (code in his eyes; the panel is only for his own runs).
//   node tests/agent_approve_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (#138). Exit 0 = pass.
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
await send("Page.enable"); await send("Runtime.enable");
const exc = new Set(); ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.method === "Runtime.exceptionThrown") exc.add(m.params.exceptionDetails.exception?.description?.split("\n").slice(0, 2).join(" | ")); });
const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const waitFor = async (js, ms = 4000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await ev(`return !!(${js})`)) return true; await sleep(60); } return false; };

await send("Emulation.setDeviceMetricsOverride", { width: 900, height: 900, screenWidth: 1920, screenHeight: 1080, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: nativeUrl }); await sleep(4500);
await ev(`setInterval(()=>{ nextFidAt=1e15; },50); await post('/api/settings',{idle_mode:'off'}); if(window.setIdle) setIdle('full');
  window.__calls=[]; window.__ticks=[]; muted=true;
  const of=window.fetch;
  window.fetch=(u,o)=>{ const p=String(u).split('?')[0];
    if(['/api/approve/answer','/api/approve/release'].includes(p)){ __calls.push([p,JSON.parse(o.body),(o.headers||{})['X-Nixi-Click']||null]); return Promise.resolve(new Response('{"ok":true}',{status:200})); }
    return of(u,o); };
  const t0=tick; tick=(x,b)=>{ __ticks.push([x,!!b]); return t0(x,b); };
  return 1`);
const card = (extra = "") => ev(`onEvent(Object.assign({t:'approve',id:'a1',agent:'codex',tool:'Bash',project:'proj',detail:${JSON.stringify("uname -r\n" + "x".repeat(160))},say:'Codex wants to run a command',confirm:'click',always:false},${extra||"{}"})); return 1`);
const click = async sel => { const r = await ev(`const b=document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return [b.left+b.width/2,b.top+b.height/2]`);
  for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: r[0], y: r[1], button: "left", clickCount: 1 }); };
const calls = () => ev("return __calls.splice(0)");

// 1. the card: head line, fits the window, no always, terminal button
await card(); await waitFor("pendingAppr");
const g = await ev(`const r=apEl.getBoundingClientRect(); return {q:$('#apQ').textContent, l:r.left, t:r.top, r:r.right, b:r.bottom, vw:innerWidth, vh:innerHeight, wx:cardWant[0], wy:cardWant[1], al:apEl.querySelector('[data-ans="always"]').offsetParent===null, term:$('#apTerm').offsetParent!==null}`);
check(g.q === "Codex · proj wants to run", "head line names the agent and project", g.q);
check(g.l >= 0 && g.t >= 0 && g.r <= 340 + g.wx + 1 && g.b <= 460 + g.wy + 1, "the card fits the window it asks for", JSON.stringify(g));
check(g.al && g.term, "no always button, terminal button shown");

// 2. a trusted click on yes sends the key; a click on no and the keyboard path do not
await sleep(300);
await click('#appr [data-ans="yes"]'); await waitFor("!pendingAppr");
let c = await calls();
check(c.length === 1 && c[0][1].ans === "yes" && typeof c[0][2] === "string" && c[0][2].length > 10, "trusted yes carries X-Nixi-Click", JSON.stringify(c));
await card(); await waitFor("pendingAppr"); await sleep(300);
await ev("answer('yes'); return 1"); await waitFor("!pendingAppr"); c = await calls();
check(c.length === 1 && c[0][2] === null, "a yes that is not a trusted click carries no key", JSON.stringify(c));
await card(); await waitFor("pendingAppr"); await sleep(300);
await click('#appr [data-ans="no"]'); await waitFor("!pendingAppr"); c = await calls();
check(c.length === 1 && c[0][1].ans === "no" && c[0][2] === null, "a no never carries the key", JSON.stringify(c));

// 3. a refused answer says so
await ev("window.fetch=(u,o)=>String(u).includes('/api/approve/answer')?Promise.resolve(new Response('{\"ok\":false}',{status:200})):Promise.resolve(new Response('{}',{status:200})); return 1");
await card(); await waitFor("pendingAppr"); await sleep(300);
await click('#appr [data-ans="yes"]'); await waitFor("!pendingAppr");
check(await ev("return __ticks.some(x=>/already gone/.test(x[0]))"), "a refused yes says it had already gone");

// 4. answer in the terminal releases
await ev(`window.fetch=(u,o)=>{ if(String(u).includes('/api/approve/release')) __calls.push([String(u),JSON.parse(o.body),null]); return Promise.resolve(new Response('{"ok":true}',{status:200})); }; __calls.length=0; return 1`);
await card(); await waitFor("pendingAppr"); await sleep(300);
await click('#appr [data-term]'); await waitFor("!pendingAppr"); c = await calls();
check(c.length === 1 && c[0][0].endsWith("/api/approve/release") && c[0][1].id === "a1", "terminal button releases the request", JSON.stringify(c));

// 5. result lines
const lines = async (e) => { await ev(`__ticks.length=0; onEvent(${JSON.stringify(Object.assign({ t: "agent_result", agent: "codex" }, e))}); return 1`); return ev("return __ticks.map(x=>x.join('|')).join(';')"); };
check(await lines({ state: "ran", ok: true, exit: 0 }) === "Codex ran it ✓|false", "ran ok");
check(await lines({ state: "ran", ok: false, exit: 2 }) === "Codex ran it ✗ (exit 2)|true", "ran failed with exit");
check(await lines({ state: "denied", ok: false }) === "denied in Nixi|false", "denied");
check((await lines({ state: "ran-after-deny", ok: true })).endsWith("|true"), "ran after deny is red");
check(await lines({ state: "unknown", ok: null }) === "approved, result unknown|false", "unknown");

// 6. the working signal (#227): code in his eyes and no panel, no flash, no attnPend; done ends it
await ev("attnPend=null; return 1");
await ev("onEvent({t:'attention',from:'claude',name:'Claude',kind:'working',project:'p',text:''}); return 1");
check(await waitFor("!document.querySelector('#code').classList.contains('on')&&getComputedStyle(document.querySelector('#eL .ce')).display!=='none'"), "working shows code in his eyes, no panel");
check(await ev("return attnPend===null && !chip.classList.contains('act')"), "working sets no attnPend and no chip");
// his own tool run still opens the sheet (busy keeps it out after the tool): full size, at 70%, beside him
await ev("busy=true; CP.tool({t:'tool',id:'geo1',name:'Bash',input:{command:'true',description:'geometry'}}); return 1");
await sleep(1500);
const fz = await ev("const c=document.querySelector('#code').getBoundingClientRect(), b=document.querySelector('#body > .ball').getBoundingClientRect(); const over=Math.max(0,Math.min(c.right,b.right)-Math.max(c.left,b.left))*Math.max(0,Math.min(c.bottom,b.bottom)-Math.max(c.top,b.top)); return {w:Math.round(c.width), over:Math.round(over), ball:Math.round(b.width*b.height)};");
check(fz.w <= 300 && fz.over < fz.ball * 0.1, "the sheet is drawn small (<=300 px) and doesn't cover him", JSON.stringify(fz));
// he shrinks to the corner when idle (peek): the panel shrinks with him and stays beside him, not over him
await ev("document.body.classList.add('peek'); return 1"); await sleep(1500);
const pk = await ev("const c=document.querySelector('#code').getBoundingClientRect(), b=document.querySelector('#body > .ball').getBoundingClientRect(); const over=Math.max(0,Math.min(c.right,b.right)-Math.max(c.left,b.left))*Math.max(0,Math.min(c.bottom,b.bottom)-Math.max(c.top,b.top)); return {w:Math.round(c.width), over:Math.round(over), ball:Math.round(b.width*b.height)};");
check(pk.w < 250 && pk.over < pk.ball * 0.1, "in peek the panel is scaled down with him and doesn't cover him", JSON.stringify(pk));
await ev("document.body.classList.remove('peek'); return 1"); await sleep(1000);
await ev("busy=false; CP.done(); onEvent({t:'attention',from:'claude',name:'Claude',kind:'done',project:'p',text:''}); return 1");
check(await waitFor("!document.querySelector('#code').classList.contains('on')&&CP.n()===0"), "his turn done and the agent's done: no panel, no entry");

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
