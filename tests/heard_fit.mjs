// #216: the page passes how he was reached ({path,media}) to /api/ask, shows "that wasn't me" only while the server says
// it can be marked, and fills the mic settings line from /api/heard.
//   node tests/heard_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Exit 0 = pass.
const [port, url] = process.argv.slice(2);
const [base, hash = ""] = url.split("#");
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
await send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, screenWidth: 1920, screenHeight: 1080, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: `${base}?native=1#${hash}` }); await sleep(4500);
const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const poll = async js => { for (let n = 0; n < 100; n++) { if (await ev(`return !!(${js})`)) return true; await sleep(30); } return false; };

// stub the endpoints; /api/ask is recorded, /api/listen is a stream the test feeds
await ev(`window.__of=window.fetch; window.__asks=[]; window.__streams=[]; window.__heard={totals:{},mark_open:false}; window.__notme=0;
  window.fetch=(u,o)=>{ const p=new URL(String(u),location.href).pathname;
    if(p==='/api/ask'){ __asks.push(JSON.parse(o.body)); return Promise.resolve(new Response(new ReadableStream({start(c){c.close()}}))); }
    if(p==='/api/listen') return Promise.resolve(new Response(new ReadableStream({start(c){__streams.push(c)}})));
    if(p==='/api/follow'||p==='/api/listen/stop'||p==='/api/quick') return Promise.resolve(new Response('{}'));
    if(p==='/api/heard') return Promise.resolve(new Response(JSON.stringify(__heard)));
    if(p==='/api/heard/not-me'){ __notme++; return Promise.resolve(new Response('{"ok":true}')); }
    return __of(u,o); };
  window.__frame=(i,e)=>__streams[i].enqueue(new TextEncoder().encode('data: '+JSON.stringify(e)+'\\n\\n'));
  window.__reset=async()=>{ if(rec) stopRec(true); rec=null; transcribing=false; follow=false; busy=false; hiddenNow=false; playing=false; hideAsk(); menu(false); __asks.length=0; await new Promise(r=>setTimeout(r,60)); };
  setInterval(()=>{ nextFidAt=1e15; },50); return 1`);
const reset = () => ev("await __reset(); return 1");
const asks = () => ev("return __asks.slice()");
const H = (path, media = "on") => ({ path, media });
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
// feed a recording started by an event: open, then the transcript, then close the stream
const record = async (i, text) => { await poll(`__streams.length>${i}`); await ev(`__frame(${i},{t:'open'}); __frame(${i},{t:'text',text:${JSON.stringify(text)}}); __streams[${i}].close(); return 1`); };

await reset();
await ev(`onEvent({t:'wake',text:'hey nixi what time is it',path:'wake',media:'on'}); return 1`);
check(await poll("__asks.length"), "a name with words posts to /api/ask");
check(same((await asks())[0]?.heard, H("wake")), "a name with words carries heard", JSON.stringify(await asks()));

await reset();
{ const i = await ev("return __streams.length"); await ev(`onEvent({t:'wake',text:'',path:'wake',media:'off'}); return 1`); await record(i, "what time is it"); }
check(await poll("__asks.length"), "a bare name then a recording posts");
check(same((await asks())[0]?.heard, H("wake", "off")), "a bare name then a recording carries heard", JSON.stringify(await asks()));

await reset();
await ev(`onEvent({t:'wake',follow:true,text:'and tomorrow then',path:'follow',media:'unknown'}); return 1`);
check(await poll("__asks.length"), "a follow-up posts");
check(same((await asks())[0]?.heard, H("follow", "unknown")) && (await asks())[0].follow === true, "a follow-up carries heard", JSON.stringify(await asks()));

await reset();
await ev(`playing=true; onEvent({t:'barge',listen:true,text:'stop that and say it again',path:'barge',media:'on'}); return 1`);
check(await poll("__asks.length"), "a barge with words posts");
check(same((await asks())[0]?.heard, H("barge")), "a barge with words carries heard", JSON.stringify(await asks()));

await reset();
{ const i = await ev("return __streams.length"); await ev(`playing=true; onEvent({t:'barge',listen:true,text:'',path:'barge',media:'off'}); return 1`); await record(i, "say it again"); }
check(await poll("__asks.length"), "a barge then a recording posts");
check(same((await asks())[0]?.heard, H("barge", "off")), "a barge then a recording carries heard", JSON.stringify(await asks()));

await reset();
{ const i = await ev("return __streams.length"); await ev(`startRec('auto'); return 1`); await record(i, "a clicked question"); }
check(await poll("__asks.length"), "a clicked recording posts");
check((await asks())[0] && !("heard" in (await asks())[0]), "a clicked recording carries no heard", JSON.stringify(await asks()));

await reset();
await ev(`send('typed question here'); return 1`); await poll("__asks.length");
check((await asks())[0] && !("heard" in (await asks())[0]), "a typed question carries no heard");

// the menu item
await reset();
const item = () => ev("const b=document.querySelector('#menu .mb[data-a=notme]'); return b?getComputedStyle(b).display:'missing'");
await ev("window.__heard={totals:{},mark_open:false}; menu(true); return 1"); await sleep(300);
check(await item() === "none", "the 'that wasn't me' item is hidden without mark_open", await item());
await ev("menu(false); window.__heard={totals:{},mark_open:true}; menu(true); return 1"); await sleep(400);
check(await item() !== "none" && await item() !== "missing", "the item shows while mark_open", await item());
await ev("document.body.classList.add('nixi'); return 1");
check(await item() !== "none", "the item also shows in nixi mode (the bridged build hides .nx items)", await item());
await ev("document.body.classList.remove('nixi'); return 1");
await ev("document.querySelector('#menu .mb[data-a=notme]').click(); return 1"); await sleep(300);
check(await ev("return __notme") === 1, "clicking it posts /api/heard/not-me");
await ev("menu(false); window.__heard={totals:{},mark_open:false}; menu(true); return 1"); await sleep(400);
check(await item() === "none", "the item hides again when mark_open turns false", await item());
await reset();

// the settings line
await ev("window.__heard={totals:{wake:{on:{sent:3,ignored:1,not_me:1},off:{sent:2}},follow:{off:{sent:4}},barge:{on:{not_me:2}}},mark_open:false}; settings(true); return 1");
check(await poll("$('#heardLine').textContent"), "the mic settings line fills");
check(await ev("return $('#heardLine').textContent") === "This week: 5 times by name, 4 follow-ups · 3 not for me (3 while media played)", "the line reads as planned", await ev("return $('#heardLine').textContent"));
await ev("settings(false); window.__heard={totals:{},mark_open:false}; settings(true); return 1"); await sleep(400);
check(await ev("return $('#heardLine').textContent") === "", "the line is empty when all counts are zero");

check(exc.size === 0, "no page exceptions", [...exc].join(" ;; "));
await send("Target.closeTarget", { targetId: t.id }).catch(() => {});
console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall pass");
process.exit(fails.length ? 1 : 0);
