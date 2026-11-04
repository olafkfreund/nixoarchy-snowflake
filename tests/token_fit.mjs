// The window hands the page its token as window.__nixiT (a user script), not in the URL (#181).
//   node tests/token_fit.mjs <cdp-port> <page-url, no #> <token>
// Needs a headless Chromium started with --disable-gpu (never a desktop browser, #138). Exit 0 = pass.
const [port, url, token] = process.argv.slice(2);
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
await send("Page.addScriptToEvaluateOnNewDocument", { source: `window.__nixiT=${JSON.stringify(token)};` });
await send("Page.navigate", { url }); await sleep(4500);

const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
check(!url.includes("#"), "the page URL has no fragment", url);
const status = await ev("return (await post('/api/settings',{})).status");
check(status === 200, "a token-protected request succeeds", String(status));
const left = await ev("return typeof window.__nixiT");
check(left === "undefined", "window.__nixiT is gone once read", left);
process.exit(fails.length ? 1 : 0);
