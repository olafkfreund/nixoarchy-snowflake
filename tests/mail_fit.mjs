// The mail board and its reply card (#210 step 5):
//   node tests/mail_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Fails with `CUT <what>`, exit 1.
// The server's mail routes are stubbed in the page (fetch), so no gog, Ollama or mail is involved; every POST is recorded.
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
  await send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1, pointerType: "mouse" }); await sleep(150); };
const key = async (k, code, vk, text) => { for (const type of ["keyDown", "keyUp"])
  await send("Input.dispatchKeyEvent", { type: type === "keyDown" && text ? "keyDown" : type, key: k, code, windowsVirtualKeyCode: vk, ...(type === "keyDown" && text ? { text } : {}) }); await sleep(150); };

const HOSTILE = `<img src=x onerror="window.__xss=1"><b>bold</b>`;
const BOARD = { t: "stage", v: 1, kind: "mail", trust: "mechanic", has_prev: false, rows: [
  { account: "you@example.com", from: "sender@example.com", subject: "Lunch on Friday?", age: "5m", hear: "h1", reply: "r1" },
  { account: "you@example.com", from: HOSTILE, subject: HOSTILE, age: "2h", hear: "h2", reply: "r2" },
  { account: "other@example.com", from: "", subject: "Couldn't read other@example.com", age: "", hear: null, reply: null }] };
const DRAFT = { draft: "d1", account: "you@example.com", to: ["reply@example.com"], cc: ["cc@example.com"], subject: "Re: Lunch on Friday?", body: "Yes, noon works.\n<b>no markup</b>", from: "sender@example.com", reply_to_differs: true };

// stub the mail routes and /api/settings in the page; record every POST to /api/mail/*
await ev(`
  window.__posts=[]; window.__q={draft:[],hear:null};
  const f0=window.fetch.bind(window), R=o=>Promise.resolve(new Response(JSON.stringify(o)));
  window.fetch=(u,o)=>{ u=String(u);
    if(u.includes('/api/mail/options')) return R({accounts:['you@example.com','other@example.com'],models:['gemma4:e4b']});
    if(u.includes('/api/settings')&&o&&o.method==='POST'){ const b=JSON.parse(o.body||'{}'); window.__posts.push({u:'/api/settings',b}); info={...info,...b}; return R(info); }
    const m=u.match(/\\/api\\/mail\\/(\\w+)/);
    if(m&&o&&o.method==='POST'){ const b=JSON.parse(o.body||'{}'); window.__posts.push({u:m[0],b});
      if(m[1]==='draft'){ const q=window.__q.draft.shift()||{d:${JSON.stringify(DRAFT)},delay:0}; return new Promise(r=>setTimeout(()=>r(new Response(JSON.stringify(q.d))),q.delay)); }
      if(m[1]==='hear') return R(window.__q.hear||{from:'x',subject:'s',summary:'A short summary.'});
      if(m[1]==='send') return R({sent:true,thread:'t'});
      return R({ok:true}); }
    return f0(u,o); };
  setInterval(()=>{ nextFidAt=1e15; },50);
  info={...info,idle_mode:'off',bridge:true,mail_on:true}; if(window.setIdle) setIdle('full');
  window.mp=()=>window.__posts.filter(p=>p.u.startsWith('/api/mail')); window.sendPosts=()=>window.__posts.filter(p=>p.u==='/api/mail/send').length;
  window.show=async()=>{ stageClose(); await new Promise(r=>setTimeout(r,320)); onEvent(${JSON.stringify(BOARD)}); await new Promise(r=>setTimeout(r,500)); };
  window.btn=(txt,root)=>[...(root||stgEl).querySelectorAll('button')].find(b=>b.textContent===txt);
  window.openCard=async(row)=>{ await show(); [...stgEl.querySelectorAll('.it')][row].querySelectorAll('button')[1].click(); const ta=stgEl.querySelector('.mcard textarea'); ta.value='Yes, noon works.'; ta.dispatchEvent(new Event('input')); };
  window.review=async()=>{ btn('Review').click(); await new Promise(r=>setTimeout(r,200)); };
  return 1;`);
await sleep(300);
const shownTxt = (await ev(`return typeof stageMail+typeof mailCardOpen`));
check(shownTxt === "functionfunction", "the page has stageMail and mailCardOpen", shownTxt);

