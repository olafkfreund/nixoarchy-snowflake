// Settings → Voice (#176) and the page playback path:
//   node tests/voice_fit.mjs <cdp-port> <page-url>
// Needs a headless Chromium started with --disable-gpu. Fails with `CUT <what>` and exit 1.
const [port, url] = process.argv.slice(2);
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map();
const offOrigin = [];
ws.addEventListener("message", e => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  if (m.method === "Network.requestWillBeSent") {
    const u = m.params?.request?.url || "";
    if (/^https?:\/\//i.test(u) && !u.startsWith("http://127.0.0.1:")) offOrigin.push(u);
  }
});
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = async js => {
  const r = await send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
await send("Page.enable");
await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 820, height: 620, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await sleep(3000);

const fails = [];
const check = (ok, what, got) => { if (!ok) { fails.push(what); console.log(`CUT  ${what}${got === undefined ? "" : "  → " + got}`); } };

// 1. Open Settings → Voice: ElevenLabs section is visible before ElevenLabs engine is chosen,
//    and ElevenLabs engine chip is disabled with its reason until eleven_on + voice are set.
const init = await ev(`
  await refresh();
  settings(true, 'voice');
  await new Promise(r => setTimeout(r, 150));
  const chips = [...document.querySelectorAll('#engChips button')].map(b => ({
    id: b.dataset.eng, text: b.textContent, disabled: b.disabled, reason: b.dataset.reason, title: b.title, on: b.classList.contains('on')
  }));
  const elRow = document.getElementById('elevenRow');
  const elVis = !!elRow && getComputedStyle(elRow).display !== 'none';
  const notice = document.getElementById('elevenNotice');
  const confirmIn = document.getElementById('elevenConfirm');
  const swIn = document.getElementById('elevenSw');
  const offNote = document.getElementById('elevenOffNote');
  const orderOk = !!(notice && confirmIn && swIn &&
    (notice.compareDocumentPosition(confirmIn) & Node.DOCUMENT_POSITION_FOLLOWING) &&
    (confirmIn.compareDocumentPosition(swIn) & Node.DOCUMENT_POSITION_FOLLOWING));
  return {
    chips, elVis, orderOk,
    noticeTxt: notice ? notice.textContent : '',
    offTxt: offNote ? offNote.textContent : '',
    keyTxt: document.getElementById('elevenKey')?.textContent || '',
    whyTxt: document.getElementById('engWhy')?.textContent || ''
  };
`);
check(init.elVis, "ElevenLabs section not visible before engine chosen");
check(init.orderOk, "notice and confirm must precede the on/off switch in DOM");
check(init.noticeTxt === "What he says out loud is sent to ElevenLabs. That can include anything in his answers.", "notice text mismatch", init.noticeTxt);
check(init.offTxt === "Text already sent may still count on your ElevenLabs account.", "off note text mismatch", init.offTxt);
const elChip0 = init.chips.find(c => c.id === "elevenlabs");
check(elChip0 && elChip0.disabled && /Switch it on|ElevenLabs/i.test(elChip0.reason), "ElevenLabs chip not disabled with reason initially", JSON.stringify(elChip0));
check(init.chips.map(c => c.id).join(",") === "auto,kokoro,piper,espeak,elevenlabs,off", "engine chip ids", init.chips.map(c => c.id).join(","));

// 2. Switching on without confirm gets 400 from /api/settings and shows the error under the control.
const unconfirmed = await ev(`
  const cf = document.getElementById('elevenConfirm');
  const sw = document.getElementById('elevenSw');
  cf.checked = false;
  sw.checked = true;
  sw.dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 250));
  return {
    swChecked: sw.checked,
    elevenOn: !!(info.eleven && info.eleven.on),
    err: document.getElementById('elevenErr')?.textContent || ''
  };
`);
check(!unconfirmed.elevenOn && !unconfirmed.swChecked, "eleven_on turned on without confirm", JSON.stringify(unconfirmed));
check(/confirm/i.test(unconfirmed.err), "400 confirm error not shown under control", unconfirmed.err);

// 3. Confirming and switching on enables eleven_on, loads voices safely with textContent/hx() (zero <img>/<script>).
const confirmed = await ev(`
  const cf = document.getElementById('elevenConfirm');
  const sw = document.getElementById('elevenSw');
  cf.checked = true;
  sw.checked = true;
  sw.dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 350));
  const vBox = document.getElementById('elevenVoices');
  const rows = [...vBox.querySelectorAll('.el-v')].map(r => ({
    id: r.dataset.vid,
    name: r.querySelector('b')?.textContent || '',
    meta: r.querySelector('small')?.textContent || ''
  }));
  const elChip = document.querySelector('#engChips button[data-eng="elevenlabs"]');
  return {
    elevenOn: !!(info.eleven && info.eleven.on),
    err: document.getElementById('elevenErr')?.textContent || '',
    rows,
    imgs: vBox.querySelectorAll('img,script').length,
    voiceChipsImgs: document.getElementById('voiceChips').querySelectorAll('img,script').length,
    pwn: window.__pwn || null,
    elChipDisabled: elChip ? elChip.disabled : null,
    elChipReason: elChip ? elChip.dataset.reason : ''
  };
`);
check(confirmed.elevenOn && confirmed.err === "", "eleven_on did not turn on after confirm", JSON.stringify(confirmed));
check(confirmed.rows.length === 2, "expected 2 voices in #elevenVoices", JSON.stringify(confirmed.rows));
check(confirmed.rows.some(r => r.name === "<img src=x onerror=alert(1)>"), "XSS voice name not rendered as literal text", JSON.stringify(confirmed.rows));
check(confirmed.imgs === 0 && confirmed.voiceChipsImgs === 0 && confirmed.pwn === null, "XSS payload created DOM elements or ran script", JSON.stringify(confirmed));
check(confirmed.elChipDisabled && /Choose an ElevenLabs voice/i.test(confirmed.elChipReason), "ElevenLabs chip should stay disabled until a voice is chosen", JSON.stringify(confirmed));

// 4. Preview fetches /api/eleven/preview/<id> with X-Nixi-Token from page origin, plays blob: URL, does not change eleven_voice or used_today.
const prev = await ev(`
  const beforeVoice = info.eleven?.voice || '';
  const beforeUsed = info.eleven?.used_today || 0;
  const btn = document.querySelector('#elevenVoices button[data-eprev="21m00Tcm4TlvDq8ikWAM"]');
  btn.click();
  await new Promise(r => setTimeout(r, 350));
  await refresh();
  return {
    blobUrl: window.__lastPreviewUrl || btn.dataset.blobUrl || '',
    afterVoice: info.eleven?.voice || '',
    afterUsed: info.eleven?.used_today || 0,
    beforeVoice, beforeUsed,
    err: document.getElementById('elevenErr')?.textContent || ''
  };
`);
check(prev.blobUrl.startsWith("blob:http://127.0.0.1:"), "preview did not create a same-origin blob: URL", prev.blobUrl);
check(prev.afterVoice === prev.beforeVoice && prev.afterUsed === prev.beforeUsed, "preview changed eleven_voice or used_today", JSON.stringify(prev));
check(prev.err === "", "preview produced error", prev.err);

// 5. Choose selects the voice and enables the ElevenLabs engine chip; daily cap validation shows 400 error under control.
const chosen = await ev(`
  const pickBtn = document.querySelector('#elevenVoices button[data-epick="21m00Tcm4TlvDq8ikWAM"]');
  pickBtn.click();
  await new Promise(r => setTimeout(r, 250));
  const capIn = document.getElementById('elevenCap');
  capIn.value = '500';
  capIn.dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 250));
  const badCapErr = document.getElementById('elevenErr')?.textContent || '';
  capIn.value = '25000';
  capIn.dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 250));
  const fbBtn = document.querySelector('#fallbackChips button[data-fb="espeak"]');
  fbBtn.click();
  await new Promise(r => setTimeout(r, 250));
  document.querySelector('#engChips button[data-eng="elevenlabs"]').click();
  await new Promise(r => setTimeout(r, 250));
  const elChip = document.querySelector('#engChips button[data-eng="elevenlabs"]');
  return {
    voice: info.eleven?.voice,
    elChipDisabled: elChip.disabled,
    ttsChoice: info.tts_choice,
    tts: info.tts,
    hint: document.getElementById('voiceEng')?.textContent || '',
    badCapErr,
    cap: info.eleven?.cap,
    fb: info.tts_fallback,
    usageTxt: document.getElementById('elevenUsage')?.textContent || ''
  };
`);
check(chosen.voice === "21m00Tcm4TlvDq8ikWAM" && !chosen.elChipDisabled, "choosing voice did not enable ElevenLabs chip", JSON.stringify(chosen));
check(/1000|500000|cap/i.test(chosen.badCapErr), "invalid cap 400 error not shown under control", chosen.badCapErr);
check(chosen.cap === 25000 && chosen.fb === "espeak", "cap or fallback not updated", JSON.stringify(chosen));
check(chosen.ttsChoice === "elevenlabs" && chosen.tts === "elevenlabs", "ElevenLabs engine chip did not select elevenlabs", JSON.stringify(chosen));
check(chosen.hint === "Speaking with ElevenLabs (cloud)", "hint line does not say Speaking with ElevenLabs (cloud)", chosen.hint);

// 6. While ElevenLabs speaks, caption plate shows ☁ and hint says "Speaking with ElevenLabs (cloud)"; hides when done.
const cloudCap = await ev(`
  himSet('Hello from cloud'); capShow();
  spkMap.set(999, { cap: '', fresh: false });
  onEvent({ t: 'spk', id: 999, at: 0, dur: 0.4, engine: 'elevenlabs' });
  const during = {
    cloudClass: plate.classList.contains('cloud'),
    badgeTxt: document.getElementById('capCloud')?.textContent || '',
    badgeDisp: getComputedStyle(document.getElementById('capCloud')).display,
    hint: document.getElementById('voiceEng')?.textContent || ''
  };
  onEvent({ t: 'spk_done' });
  const after = {
    cloudClass: plate.classList.contains('cloud'),
    badgeTxt: document.getElementById('capCloud')?.textContent || '',
    badgeDisp: getComputedStyle(document.getElementById('capCloud')).display
  };
  return { during, after };
`);
check(cloudCap.during.cloudClass && cloudCap.during.badgeTxt === "☁" && cloudCap.during.badgeDisp !== "none", "☁ badge not shown on caption plate while ElevenLabs speaks", JSON.stringify(cloudCap.during));
check(cloudCap.during.hint === "Speaking with ElevenLabs (cloud)", "hint during cloud speech", cloudCap.during.hint);
check(!cloudCap.after.cloudClass && cloudCap.after.badgeTxt === "" && cloudCap.after.badgeDisp === "none", "☁ badge did not clear after speech ended", JSON.stringify(cloudCap.after));

// 7. Page sends 'reply' with every /api/say and /api/tts call, and drops stale queued/decoded clips after tts_gen.
const genTest = await ev(`
  const calls = [];
  const origFetch = window.fetch;
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/say' || u === '/api/tts') {
      try { calls.push({ u, body: JSON.parse(opts.body || '{}') }); } catch (e) {}
    }
    return origFetch(u, opts);
  };
  try {
    const wasNative = info.voice_native;
    muted = false;
    info.voice_native = true;
    say('First native sentence.');
    await new Promise(r => setTimeout(r, 80));
    shush();
    info.voice_native = false;
    say('First page sentence.');
    await new Promise(r => setTimeout(r, 80));
    shush();
    // Queue two already-decoded clips under current ttsGen, then fire tts_gen with ttsGen + 5
    const g0 = ttsGen;
    let resolveSlow;
    const slowP = new Promise(r => { resolveSlow = r; });
    q.push({ cap: 'holding', fresh: true, tg: g0, p: slowP });
    q.push({ cap: 'stale decoded', fresh: false, tg: g0, p: Promise.resolve({ b: {}, rate: 1, pause: 0.08, words: null, engine: 'elevenlabs', tg: g0 }) });
    const beforeQ = q.length;
    onEvent({ t: 'tts_gen', gen: g0 + 5 });
    const afterQ = q.length;
    resolveSlow(null);
    info.voice_native = wasNative;
    return { calls, beforeQ, afterQ, newTtsGen: ttsGen, expectedGen: g0 + 5 };
  } finally {
    window.fetch = origFetch;
  }
`);
const sayCall = genTest.calls.find(c => c.u === "/api/say");
const ttsCall = genTest.calls.find(c => c.u === "/api/tts");
check(sayCall && typeof sayCall.body.reply === "string" && sayCall.body.reply.length > 0, "/api/say missing reply id", JSON.stringify(sayCall));
check(ttsCall && typeof ttsCall.body.reply === "string" && ttsCall.body.reply.length > 0, "/api/tts missing reply id", JSON.stringify(ttsCall));
check(genTest.beforeQ === 2 && genTest.afterQ === 0 && genTest.newTtsGen === genTest.expectedGen, "stale queued/decoded clips not dropped on tts_gen", JSON.stringify(genTest));

// 8. spk_done with an id removes that item from spkMap (when cut_cloud drops queued cloud items).
const cutMap = await ev(`
  spkMap.set(42, { cap: 'dropped cloud sentence', fresh: true });
  onEvent({ t: 'spk_done', id: 42 });
  return { has42: spkMap.has(42) };
`);
check(!cutMap.has42, "spk_done with id did not remove item from spkMap");

// 9. Zero off-origin requests.
check(offOrigin.length === 0, "off-origin requests made", offOrigin.join(", "));

ws.close();
if (fails.length) process.exit(1);
console.log("OK   settings → voice, preview, cloud badge, reply id and tts_gen cut verified");
