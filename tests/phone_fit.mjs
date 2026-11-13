// The phone cards, the approval caption and phone-call silence (#231 step 12):
//   node tests/phone_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
// The /api/phone/* routes are stubbed in the page (fetch) and every POST is recorded, so no Flux or phone is involved.
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
await send("Emulation.setDeviceMetricsOverride", { width: 1100, height: 760, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4500);

const fails = [];
const check = (ok, what, got) => { if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + JSON.stringify(got)}`); } };
const eq = (got, want, what) => check(JSON.stringify(got) === JSON.stringify(want), what, got);
const mouse = async (x, y) => { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
  await send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1, pointerType: "mouse" }); await sleep(200); };
const centre = sel => ev(`const r=(${sel}).getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];`);

const PICK = { t: "stage", v: 1, kind: "phone_pick", title: "Which phone?", do: "ring", devices: [{ id: "d1", name: "Pixel" }, { id: "d2", name: "Tablet" }] };
const DRAFT = { t: "stage", v: 1, kind: "phone_draft", title: "Text", draft: "dr1", name: "Ann", number: "+4712345678", text: "On my way", send_label: "Send", length_error: "Too long", send_error: "Couldn't send" };

// stub the phone routes in the page and record every POST (with its headers); sound and speech are stubbed too
await ev(`
  window.__posts=[]; window.__sfx=[]; window.__say=[];
  const f0=window.fetch.bind(window), R=o=>Promise.resolve(new Response(JSON.stringify(o)));
  window.fetch=(u,o)=>{ u=String(u); const m=u.match(/\\/api\\/phone\\/(\\w+)/);
    if(m&&o&&o.method==='POST'){ window.__posts.push({u:m[0],b:JSON.parse(o.body||'{}'),click:(o.headers||{})['X-Nixi-Click']||null}); return R({ok:true,say:'Done'}); }
    return f0(u,o); };
  sfx=n=>window.__sfx.push(n); enqueue=(t,o)=>window.__say.push(t);
  setInterval(()=>{ nextFidAt=1e15; },50);
  info={...info,idle_mode:'off',bridge:true}; if(window.setIdle) setIdle('full');
  window.show=async ev=>{ stageClose(); await new Promise(r=>setTimeout(r,320)); onEvent(ev); await new Promise(r=>setTimeout(r,500)); };
  return 1;`);
await sleep(300);

// 1. the ring chooser: two devices, two buttons, a click posts that device's id
const p1 = await ev(`await show(${JSON.stringify(PICK)}); window.__posts.length=0;
  const rows=[...stgEl.querySelectorAll('.it')]; return {n:rows.length, names:rows.map(r=>r.querySelector('.lb').textContent), btns:rows.map(r=>[...r.querySelectorAll('button')].map(b=>b.textContent))};`);
eq([p1.n, p1.names, p1.btns], [2, ["Pixel", "Tablet"], [["Ring"], ["Ring"]]], "the chooser has one Ring button per device");
await ev(`stgEl.querySelectorAll('.it')[1].querySelector('button').click(); await new Promise(r=>setTimeout(r,200)); return 1`);
eq(await ev(`return window.__posts.map(p=>[p.u,p.b])`), [["/api/phone/ring", { id: "d2", what: "ring" }]], "a click on the second Ring posts /api/phone/ring with that device id");

// 2. the draft card: only a trusted pointer click sends, and it carries X-Nixi-Click
await ev(`await show(${JSON.stringify(DRAFT)}); window.__posts.length=0; return 1`);
await ev(`stgEl.querySelector('.mcard .sb').click(); await new Promise(r=>setTimeout(r,200)); return 1`);
eq(await ev(`return window.__posts.length`), 0, "a synthetic click on Send posts nothing");
const [sx, sy] = await centre(`stgEl.querySelector('.mcard .sb')`);
check(await ev(`const b=stgEl.querySelector('.mcard .sb'); return document.elementFromPoint(${sx},${sy})===b`), "Send is under the pointer in the test view");
await mouse(sx, sy);
const s2 = await ev(`return {posts:window.__posts, msg:stgEl.querySelector('.mmsg').textContent};`);
eq(s2.posts.map(p => [p.u, p.b]), [["/api/phone/send", { draft: "dr1", text: "On my way" }]], "a real click on Send posts /api/phone/send once, with the draft id and the text");
check(s2.posts.length === 1 && typeof s2.posts[0].click === "string" && s2.posts[0].click.length > 0, "that POST carries X-Nixi-Click", s2.posts);
eq(s2.msg, "Done", "the server's words show under the card");

// 3. the approval caption: shown as given, cleared by empty text
const c3 = await ev(`phoneCap('Approve on your Pixel (sudo)'); await new Promise(r=>setTimeout(r,300)); const on=himEl.textContent;
  onEvent({t:'phone_cap',text:''}); await new Promise(r=>setTimeout(r,300)); const off=himEl.textContent;
  onEvent({t:'phone_cap',text:'Approve on your Pixel (sudo)'}); await new Promise(r=>setTimeout(r,300)); const again=himEl.textContent; phoneCap('');
  return {on,off,again,spoken:window.__say.length};`);
check(c3.on.includes("Approve on your Pixel (sudo)") && c3.again.includes("Approve on your Pixel (sudo)"), "phone_cap shows the caption", c3);
eq([c3.off, c3.spoken], ["", 0], "empty text clears the caption; the caption is never spoken");

// 4. a phone_call notify row gets no category speech; the same row without it does
const say = await ev(`const N=(key,o)=>Object.assign({t:'notify',key,category:'chat',app:'teams-for-linux',source:'teams-for-linux',summary:'Ann',body:'hi',icon:''},o);
  const run=async e=>{ notifyQ.length=0; if(notifyRow) notifyClear(); notifyRow=null; notifyAt=0; notifyBurst={cat:'',n:0,t:0}; propOn=null; busy=false; playing=false; rec=null; follow=false; pendingAppr=null;
    SIT.meeting=false; SIT.fullscreen=false; SIT.locked=false; SIT.phone_call=false; muted=false; info.hover=false; info.notify_speak=['chat']; window.__say.length=0;
    notifyIn(e); await new Promise(r=>setTimeout(r,200)); return [...window.__say]; };
  return {plain:await run(N('n1')), call:await run(N('n2',{phone_call:true}))};`);
check(say.plain.length === 1, "control: a chat row speaks when category speech is on", say);
eq(say.call, [], "a chat row with phone_call:true speaks nothing");

console.log(fails.length ? `${fails.length} cut` : "phone fit: ok");
process.exit(fails.length ? 1 : 0);