// 1. the board: markup is text, a failed row has no buttons
const b1 = await ev(`await show(); const rows=[...stgEl.querySelectorAll('.it')];
  return {title:$('#stgT').textContent, n:rows.length, cls:stgEl.className, imgs:stgEl.querySelectorAll('#stgBd img,#stgBd b').length, xss:window.__xss||0,
    hostile:rows[1].textContent.includes(${JSON.stringify(HOSTILE)}), btns:rows.map(r=>[...r.querySelectorAll('button')].map(b=>b.textContent)), failed:rows[2].textContent.includes("Couldn't read other@example.com"),
    first:rows[0].textContent, st:stgState};`);
eq([b1.title, b1.n, b1.imgs, b1.xss, b1.hostile], ["Mail", 3, 0, 0, true], "the board has three rows, and markup in a field is text");
eq(b1.btns, [["Hear", "Reply"], ["Hear", "Reply"], []], "Hear and Reply on a row with tokens, none on a failed row");
check(b1.first.includes("Lunch on Friday?") && b1.first.includes("sender@example.com") && b1.first.includes("you@example.com") && b1.first.includes("5m") && b1.st === "open", "the row shows subject, sender, account and age", b1);

// 2. Hear: posts the token and shows the summary as text
const h = await ev(`window.__q.hear={from:'a',subject:'s',summary:'Sum <i>x</i>'}; const row=stgEl.querySelectorAll('.it')[0]; row.querySelectorAll('button')[0].click(); await new Promise(r=>setTimeout(r,200));
  return {posts:mp(), txt:row.querySelector('.mst').textContent, el:row.querySelectorAll('.mst *').length};`);
eq([h.posts, h.txt, h.el], [[{ u: "/api/mail/hear", b: { token: "h1" } }], "Sum <i>x</i>", 0], "Hear posts its token and shows the summary as text");

// 3. the reply card shows the draft exactly as served, and markup in it is text
const c3 = await ev(`window.__posts.length=0; await openCard(1); window.__q.draft=[{d:{...${JSON.stringify(DRAFT)},account:${JSON.stringify(HOSTILE)},to:[${JSON.stringify(HOSTILE)}],cc:['c@x.com'],subject:${JSON.stringify(HOSTILE)}},delay:0}];
  btn('Review').click(); await new Promise(r=>setTimeout(r,250)); const card=stgEl.querySelector('.mcard'), rev=card.querySelector('.mrev');
  return {posts:mp(), imgs:card.querySelectorAll('img,b:not(.mln b)').length, xss:window.__xss||0, txt:rev.textContent, send:!!btn('Send',rev), pre:rev.querySelector('pre').textContent, warn:rev.querySelector('.mwarn')&&rev.querySelector('.mwarn').textContent, form:!!card.closest('form')};`);
eq(c3.posts, [{ u: "/api/mail/draft", b: { token: "r2", text: "Yes, noon works.", all: false } }], "Review posts the row's reply token and the words");
check(c3.imgs === 0 && c3.xss === 0 && c3.txt.includes(HOSTILE) && !c3.form, "markup in the account, To and subject shows as text; the card is not in a form", c3);
check(c3.send && c3.pre === DRAFT.body && c3.warn === `Replies go to ${HOSTILE}, not the sender sender@example.com`, "Send, the body exactly, and the Reply-To warning", c3);
const c3b = await ev(`const rev=stgEl.querySelector('.mrev'); return rev.textContent.includes('Cc: c@x.com');`);
check(c3b, "Cc is shown");

// 4. a real pointer click on Send posts once
await ev(`await openCard(0); await review(); window.__posts.length=0; const s=btn('Send'); s.scrollIntoView({block:'center'}); return 1`);
await sleep(200);
const [sx, sy] = await ev(`const r=btn('Send').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];`);
check(await ev(`const r=btn('Send').getBoundingClientRect(); return document.elementFromPoint(${sx},${sy})===btn('Send')`), "Send is under the pointer in the test view");
await mouse(sx, sy);
const s4 = await ev(`return {posts:window.__posts.filter(p=>p.u==='/api/mail/send'), msg:stgEl.querySelector('.mmsg').textContent, hasSend:!!btn('Send')};`);
eq(s4.posts, [{ u: "/api/mail/send", b: { draft: "d1", text: DRAFT.body } }], "a real mouse click on Send posts /api/mail/send once, with the draft id and the served body");
eq([s4.msg, s4.hasSend], ["Sent", false], "then it says Sent and Send is gone (no retry)");

