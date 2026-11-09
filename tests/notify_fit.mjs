// Pins how notifications show today, before clicking one opens its app (#215 step 1):
//   node tests/notify_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
// Nothing is spoken: sfx and enqueue are stubbed, and POSTs to /api/notify/* are recorded and answered locally.
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
await send("Emulation.setDeviceMetricsOverride", { width: 820, height: 620, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url }); await sleep(4000);

const fails = []; let checks=0;
const check = (ok, what, got) => { checks++; if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + JSON.stringify(got)}`); } };
const eq = (got, want, what) => check(JSON.stringify(got) === JSON.stringify(want), what, got);

// a real mouse click at a point, or a real key
const click = async (x, y) => { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
  await send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1 }); await sleep(120); };
const esc = async () => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }); await sleep(120); };
const centre = sel => ev(`const r=(${sel}).getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];`);

// setup: record the POSTs to /api/notify/*, stub sound and speech and the mic, and give a clean slate (reset())
await ev(`
  window.__posts=[]; window.__sfx=[]; window.__say=[]; window.__rec=[];
  const f0=window.fetch.bind(window);
  window.fetch=(u,o)=>{ if(/\\/api\\/(notify\\/(act|seen)|nudge)/.test(String(u))){ window.__posts.push({u:String(u),b:JSON.parse((o&&o.body)||'{}')}); return Promise.resolve(new Response(JSON.stringify({ok:window.__actOk!==false}))); } return f0(u,o); };
  sfx=n=>window.__sfx.push(n); enqueue=(t,o)=>window.__say.push(t); startRec=m=>window.__rec.push(m);
  window.reset=()=>{ notifyQ.length=0; nudgeQ.clear(); remClose(); if(notifyRow) notifyClear(); notifyRow=null; notifyAt=0; notifyBurst={cat:'',n:0,t:0}; propOn=null; busy=false; playing=false; rec=null; follow=false; pendingAppr=null;
    SIT.meeting=false; SIT.fullscreen=false; SIT.locked=false; muted=false; info.hover=false; info.sfx=true; info.notify_sound=true; info.notify_speak=[]; info.notify_details=false;
    mailT.forEach(clearTimeout); mailT=[]; $('#mailPop').classList.remove('on','open','up'); window.__posts.length=0; window.__sfx.length=0; window.__say.length=0; window.__rec.length=0; clicks=[]; };
  window.N=(key,cat,o={})=>Object.assign({t:'notify',key,category:cat,app:'',source:'',summary:'',body:'',icon:''},o);
  window.acts=()=>window.__posts.filter(p=>p.u.includes('/act')).map(p=>p.b);
  reset(); return 1;`);
await sleep(300);
const idle = await ev(`return notifyIdle();`);
check(idle === true, "the page is not idle in the test browser, so rows would be held back", idle);

// 1. notifyText, exact strings
const txt = await ev(`const T=(e,n)=>notifyText(e,n); return [
  T(N('a','mail',{app:'thunderbird',source:'thunderbird',summary:'Hello'}),1),
  T(N('a','chat',{app:'teams-for-linux',source:'teams-for-linux',summary:'Ann',body:'one two three four five six seven eight'}),1),
  T(N('a','chat',{app:'slack',summary:'Ann',body:'x'.repeat(200)}),1).length,
  T(N('a','other',{app:'nixi-job',summary:'build done'}),1),
  T(N('a','other',{app:'nixi-job'}),1),
  T(N('a','chat',{app:'teams-for-linux',source:'teams-for-linux',summary:'Ann',body:'hi'}),3),
  T(N('a','other'),1), T(N('a','mail'),1)];`);
eq(txt, ["✉ New mail · Thunderbird · Hello", "💬 New message in Teams · Ann · one two three four five six", 90, "✔ build done", "✔ A long command finished",
  "💬 3 new in Teams", "🔔 Notification", "✉ New mail"], "notifyText strings");

// 2. a chat row: bubble, icon, caption, then ×2
const chat1 = await ev(`reset(); notifyIn(N('c1','chat',{app:'teams-for-linux',source:'teams-for-linux',summary:'Ann',body:'hi there',icon:'0123456789abcdef'}));
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,900));
  const P=SIT_P.chat; return {cat:propOn&&propOn.cat, n:propOn&&propOn.n, op:+P.g.getAttribute('opacity'), href:P.img.getAttribute('href'), disp:P.img.getAttribute('display'),
    row:himEl.textContent, key:notifyRow&&notifyRow.key, ntf:cap.classList.contains('ntf')};`);
check(chat1.cat === "chat" && chat1.n === 1, "chat prop is on with n 1", chat1);
check(chat1.op > 0, "the bubble is visible (opacity above 0)", chat1.op);
check(chat1.href === "/api/icon/0123456789abcdef", "the bubble icon's href (it then hides itself when the image 404s)", chat1);
check(chat1.row.includes("💬 New message in Teams · Ann · hi there") && chat1.ntf && chat1.key === "c1", "the chat row text", chat1);
const chat2 = await ev(`notifyIn(N('c2','chat',{app:'teams-for-linux',source:'teams-for-linux',summary:'Bob'}));
  await new Promise(r=>setTimeout(r,300)); const P=SIT_P.chat; return {n:propOn.n, badge:P.bt.textContent, show:P.badge.getAttribute('display'), q:notifyQ.map(e=>e.key), row:notifyRow.key};`);
check(chat2.n === 2 && chat2.badge === "×2" && chat2.show !== "none", "a second chat gives n 2 and ×2", chat2);
eq([chat2.q, chat2.row], [["c2"], "c1"], "the second chat waits in notifyQ; the first row stays");

// 3. a burst of 3: second queued, third rewrites the visible row (key and counted text) without entering notifyQ
const burst = await ev(`reset(); const c={app:'teams-for-linux',source:'teams-for-linux'};
  notifyIn(N('b1','chat',{...c,summary:'A'})); const a=notifyRow.key;
  notifyIn(N('b2','chat',{...c,summary:'B'})); const q2=notifyQ.map(e=>e.key);
  notifyIn(N('b3','chat',{...c,summary:'C'})); const q3=notifyQ.map(e=>e.key); const k3=notifyRow.key, t3=notifyRow.span.textContent;
  const at=notifyAt; notifyIn(N('b3','chat',{...c,summary:'D'}));          // the same key: changed in place
  return {a,q2,q3,k3,t3,same:notifyRow.span.textContent,q4:notifyQ.map(e=>e.key),atSame:at===notifyAt, seen:window.__posts.filter(p=>p.u.includes('/seen')).map(p=>p.b.key)};`);
eq([burst.a, burst.q2, burst.q3, burst.k3], ["b1", ["b2"], ["b2"], "b3"], "burst: first shows, second queued, third takes the row's key and leaves the queue alone");
check(burst.t3.includes("3 new in Teams") && !burst.t3.includes("· C"), "burst: counted text", burst.t3);
check(burst.same.includes("New message in Teams · D") && JSON.stringify(burst.q4) === '["b2"]' && burst.atSame, "same key updates in place, no new arrival", burst);

// 4. the queue: at most 8 waiting, a row older than 4 s is dropped
const qq = await ev(`reset(); notifyAt=performance.now()+1e7;
  for(let i=0;i<12;i++) notifyIn(N('q'+i,'other'));
  const len=notifyQ.length; notifyQ.length=0; notifyAt=0;
  const now=performance.now(); notifyQ.push({...N('old','other'),rt:now-5000},{...N('new','other'),rt:now});
  notifyDrain(now); return {len, shown:notifyRow&&notifyRow.key, left:notifyQ.length};`);
eq([qq.len, qq.shown, qq.left], [8, "new", 0], "queue holds 8; an old row is dropped, the fresh one shows");

// 5. a mail row: #mailPop on / open / up, then off in mailPop's order, at about its times
const mail = await ev(`reset(); const el=$('#mailPop'), seen={}, t0=performance.now(); const had={on:0,open:0,up:0};
  notifyIn(N('m1','mail',{app:'thunderbird',source:'thunderbird',summary:'Hi'}));
  await new Promise(res=>{ const iv=setInterval(()=>{ const t=Math.round(performance.now()-t0);
    for(const k of ['on','open','up']){ const has=el.classList.contains(k); if(has&&!(k in had&&had[k])){ had[k]=1; seen[k+'+']=t; } if(!has&&had[k]===1&&!(k+'-' in seen)) seen[k+'-']=t; }
    if(t>6500){ clearInterval(iv); res(); } },25); });
  return seen;`);
const inR = (v, a, b) => v >= a && v <= b;
check(mail["on+"] < mail["open+"] && mail["open+"] < mail["up+"], "mail: on, then open, then up", mail);
check(inR(mail["on+"], 0, 500) && inR(mail["open+"], 300, 900) && inR(mail["up+"], 600, 1400), "mail: the times of on, open and up", mail);
check(mail["up-"] < mail["open-"] && mail["open-"] < mail["on-"], "mail: up goes, then open, then on", mail);
check(inR(mail["up-"], 3900, 4900) && inR(mail["open-"], 4300, 5300) && inR(mail["on-"], 4700, 5800), "mail: the times of up, open and on going", mail);

// 6. sound and speech
const snd = await ev(`const run=async(setup,e)=>{ reset(); setup(); notifyIn(e); await new Promise(r=>setTimeout(r,100)); return {sfx:[...window.__sfx], say:[...window.__say]}; };
  const chat=N('s1','chat',{app:'slack',summary:'Ann'}), mail=N('s2','mail',{app:'thunderbird',source:'thunderbird',summary:'Secret'});
  return {
    on: await run(()=>{},chat),
    off: await run(()=>{ info.notify_sound=false; },chat),
    muted: await run(()=>{ muted=true; info.notify_speak=['chat']; },chat),
    speak: await run(()=>{ info.notify_speak=['chat']; },chat),
    mailSpeak: await run(()=>{ info.notify_speak=['mail']; },mail),
    mailSubject: await run(()=>{ info.notify_speak=['mail']; info.notify_details=true; info.notify_speak_subject=true; },mail),
    notListed: await run(()=>{ info.notify_speak=['mail']; },chat),
    meeting: await run(()=>{ SIT.meeting=true; info.notify_speak=['chat']; },chat)};`);
eq([snd.on.sfx, snd.on.say], [["chat"], []], "sound plays, nothing is said when notify_speak is empty");
eq([snd.off.sfx, snd.off.say], [[], []], "notify_sound false plays no sound");
eq([snd.muted.sfx, snd.muted.say], [[], []], "muted: no sound and no speech");
eq(snd.speak.say, ["New message"], "notify_speak says the kind of row");
eq(snd.mailSpeak.say, ["New mail from Thunderbird"], "a spoken mail names the sender, not the subject");
eq(snd.mailSubject.say, ["Secret"], "a spoken mail reads the subject only when both details settings are on");
eq(snd.notListed.say, [], "a category not in notify_speak is not spoken");
eq([snd.meeting.sfx, snd.meeting.say], [[], []], "a meeting silences sound and speech");

// 7. real clicks and Esc
const [px, py] = (await ev(`reset(); notifyIn(N('k1','chat',{app:'teams-for-linux',source:'teams-for-linux',summary:'Ann'})); await new Promise(r=>setTimeout(r,500)); return 1;`), await centre("plate"));
await click(px, py);
eq(await ev(`return [acts(), notifyRow];`), [[{ key: "k1", how: "open" }], null], "a click on the row posts act open and clears it");
await ev(`reset(); notifyIn(N('k2','mail',{app:'thunderbird',source:'thunderbird',summary:'Hi'})); await new Promise(r=>setTimeout(r,1800)); return 1;`);
const [ex, ey] = await centre("$('#mailPop')");
check(await ev(`return $('#mailPop').classList.contains('on');`), "the envelope is out before it is clicked");
await click(ex, ey);
eq(await ev(`return [acts(), $('#mailPop').classList.contains('on')];`), [[{ key: "k2", how: "open" }], false], "a click on the envelope posts act open with its key");
await ev(`reset(); notifyIn(N('k3','other',{summary:'x'})); await new Promise(r=>setTimeout(r,500)); return 1;`);
await esc();
eq(await ev(`return [acts(), notifyRow];`), [[{ key: "k3", how: "dismiss" }], null], "Esc posts act dismiss and clears the row");

// 8. a click on him with nothing showing starts listening
await ev(`reset(); await new Promise(r=>setTimeout(r,2500)); return 1;`);
const [bx, by] = await centre("E.body");
const hit = await ev(`const e=document.elementFromPoint(${bx},${by}); return !!e&&E.body.contains(e);`);
check(hit, "his body is under its own centre point");
await click(bx, by);
eq(await ev(`return [window.__rec, acts()];`), [["auto"], []], "a click on him with nothing showing starts listening and posts no act");

// 9. the moving chat bubble opens the row currently on screen
const bubble = async () => { await ev(`await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); await new Promise(r=>setTimeout(r,150)); return 1;`);
  const p = await centre("SIT_P.chat.g");
  check(await ev(`return SIT_P.chat.g.contains(document.elementFromPoint(${p[0]},${p[1]}));`), "the bubble's centre is a real hit target", p);
  return p; };
await ev(`reset(); notifyIn(N('bubble','chat',{app:'teams-for-linux',source:'teams-for-linux'})); return 1;`);
const [cx, cy] = await bubble();
await click(cx, cy);
eq(await ev(`return [acts(), window.__rec, notifyRow];`), [[{key:"bubble",how:"open"}], [], null], "bubble click opens the visible row without listening");

await ev(`reset(); notifyIn(N('away','chat',{app:'teams-for-linux'})); return 1;`);
await bubble();
await click(bx, by);
eq(await ev(`return [window.__rec, acts()];`), [["auto"], []], "clicking him away from the bubble still starts listening");

await ev(`reset(); notifyIn(N('gone','chat',{app:'teams-for-linux'})); await new Promise(r=>setTimeout(r,3700)); return 1;`);
const [gx, gy] = await centre("SIT_P.chat.g");
const goneHit = await ev(`return E.body.contains(document.elementFromPoint(${gx},${gy}));`);
await click(gx, gy);
eq(await ev(`return [acts(), window.__rec, notifyRow&&notifyRow.key];`), [[], goneHit?["auto"]:[], "gone"], "after the bubble goes, its spot keeps its old click behaviour");

for(const [count, key] of [[2,"two1"],[3,"three3"]]){
  await ev(`reset(); const c={app:'teams-for-linux',source:'teams-for-linux'};
    notifyIn(N('${count===2?"two1":"three1"}','chat',c)); notifyIn(N('${count===2?"two2":"three2"}','chat',c));
    ${count===3?"notifyIn(N('three3','chat',c));":""} return 1;`);
  const [x,y] = await bubble();
  await click(x,y);
  eq(await ev(`return [acts(), notifyQ.map(e=>e.key), window.__rec];`), [[{key,how:"open"}], [count===2?"two2":"three2"], []], `×${count} bubble opens the on-screen key and leaves the second queued`);
  const next = await ev(`notifyAt=0; notifyDrain(performance.now()); return notifyRow&&notifyRow.key;`);
  eq(next, count===2?"two2":"three2", `×${count} second row shows next`);
}

await ev(`reset(); notifyIn(N('redrawn','chat',{app:'teams-for-linux'})); applyLook({...LOOK}); return 1;`);
const [lx,ly] = await bubble();
await click(lx,ly);
eq(await ev(`return [acts(), window.__rec];`), [[{key:"redrawn",how:"open"}], []], "bubble click survives a look redraw");

// a drag that ends on the bubble stays a drag; the second click of a double click opens nothing and doesn't start listening
await ev(`reset(); notifyIn(N('drag','chat',{app:'teams-for-linux'})); return 1;`);
const [dx, dy] = await bubble();
await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: dx, y: dy, buttons: 0 });
await send("Input.dispatchMouseEvent", { type: "mousePressed", x: dx, y: dy, button: "left", buttons: 1, clickCount: 1 });
await ev(`dragged=true; return 1;`);                // (what moving more than 5 px does; the window moves with him, so the release lands on the bubble)
await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: dx, y: dy, button: "left", buttons: 0, clickCount: 1 });
await sleep(120);
eq(await ev(`return [acts(), dragged];`), [[], false], "a drag ending on the bubble opens nothing");
await ev(`reset(); notifyIn(N('dbl','chat',{app:'teams-for-linux'})); return 1;`);
const [e2x, e2y] = await bubble();
await click(e2x, e2y);
for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: e2x, y: e2y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 2 });
await sleep(150);
eq(await ev(`return [acts(), window.__rec];`), [[{ key: "dbl", how: "open" }], []], "a double click opens once and doesn't start listening");
// his words wiped the row: the bubble's click carries on to him
await ev(`reset(); notifyIn(N('wiped','chat',{app:'teams-for-linux'})); return 1;`);
const [wx, wy] = await bubble();
await ev(`himEl.textContent=''; return 1;`);
await click(wx, wy);
eq(await ev(`return [acts(), window.__rec];`), [[], ["auto"]], "with the row wiped, a bubble click goes to him");

// 10. cards (#214): row.card = {runs, buttons, image?, rev?}
const CARD = `(key,o={})=>N(key,'chat',{app:'slack',summary:'Ann',card:{runs:[{t:'<img src=x onerror=window.__pwn=1>',b:true,i:false,u:false,host:''},{t:'\\n'},{t:'a link',b:false,i:true,u:false,host:'ex.com'},{t:'ex.com',b:false,i:false,u:false,host:'ex.com'}],buttons:['Yes','No'],rev:'r1',image:'0123456789abcdef',...o},...(o.top||{})})`;
await ev(`window.C=${CARD}; window.__seenLog=[]; const ns=notifySeen; notifySeen=k=>{ window.__seenLog.push([k,!!(notifyRow&&notifyRow.span&&notifyRow.span.isConnected)]); ns(k); };   // (was a card on screen when it was marked seen?)
  window.seenOf=k=>window.__seenLog.filter(x=>x[0]===k).map(x=>x[1]); return 1;`);
const cardUp = async (look = "return 1;") => ev(`reset(); __seenLog.length=0; const now=performance.now(); notifyQ.push({...C('cd1'),rt:now},{...N('x2','other'),rt:now}); notifyDrain(now);
  const out=(()=>{${look}})(); await new Promise(r=>setTimeout(r,400)); return out;`);
const cd = await cardUp(`const d=document.querySelector('#him .ncard'); if(!d) return null; const t=sel=>[...d.querySelectorAll(sel)];   // (read at once: the 404 for the fake id removes the image a moment later)
  return {imgs:t('img').map(i=>i.getAttribute('src')), btns:t('button').map(b=>b.textContent), more:(t('.nmore')[0]||{}).textContent, who:t('.nch span')[0].textContent, summary:(t('.ncs')[0]||{}).textContent,
    runs:t('.ncr span:not(.nh)').map(s=>[s.textContent,s.style.fontWeight,s.style.fontStyle,s.style.textDecoration]), br:t('.ncr br').length, hosts:t('.nh').map(s=>s.textContent),
    pwn:window.__pwn===undefined, seen:seenOf('cd1'), ntf:cap.classList.contains('ntf'),
    cut:[...d.children].filter(c=>{ const r=c.getBoundingClientRect(), h=himEl.getBoundingClientRect(); return r.top<h.top-0.5||r.bottom>h.bottom+0.5||r.top<0; }).map(c=>c.className)};`);
check(cd !== null, "a row with a card is drawn as a card");
if (cd) {
  eq(cd.imgs, ["/api/nimage/0123456789abcdef"], "the card has one preview, from /api/nimage/<id>");
  eq([cd.btns, cd.more, cd.who, cd.summary], [["Yes", "No"], "+1", "Slack", "Ann"], "card: buttons, +N, app name, summary");
  eq(cd.runs, [["<img src=x onerror=window.__pwn=1>", "700", "", ""], ["a link", "", "italic", "underline"], ["ex.com", "", "", "underline"]], "card: runs are text with their styles; a link is underlined");
  eq([cd.br, cd.hosts, cd.pwn], [1, [" (ex.com)"], true], "card: a line break, the host only when the label differs, no sender markup becomes an element");
  eq(cd.seen, [true], "card: marked seen once, only after it was drawn");
  eq(cd.cut, [], "card: header, text, picture and buttons all show, none clipped by the caption (#214 by-hand check)");
}
await sleep(5800);
check(await ev(`return !!document.querySelector('#him .ncard');`), "a card is still up at 6.2 s");
await sleep(1400);
check(await ev(`return !document.querySelector('#him .ncard')&&notifyRow===null;`), "a card is gone by 7.6 s");

// a real click on a button posts its index and rev, and doesn't open
await cardUp();
const [bbx, bby] = await centre("document.querySelectorAll('#him .ncard button')[1]");
check(await ev(`return document.querySelectorAll('#him .ncard button')[1].contains(document.elementFromPoint(${bbx},${bby}));`), "the second button is a real hit target");
await click(bbx, bby);
eq(await ev(`return [acts(), notifyRow];`), [[{ key: "cd1", how: "action", i: 1, rev: "r1" }], null], "a click on a button posts its index and rev, not open");
// ok:false: the page says so
await ev(`window.__ticks=[]; window.tick0=tick; tick=t=>window.__ticks.push(t); window.__actOk=false; return 1;`);
await cardUp();
const [b0x, b0y] = await centre("document.querySelectorAll('#him .ncard button')[0]");
await click(b0x, b0y);
await sleep(200);
eq(await ev(`const t=window.__ticks; tick=window.tick0; window.__actOk=true; return t;`), ["That notification has gone."], "ok:false shows that the notification has gone");
// a click on the card body opens; Esc dismisses
await cardUp();
const [sx, sy] = await centre("document.querySelector('#him .ncard .ncr')");
await click(sx, sy);
eq(await ev(`return acts();`), [{ key: "cd1", how: "open" }], "a click on the card opens it");
await cardUp();
await esc();
eq(await ev(`return [acts(), notifyRow];`), [[{ key: "cd1", how: "dismiss" }], null], "Esc dismisses a card");

// in the notch (body.bar) a card is neither drawn nor marked seen
await ev(`reset(); document.body.classList.add('bar'); notifyIn(C('bar1')); await new Promise(r=>setTimeout(r,500)); return 1;`);
eq(await ev(`const r=[!!document.querySelector('.ncard'), seenOf('bar1'), notifyRow, notifyQ.length]; document.body.classList.remove('bar'); return r;`), [false, [], null, 0], "bar mode: a card isn't drawn or marked seen");
// under an open panel (#cap is hidden) neither
await ev(`reset(); document.body.classList.add('pnl'); notifyIn(C('pnl1')); await new Promise(r=>setTimeout(r,500)); return 1;`);
eq(await ev(`const r=[!!document.querySelector('.ncard'), seenOf('pnl1'), notifyRow, notifyQ.length]; document.body.classList.remove('pnl'); return r;`), [false, [], null, 0], "panel open: a card isn't drawn or marked seen");

// a same-key update with a card goes through the queue and is drawn as a card, seen after
const upd = await ev(`reset(); notifyIn(N('u1','chat',{app:'slack',summary:'old'})); await new Promise(r=>setTimeout(r,300));
  notifyIn(C('u1')); const queued=notifyQ.map(e=>e.key), still=!document.querySelector('.ncard');
  notifyAt=0; notifyDrain(performance.now()); await new Promise(r=>setTimeout(r,300));
  return {queued, still, card:!!document.querySelector('#him .ncard'), seen:seenOf('u1')};`);
eq([upd.queued, upd.still, upd.card, upd.seen], [["u1"], true, true, [false, true]], "same-key card update: queued, drawn as a card, marked seen only after");
// the third message of a burst with a card is not merged into "3 new"
const bur = await ev(`reset(); const c={app:'slack',source:'slack'};
  notifyIn(N('g1','chat',{...c,summary:'A'})); notifyIn(N('g2','chat',{...c,summary:'B'})); notifyIn(C('g3'));
  const q=notifyQ.map(e=>e.key), row=notifyRow.key, txt=notifyRow.span.textContent;
  notifyAt=0; notifyDrain(performance.now()); notifyAt=0; notifyDrain(performance.now()); await new Promise(r=>setTimeout(r,300));
  return {q,row,txt,card:!!document.querySelector('#him .ncard'),seen:seenOf('g3')};`);
eq([bur.q, bur.row, bur.card, bur.seen], [["g2", "g3"], "g1", true, [true]], "a burst's third message with a card is queued, drawn as a card, marked seen after");
check(!bur.txt.includes("3 new"), "a burst's card is not merged into a count", bur.txt);
// a row with no card: seen before it is shown, as today
await ev(`reset(); notifyIn(N('p1','other',{summary:'x'})); await new Promise(r=>setTimeout(r,300)); return 1;`);
eq(await ev(`return [seenOf('p1'), !document.querySelector('.ncard')];`), [[false], true], "a row with no card is marked seen as before and is not a card");

// Quiet gate: all signals arrive through situation; no fetch in these cases reaches the server.
const quiet = await ev(`
  const fetch0=window.fetch, restore0=restore, poke0=poke, aside0=sayAside, burst0=burstLines;
  window.fetch=()=>Promise.resolve(new Response(JSON.stringify({ok:true,go:false})));
  window.__restore=[]; window.__poke=[]; window.__aside=[]; window.__burst=[];
  restore=(...a)=>__restore.push(a); poke=(...a)=>__poke.push(a); sayAside=t=>__aside.push(t); burstLines=(...a)=>__burst.push(a);
  const sit=o=>onEvent({t:'situation',...Object.fromEntries(Object.entries(SIT).filter(([k])=>k!=='weather')),weather:SIT.weather,...o});
  const prep=()=>{ reset(); sit({dnd:false,locked:false,fullscreen:false,meeting:false,weather:null});
    notifyAt=performance.now()+1e7; lastSpokeAt=-1e9; himEl.textContent=''; cap.classList.add('off'); capOn=false;
    __restore.length=0; __poke.length=0; __aside.length=0; __sfx.length=0; __say.length=0; };
  const held={};
  for(const flag of ['dnd','locked','fullscreen','meeting']){
    prep(); onEvent({t:'nudge',kind:'break',text:'stretch',speak:false,wait:null});
    const start=performance.now(); sit({[flag]:true}); __restore.length=0; __poke.length=0;
    nudgeDrain(start+610000);
    const during={q:nudgeQ.size,caption:himEl.textContent,speech:__aside.length+__say.length,restore:__restore.length,poke:__poke.length};
    sit({[flag]:false}); notifyAt=0; nudgeDrain(start+610001);
    const after={q:nudgeQ.size,caption:himEl.textContent};
    nudgeDrain(start+610002); after.once=nudgeQ.size===0&&himEl.textContent==='stretch';
    held[flag]={during,after};
  }
  prep(); sit({dnd:true}); onEvent({t:'nudge',kind:'break',text:'under DND',wait:null});
  const arrival={restore:__restore.length,q:nudgeQ.size};
  prep(); AMB.sys=[]; sit({dnd:true,weather:'snow'}); onEvent({t:'ambient',sys:['bad.service'],glint:true,alert:true,cal:{time:'10:00',title:'test'}});
  const unasked={poke:[...__poke],burst:__burst.length,restore:__restore.length,line:chip.textContent};
  prep(); sit({dnd:true}); onEvent({t:'attention',kind:'done',name:'Claude',from:'claude',text:''});
  const finished={mark:AM&&AM.kind,from:AM&&AM.from,line:chip.textContent,sfx:[...__sfx],poke:[...__poke],restore:__restore.length};
  prep(); sit({dnd:true}); onEvent({t:'approve',id:'quiet-a1',agent:'codex',tool:'Bash',detail:'true',confirm:'click',always:false});
  const approval={shown:apEl.classList.contains('on'),id:pendingAppr&&pendingAppr.id};
  pendingAppr=null; apprQ.length=0; apEl.classList.remove('on'); document.body.classList.remove('appr');
  const expiry={};
  for(const [name,wait,delta] of [['none',null,610000],['short',60,61000]]){
    prep(); onEvent({t:'nudge',kind:'break',text:name,speak:true,wait}); const start=performance.now();
    notifyAt=0; nudgeDrain(start+delta); expiry[name]={q:nudgeQ.size,said:__aside.includes(name)};
  }
  restore=restore0; poke=poke0; sayAside=aside0; burstLines=burst0; window.fetch=fetch0;
  return {held,arrival,unasked,finished,approval,expiry};`);
for (const flag of ['dnd','locked','fullscreen','meeting']) {
  eq(quiet.held[flag].during, {q:1,caption:'',speech:0,restore:0,poke:0}, `${flag}: queued break stays silent past ten minutes`);
  eq(quiet.held[flag].after, {q:0,caption:'stretch',once:true}, `${flag}: queued break draws once when quiet ends`);
}
eq(quiet.arrival, {restore:0,q:1}, "a nudge arriving under DND does not restore him");
eq(quiet.unasked, {poke:[],burst:0,restore:0,line:'📅 10:00 test'}, "snow, a failed unit and a new generation stay quiet; the alert line shows");
check(quiet.finished.mark==='done'&&quiet.finished.from==='claude'&&quiet.finished.line.includes('finished')&&quiet.finished.sfx.length===0&&quiet.finished.poke.length===0&&quiet.finished.restore===0,
  "an agent finish under DND shows its mark and line silently", quiet.finished);
eq(quiet.approval, {shown:true,id:'quiet-a1'}, "an approval card still shows under DND");
eq(quiet.expiry, {none:{q:0,said:true},short:{q:0,said:false}}, "null wait survives ten minutes; a 60 second wait expires");

// #209: reminder controls use the id last displayed and yield to quiet and approvals.
const rem=await ev(`const seen={}; const show=(kind,id,speak=false)=>{ reset(); SIT.dnd=false; notifyAt=0; onEvent({t:'nudge',kind,id,text:'stretch',speak,wait:null}); return !remEl.hidden; };
  const settle=()=>new Promise(r=>setTimeout(r,0));   // (post() waits for the token first)
  setEl.classList.remove('on'); panelEl.classList.remove('on'); calmCheck();   // (a panel left open by an earlier case makes him calm, which hides the chip)
  seen.break=show('break',11); remEl.querySelector('[data-rem="10"]').click(); await settle();
  seen.snooze=__posts.filter(p=>p.u==='/api/nudge').map(p=>p.b); seen.closed=remEl.hidden;
  seen.doneShown=show('water',12); remEl.querySelector('[data-rem="done"]').click(); await settle(); seen.done=__posts.filter(p=>p.u==='/api/nudge').map(p=>p.b);
  seen.cpu=show('cpu',13);
  reset(); SIT.dnd=true; onEvent({t:'nudge',kind:'break',id:14,text:'held',speak:false,wait:null}); seen.held=remEl.hidden&&nudgeQ.size===1;
  SIT.dnd=false; notifyAt=0; nudgeDrain(performance.now()); seen.released=!remEl.hidden;
  seen.spoken=show('break',15,true);
  show('break',16); capTick(performance.now()+7000); seen.outlives=cap.classList.contains('off')&&!remEl.hidden;
  show('break',17); onEvent({t:'approve',id:'rem-a1',agent:'codex',tool:'Bash',detail:'true',confirm:'click',always:false}); seen.approval=remEl.hidden; pendingAppr=null; apprQ.length=0; apEl.classList.remove('on'); document.body.classList.remove('appr');
  show('break',18); document.body.classList.add('bar'); remSync(); seen.bar=remEl.hidden; document.body.classList.remove('bar');
  show('break',19); onEvent({t:'nudge',kind:'break',id:20,text:'new',speak:false,wait:null}); seen.replaced=remEl.hidden; notifyAt=0; nudgeDrain(performance.now()); seen.newer=seen.replaced&&remId===20&&!remEl.hidden;
  show('break',21); SIT.dnd=true; remSync(); seen.quiet=remEl.hidden; SIT.dnd=false;
  show('break',22); remSync(remUntil+1); seen.expired=remEl.hidden;
  show('break',23); remEl.querySelector('[data-rem="30"]').click(); await settle(); seen.thirty=__posts.filter(p=>p.u==='/api/nudge').at(-1).b;
  reset(); return seen;`);
check(rem.break&&rem.closed&&JSON.stringify(rem.snooze)==='[{"id":11,"act":"snooze","minutes":10}]',"break chip posts 10 minute snooze and closes",rem);
check(rem.doneShown&&JSON.stringify(rem.done)==='[{"id":12,"act":"dismiss"}]',"Done posts dismiss without minutes",rem);
check(!rem.cpu&&rem.held&&rem.released&&rem.spoken,"CPU has no chip; DND holds a reminder; spoken break has a chip",rem);
check(rem.outlives&&rem.approval&&rem.bar&&rem.newer&&rem.quiet,"chip outlives caption and closes for approval, bar, newer reminder and quiet",rem);
check(rem.expired&&JSON.stringify(rem.thirty)==='{"id":23,"act":"snooze","minutes":30}',"chip expires at 30 seconds and posts 30 minute snooze",rem);

if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log(`notify fit: ${checks} checks, 0 failed`);
process.exit(0);
