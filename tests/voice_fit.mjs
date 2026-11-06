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
check(init.keyTxt.includes("Nixi reads the key from /run/agenix/api-elevenlabs (an agenix secret).") && !init.keyTxt.includes("~/.config/nixi/"), "key hint points at a refused path", init.keyTxt);
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
  const createBlobUrl=URL.createObjectURL; let blobUrl='';
  URL.createObjectURL=(...args)=>{ blobUrl=createBlobUrl(...args); return blobUrl; };
  btn.click();
  await new Promise(r => setTimeout(r, 350));
  URL.createObjectURL=createBlobUrl;
  await refresh();
  return {
    blobUrl,
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
    q.push({ cap: 'holding', fresh: true, tg: g0, engine: 'elevenlabs', p: slowP });
    q.push({ cap: 'stale decoded', fresh: false, tg: g0, engine: 'elevenlabs', p: Promise.resolve({ b: {}, rate: 1, pause: 0.08, words: null, engine: 'elevenlabs', tg: g0 }) });
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

const localCut = await ev(`
  const g0=ttsGen; q.push({tg:g0,engine:'espeak',p:Promise.resolve(null)});
  cutTtsGen(g0+1);
  const kept=q.some(x=>x.engine==='espeak'); q.length=0;
  return kept;
`);
check(localCut, "tts_gen dropped a local clip");

const pumpRace = await ev(`
  const oldFloor=floorPage; floorPage=async()=>true;
  try {
    q.length=0; pumpGen=-1;
    let finishOld, finishNew;
    const old={tg:ttsGen,engine:'elevenlabs',p:new Promise(r=>finishOld=r)};
    q.push(old); pump();
    await new Promise(r=>setTimeout(r,20));
    cutTtsGen(ttsGen+1);
    const next={tg:ttsGen,engine:'espeak',p:new Promise(r=>finishNew=r)};
    q.push(next);
    finishOld(null);
    await new Promise(r=>setTimeout(r,20));
    const kept=q.includes(next);
    finishNew(null); q.length=0;
    return kept;
  } finally { floorPage=oldFloor; }
`);
check(pumpRace, "pump removed the new sentence after its awaited cloud item was cut");

const confirmOff = await ev(`
  info.eleven.on=false; renderSettings();
  return !document.getElementById('elevenConfirm').checked;
`);
check(confirmOff, "turning ElevenLabs off left confirm checked");

// 8. spk_done with an id removes that item from spkMap (when cut_cloud drops queued cloud items).
const cutMap = await ev(`
  spkMap.set(42, { cap: 'dropped cloud sentence', fresh: true });
  onEvent({ t: 'spk_done', id: 42 });
  return { has42: spkMap.has(42) };
`);
check(!cutMap.has42, "spk_done with id did not remove item from spkMap");

// 9. Language (#177): first row of Voice tab, size/GPU hint, chips post language, status line while switching,
//    <html lang> follows lang_active, dates use active date locale, and page-spoken lines come from state_info.lines with English fallback.
const langTest = await ev(`
  settings(true, 'voice');
  await new Promise(r => setTimeout(r, 100));
  const panelRows = [...document.querySelectorAll('#panel-voice > .row')];
  const firstRowId = panelRows[0]?.id || '';
  info.whisper_device = 'cpu'; info.stt = 'ready'; delete info.gpu; delete info.cuda;
  showInfo();
  const hintCpu = document.getElementById('langHint')?.textContent || '';
  info.whisper_device = 'cuda';
  showInfo();
  const hintGpu = document.getElementById('langHint')?.textContent || '';
  info.whisper_device = 'cpu';
  showInfo();
  const chipList = [...document.querySelectorAll('#langChips button')].map(b => ({
    lang: b.dataset.lang, text: b.textContent, on: b.classList.contains('on')
  }));
  const initHtmlLang = document.documentElement.lang;

  // Item 4: clicking the language already active does nothing visible (no request, no status)
  const activeClicks = [];
  const origFetch0 = window.fetch;
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/settings') activeClicks.push(JSON.parse(opts.body || '{}'));
    return origFetch0(u, opts);
  };
  let statusAfterActiveClick = '';
  try {
    document.querySelector('#langChips button[data-lang="en"]').click();
    await new Promise(r => setTimeout(r, 80));
    statusAfterActiveClick = document.getElementById('langStatus')?.textContent || '';
  } finally {
    window.fetch = origFetch0;
  }

  const posted = [];
  const origFetch = window.fetch;
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/settings') {
      const body = JSON.parse(opts.body || '{}');
      posted.push(body);
      const r = await origFetch(u, opts);
      const j = await r.clone().json().catch(() => ({}));
      if (body.language === 'pl' && (!j.lang_status || !/Switching|Przełączam/i.test(j.lang_status))) {
        j.language = 'pl';
        j.lang_status = 'Switching to Polski: downloading the speech model and voice…';
      }
      j.lang_active = 'en';
      return new Response(JSON.stringify(j), { status: r.status, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(u, opts);
  };
  let statusDuring = '', htmlLangDuring = '', plOnDuring = false;
  try {
    document.querySelector('#langChips button[data-lang="pl"]').click();
    await new Promise(r => setTimeout(r, 200));
    statusDuring = document.getElementById('langStatus')?.textContent || '';
    htmlLangDuring = document.documentElement.lang;
    plOnDuring = document.querySelector('#langChips button[data-lang="pl"]')?.classList.contains('on') || false;
  } finally {
    window.fetch = origFetch;
  }

  // Item 2: on Best (medium.en), clicking Polski sends only {language: 'pl'}, and any refusal appears under #langRow (#langErr)
  info.language = 'en'; info.lang_active = 'en'; info.lang_status = ''; info.whisper_model = 'medium.en';
  showInfo(); renderSettings();
  const bestLangPosted = [];
  let langRefusalTxt = '', langRefusalInRow = false;
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/settings') {
      const b = JSON.parse(opts.body || '{}');
      bestLangPosted.push(b);
      return new Response(JSON.stringify({ error: 'medium.en cannot transcribe Polish' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
    }
    if (u === '/api/state') {
      return new Response(JSON.stringify(info), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(u, opts);
  };
  try {
    document.querySelector('#langChips button[data-lang="pl"]').click();
    await new Promise(r => setTimeout(r, 120));
    const le = document.getElementById('langErr');
    langRefusalTxt = le?.textContent || '';
    langRefusalInRow = le?.closest('#langRow') !== null;
  } finally {
    window.fetch = origFetch;
    const le = document.getElementById('langErr'); if (le) le.textContent = '';
  }

  // Item 1 (M2): STT chips map per lang_active (tiny.en->tiny, base.en->base, small.en->small, medium.en->medium for nb/pl; auto stays),
  //              and a refusal on whisper_model shows under #sttErr without ticking 'speech recognition: … (loading…)'.
  info.lang_active = 'en'; info.whisper_model = 'auto'; showInfo(); renderSettings();
  const sttChipsEn = [...document.querySelectorAll('#sttChips button')].map(b => b.dataset.stt);
  const sttSmallEn = sttId('small.en');
  info.lang_active = 'pl'; info.whisper_model = 'medium'; showInfo(); renderSettings();
  const sttChipsPl = [...document.querySelectorAll('#sttChips button')].map(b => b.dataset.stt);
  const sttBestOnPl = document.querySelector('#sttChips button[data-stt="medium"]')?.classList.contains('on') || false;
  const sttSmallPl = sttId('small.en');
  info.lang_active = 'nb'; info.whisper_model = 'base'; showInfo(); renderSettings();
  const sttChipsNb = [...document.querySelectorAll('#sttChips button')].map(b => b.dataset.stt);

  let sttErrTxt = '', sttErrInRow = false, chipTxtOnRefusal = '', chipTxtOnOk = '';
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/settings') {
      return new Response(JSON.stringify({ error: 'tiny.en cannot transcribe Norwegian' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
    }
    if (u === '/api/state') {
      return new Response(JSON.stringify(info), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(u, opts);
  };
  try {
    document.getElementById('chip').textContent = '';
    document.querySelector('#sttChips button[data-stt="tiny"]').click();
    await new Promise(r => setTimeout(r, 120));
    const se = document.getElementById('sttErr');
    sttErrTxt = se?.textContent || '';
    sttErrInRow = se?.parentElement?.querySelector('#sttChips') !== null;
    chipTxtOnRefusal = document.getElementById('chip')?.textContent || '';
  } finally {
    window.fetch = origFetch;
  }
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/settings') {
      const b = JSON.parse(opts.body || '{}');
      return new Response(JSON.stringify({ ...info, ...b }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(u, opts);
  };
  try {
    document.querySelector('#sttChips button[data-stt="tiny"]').click();
    await new Promise(r => setTimeout(r, 120));
    chipTxtOnOk = document.getElementById('chip')?.textContent || '';
  } finally {
    window.fetch = origFetch;
    const se = document.getElementById('sttErr'); if (se) se.textContent = '';
  }

  // Simulate switch completion to pl, check <html lang> and Item 6 (state_info.date_locale + DATE_LOCALES fallback)
  info.language = 'pl';
  info.lang_active = 'pl';
  info.lang_status = '';
  info.date_locale = 'pl-PL';
  showInfo();
  renderSettings();
  const htmlLangPl = document.documentElement.lang;
  const statusAfter = document.getElementById('langStatus')?.textContent || '';
  stageBuild({ t: 'stage', v: 1, kind: 'headlines', title: 'Wiadomości', items: [{ title: 'Test', source: 'PAP', at: Date.now() / 1000 }] });
  const gotPlDate = document.getElementById('stgDt')?.textContent || '';
  const expPlDate = new Date().toLocaleDateString('pl-PL', { weekday: 'short', day: 'numeric', month: 'short' });

  // Custom state_info.date_locale overrides DATE_LOCALES[lang_active], and absent date_locale falls back to DATE_LOCALES
  info.lang_active = 'en';
  info.date_locale = 'de-DE';
  stageBuild({ t: 'stage', v: 1, kind: 'headlines', title: 'News', items: [{ title: 'Test', source: 'DW', at: Date.now() / 1000 }] });
  const gotCustomDate = document.getElementById('stgDt')?.textContent || '';
  const expCustomDate = new Date().toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' });

  delete info.date_locale;
  info.lang_active = 'nb';
  showInfo();
  const htmlLangNb = document.documentElement.lang;
  stageBuild({ t: 'stage', v: 1, kind: 'headlines', title: 'Nyheter', items: [{ title: 'Test', source: 'NRK', at: Date.now() / 1000 }] });
  const gotNbDate = document.getElementById('stgDt')?.textContent || '';
  const expNbDate = new Date().toLocaleDateString('nb-NO', { weekday: 'short', day: 'numeric', month: 'short' });

  // Item 5: With Settings closed, bus event refreshes immediately, and polling runs every 2 s while lang_status is non-empty
  settings(false);
  info.language = 'pl'; info.lang_active = 'en'; info.lang_status = 'Switching to Polski…'; info.date_locale = 'en-GB';
  showInfo();
  stageBuild({ t: 'stage', v: 1, kind: 'headlines', title: 'News', items: [{ title: 'Test', source: 'PAP', at: Date.now() / 1000 }] });
  let statePolls = 0;
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/state') {
      statePolls++;
      return new Response(JSON.stringify({
        ...info,
        language: 'pl',
        lang_active: 'pl',
        lang_status: '',
        date_locale: 'pl-PL',
        lines: { 'page.tidy': 'Dobrze, porządkuję.' }
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(u, opts);
  };
  let pollLangAfter = '', pollSttChipAfter = '', pollDateAfter = '', pollLineAfter = '', pollsAfterSettled = 0, busLangAfter = '';
  try {
    await new Promise(r => setTimeout(r, 2200));
    pollLangAfter = document.documentElement.lang;
    pollSttChipAfter = document.querySelector('#sttChips button')?.dataset.stt || '';
    pollDateAfter = document.getElementById('stgDt')?.textContent || '';
    pollLineAfter = pageLine('page.tidy', 'Okay, tidying up.');
    const p0 = statePolls;
    await new Promise(r => setTimeout(r, 2200));
    pollsAfterSettled = statePolls - p0;

    // Now test bus event refresh while Settings is closed
    info.language = 'nb'; info.lang_active = 'en'; info.lang_status = 'Switching to Norsk…';
    window.fetch = async (u, opts = {}) => {
      if (u === '/api/state') {
        return new Response(JSON.stringify({
          ...info,
          language: 'nb',
          lang_active: 'nb',
          lang_status: '',
          date_locale: 'nb-NO'
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return origFetch(u, opts);
    };
    onEvent({ t: 'lang_status', lang_status: '' });
    await new Promise(r => setTimeout(r, 100));
    busLangAfter = document.documentElement.lang;
  } finally {
    window.fetch = origFetch;
  }
  settings(true, 'voice');

  // Page-spoken lines from state_info.lines, with English fallback when lines are absent
  const spokenFromState = [];
  const spokenFallback = [];
  const origSay = window.say;
  const origFetch2 = window.fetch;
  let curLines = {
    'page.control_back': 'Sterowanie wróciło do Ciebie.',
    'page.live_on': 'Dobrze, patrzę. Powiedz „stop watching”, kiedy skończysz.',
    'page.live_off': 'Dobrze, już nie patrzę.',
    'page.live_wasnt': 'Nie patrzyłem.',
    'page.tidy': 'Dobrze, porządkuję.',
    'page.voice_1': 'cześć! to mój nowy głos.',
    'page.voice_2': 'jak brzmię?',
    'page.voice_3': 'o, ten mi się podoba.'
  };
  window.say = (t, follow) => { spokenFromState.push(t); };
  window.fetch = async (u, opts = {}) => {
    if (u === '/api/mirror/off') return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (u === '/api/compact') return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (u === '/api/state') return new Response(JSON.stringify({ ...info, lines: curLines }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (u === '/api/settings') {
      const b = JSON.parse(opts.body || '{}');
      return new Response(JSON.stringify({ ...info, ...b, lines: curLines }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch2(u, opts);
  };
  try {
    info.lines = curLines;
    await mirRevoke();
    setLive(false);
    toggleLive();
    toggleLive();
    await send('stop watching');
    await send('tidy up');
    document.querySelector('#voiceChips button:not(:disabled)')?.click();
    await new Promise(r => setTimeout(r, 80));

    curLines = {};
    info.lines = curLines;
    window.say = (t, follow) => { spokenFallback.push(t); };
    await mirRevoke();
    setLive(false);
    toggleLive();
    toggleLive();
    await send('stop watching');
    await send('tidy up');
    document.querySelector('#voiceChips button:not(:disabled)')?.click();
    await new Promise(r => setTimeout(r, 80));
  } finally {
    window.say = origSay;
    window.fetch = origFetch2;
  }

  info.language = 'en';
  info.lang_active = 'en';
  info.date_locale = 'en-GB';
  info.whisper_model = 'auto';
  showInfo();
  renderSettings();

  return {
    firstRowId, hintCpu, hintGpu, chipList, initHtmlLang,
    activeClicks, statusAfterActiveClick,
    posted, statusDuring, htmlLangDuring, plOnDuring,
    bestLangPosted, langRefusalTxt, langRefusalInRow,
    sttChipsEn, sttChipsPl, sttChipsNb, sttBestOnPl, sttSmallEn, sttSmallPl,
    sttErrTxt, sttErrInRow, chipTxtOnRefusal, chipTxtOnOk,
    htmlLangPl, htmlLangNb, statusAfter,
    gotPlDate, expPlDate, gotCustomDate, expCustomDate, gotNbDate, expNbDate,
    statePolls, pollLangAfter, pollSttChipAfter, pollDateAfter, pollLineAfter, pollsAfterSettled, busLangAfter,
    spokenFromState, spokenFallback
  };
`);
check(langTest.firstRowId === "langRow", "Language row must be the first .row in #panel-voice", langTest.firstRowId);
check(langTest.hintCpu.includes("≈150 MB") && langTest.hintCpu.includes("base") && !langTest.hintCpu.includes("small"),
  "CPU first-switch hint must not suggest small", langTest.hintCpu);
check(langTest.hintGpu.includes("≈150 MB") && langTest.hintGpu.includes("base") && langTest.hintGpu.includes("≈480 MB") && langTest.hintGpu.includes("small") && /GPU/i.test(langTest.hintGpu),
  "GPU first-switch size/GPU hint missing required details", langTest.hintGpu);
check(langTest.chipList.map(c => `${c.lang}:${c.text}:${c.on}`).join(",") === "en:English:true,nb:Norsk:false,pl:Polski:false",
  "Language chips initial state", JSON.stringify(langTest.chipList));
check(langTest.initHtmlLang === "en", "initial <html lang> should be en", langTest.initHtmlLang);
check(langTest.activeClicks.length === 0 && langTest.statusAfterActiveClick === "",
  "clicking already-active language should do nothing visible", JSON.stringify({ activeClicks: langTest.activeClicks, status: langTest.statusAfterActiveClick }));
check(langTest.posted.some(p => p.language === "pl") && langTest.plOnDuring, "clicking Polski chip did not post language='pl'", JSON.stringify(langTest.posted));
check(/Switching to Polski/i.test(langTest.statusDuring), "status line not shown while switching", langTest.statusDuring);
check(langTest.bestLangPosted.length === 1 && Object.keys(langTest.bestLangPosted[0]).join(",") === "language" && langTest.bestLangPosted[0].language === "pl",
  "switching language on Best must send only {language}", JSON.stringify(langTest.bestLangPosted));
check(langTest.langRefusalTxt === "medium.en cannot transcribe Polish" && langTest.langRefusalInRow,
  "language refusal must appear under #langRow", JSON.stringify({ langRefusalTxt: langTest.langRefusalTxt, langRefusalInRow: langTest.langRefusalInRow }));
check(langTest.sttChipsEn.join(",") === "tiny.en,base.en,auto,medium.en"
  && langTest.sttChipsPl.join(",") === "tiny,base,auto,medium"
  && langTest.sttChipsNb.join(",") === "tiny,base,auto,medium"
  && langTest.sttBestOnPl && langTest.sttSmallEn === "small.en" && langTest.sttSmallPl === "small",
  "STT chips did not map per lang_active", JSON.stringify(langTest));
check(langTest.sttErrTxt === "tiny.en cannot transcribe Norwegian" && langTest.sttErrInRow && !/loading/i.test(langTest.chipTxtOnRefusal) && /speech recognition:.*loading/i.test(langTest.chipTxtOnOk),
  "STT refusal must show under Speech recognition control and not tick loading", JSON.stringify({ sttErrTxt: langTest.sttErrTxt, sttErrInRow: langTest.sttErrInRow, chipTxtOnRefusal: langTest.chipTxtOnRefusal, chipTxtOnOk: langTest.chipTxtOnOk }));
check(langTest.htmlLangDuring === "en" && langTest.htmlLangPl === "pl" && langTest.htmlLangNb === "nb" && langTest.statusAfter === "",
  "<html lang> did not follow lang_active or status did not clear", JSON.stringify(langTest));
check(langTest.gotPlDate === langTest.expPlDate && langTest.gotCustomDate === langTest.expCustomDate && langTest.gotNbDate === langTest.expNbDate,
  "date locale did not use state_info.date_locale with DATE_LOCALES fallback", JSON.stringify({ gotPlDate: langTest.gotPlDate, expPlDate: langTest.expPlDate, gotCustomDate: langTest.gotCustomDate, expCustomDate: langTest.expCustomDate, gotNbDate: langTest.gotNbDate, expNbDate: langTest.expNbDate }));
check(langTest.statePolls >= 1 && langTest.pollLangAfter === "pl" && langTest.pollSttChipAfter === "tiny" && langTest.pollDateAfter === langTest.expPlDate && langTest.pollLineAfter === "Dobrze, porządkuję." && langTest.pollsAfterSettled === 0 && langTest.busLangAfter === "nb",
  "background switch with Settings closed did not refresh chips, date, and lines via 2 s poll or bus event", JSON.stringify({ statePolls: langTest.statePolls, pollLangAfter: langTest.pollLangAfter, pollSttChipAfter: langTest.pollSttChipAfter, pollDateAfter: langTest.pollDateAfter, pollLineAfter: langTest.pollLineAfter, pollsAfterSettled: langTest.pollsAfterSettled, busLangAfter: langTest.busLangAfter }));
check(langTest.spokenFromState[0] === "Sterowanie wróciło do Ciebie."
  && langTest.spokenFromState[1] === "Dobrze, patrzę. Powiedz „stop watching”, kiedy skończysz."
  && langTest.spokenFromState[2] === "Dobrze, już nie patrzę."
  && langTest.spokenFromState[3] === "Nie patrzyłem."
  && langTest.spokenFromState[4] === "Dobrze, porządkuję."
  && ["cześć! to mój nowy głos.", "jak brzmię?", "o, ten mi się podoba."].includes(langTest.spokenFromState[5]),
  "page-spoken lines were not taken from state_info.lines", JSON.stringify(langTest.spokenFromState));
check(langTest.spokenFallback[0] === "Control is back with you."
  && langTest.spokenFallback[1] === "Okay, I'm watching. Say “stop watching” when you're done."
  && langTest.spokenFallback[2] === "Okay, I stopped looking."
  && langTest.spokenFallback[3] === "I wasn't looking."
  && langTest.spokenFallback[4] === "Okay, tidying up."
  && ["hi! this is my new voice.", "how do i sound?", "ooh, i like this one."].includes(langTest.spokenFallback[5]),
  "page-spoken lines did not fall back to English", JSON.stringify(langTest.spokenFallback));

// 9b. A voice for each character: the Look select, its notes, and the Voice tab's line while it is active.
const cv = await ev(`
  const W = ms => new Promise(r => setTimeout(r, ms));
  await setSetting({ tts: 'auto', voice: 'guy', voice_by_character: {} }); await W(300);
  settings(true, 'look'); await W(300);
  const sel = () => document.getElementById('charVoice');
  const opts = [...sel().options].map(o => o.value);
  const ids = (info.voices || []).map(v => v.id);
  const label0 = document.getElementById('charVoiceLabel').textContent;
  const plain = { noteEmpty: document.getElementById('charVoiceNote').textContent === '' };
  const realVoices = info.voices;
  info.voices = realVoices.map(v => ({ ...v, ready: false }));   // (a preset not downloaded yet stays selectable: only Robot disables)
  renderSettings();
  const disabled = [...sel().options].filter(o => o.disabled).map(o => o.value);
  info.voices = realVoices; renderSettings();
  const pin = info.voice_pinned; info.voice_pinned = true; renderSettings();
  const pinNote = document.getElementById('charVoiceNote').textContent;
  info.voice_pinned = pin; const tc = info.tts_choice; info.tts_choice = 'elevenlabs'; renderSettings();
  const cloudNote = document.getElementById('charVoiceNote').textContent;
  info.tts_choice = tc; renderSettings();
  const clearedNote = document.getElementById('charVoiceNote').textContent;
  const said = []; const origSay = window.say; window.say = t => { said.push(t); };
  const selNode = sel();
  sel().value = 'deep'; sel().dispatchEvent(new Event('change', { bubbles: true })); await W(500);
  const map = info.voice_by_character, speaking = info.voice_speaking, voice = info.voice, sampled1 = said.length;
  const optNode = sel().options[1]; renderSettings(); const kept = sel() === selNode && sel().options[1] === optNode;
  settings(true, 'voice'); await W(300);
  const other = document.getElementById('voiceOther'), tap = document.getElementById('voiceTap');
  const shown = { other: !other.hidden, txt: other.textContent, tapHidden: tap.hidden };
  const pin0 = info.voice_pinned, tc0 = info.tts_choice;
  info.voice_pinned = true; const pinLine = otherVoiceLine(); info.voice_pinned = pin0;
  info.tts_choice = 'elevenlabs'; const cloudLine = otherVoiceLine(); info.tts_choice = tc0;
  said.length = 0;
  document.querySelector('#voiceChips button[data-v="girl"]')?.click(); await W(500);
  const afterChip = { voice: info.voice, said: said.length, other: !document.getElementById('voiceOther').hidden };
  const ticks = []; const origTick = window.tick; window.tick = t => { ticks.push(t); };
  await slash('/voice guy'); await W(500);
  window.tick = origTick;
  settings(true, 'look'); await W(300);
  sel().value = ''; sel().dispatchEvent(new Event('change', { bubbles: true })); await W(500);
  settings(true, 'voice'); await W(300);
  said.length = 0;
  const back = { other: !document.getElementById('voiceOther').hidden, tap: !document.getElementById('voiceTap').hidden };
  document.querySelector('#voiceChips button[data-v="guy"]').click(); await W(500);
  back.said = said.length;
  window.say = origSay;
  return { pinLine, cloudLine, opts, ids, label0, plain, disabled, pinNote, cloudNote, clearedNote, map, speaking, voice, sampled1, kept, shown, afterChip, ticks, back };
`);
check(cv.opts[0] === "" && cv.opts.slice(1).join() === cv.ids.join() && cv.label0 === "Voice for the Snowflake", "character voice select options or label", JSON.stringify(cv));
check(cv.disabled.join() === "robot", "only an unready Robot may be disabled", JSON.stringify(cv.disabled));
check(cv.pinNote === "A pinned voice is in charge, except for Robot." && /^The cloud voice comes first/.test(cv.cloudNote) && cv.clearedNote === "" && cv.plain.noteEmpty, "character voice note", JSON.stringify([cv.pinNote, cv.cloudNote, cv.clearedNote]));
check(cv.map && cv.map.snowflake === "deep" && cv.speaking === "deep" && cv.voice === "guy" && cv.sampled1 >= 1 && cv.kept, "choosing a character voice did not save or sample", JSON.stringify(cv));
check(cv.pinLine === "" && cv.cloudLine === "", "the line must not name a voice while a pin or the cloud speaks", JSON.stringify([cv.pinLine, cv.cloudLine]));
check(cv.shown.other && /speaks as/.test(cv.shown.txt) && cv.shown.tapHidden, "voice tab did not show the character's voice line", JSON.stringify(cv.shown));
check(cv.afterChip.voice === "girl" && cv.afterChip.said === 0 && cv.afterChip.other, "chip tap while a character voice is active must save and stay silent", JSON.stringify(cv.afterChip));
check(cv.ticks.some(x => /speaks as/.test(x)), "/voice did not mention the character's voice", JSON.stringify(cv.ticks));
check(!cv.back.other && cv.back.tap && cv.back.said >= 1, "back on My voice the line must hide and a tap must sample", JSON.stringify(cv.back));

// 10. Zero off-origin requests.
check(offOrigin.length === 0, "off-origin requests made", offOrigin.join(", "));

ws.close();
if (fails.length) process.exit(1);
console.log("OK   settings → voice, preview, cloud badge, reply id and tts_gen cut verified");