// 5. nothing else sends
await ev(`await openCard(0); await review(); window.__posts.length=0; return 1`);
await ev(`btn('Send').click(); return 1`); await sleep(150);
eq(await ev(`return sendPosts()`), 0, "send.click() posts nothing (no pointer type)");
await ev(`btn('Send').focus(); return document.activeElement===btn('Send')`);
await key("Tab", "Tab", 9); await key("Shift", "ShiftLeft", 16);
await ev(`btn('Send').focus(); return 1`);
await key(" ", "Space", 32, " ");
eq(await ev(`return [document.activeElement===btn('Send'), sendPosts()]`), [true, 0], "Space on the focused Send posts nothing");
await key("Enter", "Enter", 13, "\r");
eq(await ev(`return sendPosts()`), 0, "Enter on the focused Send posts nothing");
await ev(`document.activeElement.blur(); return 1`);
await key("Enter", "Enter", 13, "\r"); await key("y", "KeyY", 89, "y");
const k5 = await ev(`return {sends:sendPosts(), ask:ask.classList.contains('on'), inp:input.value, apr:!!pendingAppr};`);
check(k5.sends === 0 && !k5.ask && k5.inp === "", "Enter and y outside the textarea do nothing", k5);
const v5 = await ev(`const a=voiceAnswer('yes',true), b=voiceAnswer('send it',true); return [sendPosts(), mp().filter(p=>p.u!=='/api/mail/draft').map(p=>p.u)];`);
eq(v5, [0, []], "voiceAnswer('yes') and ('send it') post nothing");
const v6 = await ev(`return [voiceAnswer.toString(), askAloud.toString()].filter(f=>/mail/i.test(f)).length;`);
eq(v6, 0, "voiceAnswer and askAloud don't mention mail");

// 6. editing hides Send until Review is pressed again
const e6 = await ev(`const ta=stgEl.querySelector('.mcard textarea'); const had=!!btn('Send'); ta.value+=' x'; ta.dispatchEvent(new Event('input')); const gone=!btn('Send');
  await review(); return [had, gone, !!btn('Send')];`);
eq(e6, [true, true, true], "editing hides Send; Review brings it back");

// 7. an older draft answer arriving after a newer one changes nothing
const o7 = await ev(`await openCard(0); window.__q.draft=[{d:{...${JSON.stringify(DRAFT)},draft:'old',body:'OLD BODY'},delay:700},{d:{...${JSON.stringify(DRAFT)},draft:'new',body:'NEW BODY'},delay:50}];
  btn('Review').click(); await new Promise(r=>setTimeout(r,100)); btn('Review').click(); await new Promise(r=>setTimeout(r,1100));
  return {pre:stgEl.querySelector('.mbody').textContent, n:stgEl.querySelectorAll('.mbody').length};`);
eq(o7, { pre: "NEW BODY", n: 1 }, "an older draft answer that arrives later changes nothing");

// 8. Cancel posts the draft id and drops the card; closing the board cancels a live draft
const x8 = await ev(`window.__posts.length=0; btn('Cancel').click(); await new Promise(r=>setTimeout(r,100)); const a=[mp().map(p=>[p.u,p.b]), !!stgEl.querySelector('.mcard')];
  await openCard(0); await review(); window.__posts.length=0; stageClose(); await new Promise(r=>setTimeout(r,100)); return [a, mp().map(p=>[p.u,p.b])];`);
eq(x8, [[[["/api/mail/cancel", { draft: "new" }]], false], [["/api/mail/cancel", { draft: "d1" }]]], "Cancel posts the draft id; closing the board cancels a live draft");

// 9. a held mail board adds nothing to his caption
const d9 = await ev(`await show(); stageHide(false); himSet('Earlier words'); stgHeld=${JSON.stringify(BOARD)}; const text=stageText(stgHeld); dismiss(); await new Promise(r=>setTimeout(r,200));
  return {text, him:himEl.textContent, held:stgHeld};`);
check(d9.text === "" && !d9.him.includes("Lunch") && !d9.him.includes("sender@example.com") && d9.held === null && d9.him.trim() === "Earlier words", "stageText is '' for mail and dismiss() leaves the caption without mail text", d9);

// 10. the menu has no Mail item while mail is off, or outside nixi mode
const m10 = await ev(`const vis=()=>{ layoutMenu(); return !$('#menu .mb[data-a=mail]').classList.contains('off'); };
  info.mail_on=false; info.bridge=true; const off=vis(); info.mail_on=true; info.bridge=false; const plain=vis(); info.bridge=true; const on=vis();
  window.__posts.length=0; $('#menu .mb[data-a=mail]').click(); await new Promise(r=>setTimeout(r,150)); return [off,plain,on,mp().map(p=>p.u)];`);
eq(m10, [false, false, true, ["/api/mail/open"]], "the menu's Mail item shows only with mail_on in nixi mode, and posts /api/mail/open");

// 11. Settings: the Mail block comes after the notification settings, lists the addresses and models, and saves them
const s11 = await ev(`info.mail_on=true; info.mail_accounts=['you@example.com']; info.mail_model=''; mailOptT=0; settings(true,'look'); renderSettings(); await new Promise(r=>setTimeout(r,300));
  const order=['#nsChips','#mailRow','#asideSw'].map(s=>$(s)); const pos=a=>a.compareDocumentPosition(order[1]);
  const accts=[...document.querySelectorAll('#mailAccts input')].map(i=>[i.dataset.mailAcct,i.checked]), models=[...document.querySelectorAll('#mailModel option')].map(o=>o.value);
  return {after:!!(order[0].compareDocumentPosition(order[1])&4), before:!!(order[1].compareDocumentPosition(order[2])&4), sw:$('#mailSw').checked, shown:!$('#mailOpts').hidden, accts, models};`);
check(s11.after && s11.before && s11.sw && s11.shown, "the Mail block sits after the notification settings and shows its options when on", s11);
eq([s11.accts, s11.models], [[["you@example.com", true], ["other@example.com", false]], ["", "gemma4:e4b"]], "one checkbox per address and a model list with None first");
const s12 = await ev(`window.__posts.length=0; const c=document.querySelector('#mailAccts input[data-mail-acct="other@example.com"]'); c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));
  await new Promise(r=>setTimeout(r,200)); const m=$('#mailModel'); m.value='gemma4:e4b'; m.dispatchEvent(new Event('change',{bubbles:true})); await new Promise(r=>setTimeout(r,200));
  const sw=$('#mailSw'); sw.checked=false; sw.dispatchEvent(new Event('change',{bubbles:true})); await new Promise(r=>setTimeout(r,200));
  return window.__posts.filter(p=>p.u==='/api/settings').map(p=>p.b);`);
eq(s12, [{ mail_accounts: ["you@example.com", "other@example.com"] }, { mail_model: "gemma4:e4b" }, { mail_on: false }], "ticking an address, choosing a model and the switch post their settings");

// 12. no orphan drafts: a stale answer's draft is cancelled, and closing during a Review cancels the one on its way
const o12 = await ev(`closePanels(); await openCard(0); window.__q.draft=[{d:{...${JSON.stringify(DRAFT)},draft:'stale'},delay:300}]; window.__posts.length=0;
  btn('Review').click(); const ta=stgEl.querySelector('.mcard textarea'); ta.value+=' more'; ta.dispatchEvent(new Event('input')); await new Promise(r=>setTimeout(r,600));
  const a=mp().map(p=>[p.u,p.b.draft||null]);
  await openCard(0); window.__q.draft=[{d:{...${JSON.stringify(DRAFT)},draft:'late'},delay:300}]; window.__posts.length=0;
  btn('Review').click(); await new Promise(r=>setTimeout(r,50)); stageClose(); await new Promise(r=>setTimeout(r,100)); const mid=mp().map(p=>[p.u,p.b.draft||null]);
  await new Promise(r=>setTimeout(r,500)); return [a, mid, mp().map(p=>[p.u,p.b.draft||null])];`);
eq(o12[0], [["/api/mail/draft", null], ["/api/mail/cancel", "stale"]], "a draft answer nobody wants is cancelled");
eq(o12[1], [["/api/mail/draft", null], ["/api/mail/cancel", "pending"]], "closing while a Review is on its way cancels it at once");
eq(o12[2].filter(x => x[1] === "late").length, 1, "and the draft that then arrives is cancelled too");

if (fails.length) { console.log(`${fails.length} check(s) failed`); process.exit(1); }
console.log("mail fit ok");
process.exit(0);
