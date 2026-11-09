// Characters (#178): the registry contract in the page (CHARACTERS, BODY, setCharacter), and what each character must hold to.
//   node tests/character_fit.mjs <cdp-port> <page-url> char <id>          one character's cases (exit 77 = id not in CHARACTERS)
//   node tests/character_fit.mjs <cdp-port> <page-url> pixels <base-url>  Snowflake here vs the same page on origin/main
// Needs a headless Chromium started with --disable-gpu (never a desktop browser: an animated page on a forced-GPU
// Chrome hung an AMD GPU twice, #138). Exit 0 = pass.
const [port, url, mode, arg] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));

class Tab {
  static async open() {
    const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
    const tab = new Tab(t); await new Promise(r => tab.ws.addEventListener("open", r, { once: true }));
    await tab.send("Page.enable"); await tab.send("Emulation.setDeviceMetricsOverride", { width: 340, height: 460, deviceScaleFactor: 1, mobile: false });
    return tab;
  }
  constructor(t) {
    this.t = t; this.ws = new WebSocket(t.webSocketDebuggerUrl); this.id = 0; this.pend = new Map();
    this.ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && this.pend.has(m.id)) { this.pend.get(m.id)(m); this.pend.delete(m.id); } });
  }
  send(method, params = {}) { return new Promise(r => { const i = ++this.id; this.pend.set(i, r); this.ws.send(JSON.stringify({ id: i, method, params })); }); }
  async ev(js) { const r = await this.send("Runtime.evaluate", { expression: `(async()=>{${js}})()`, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; }
  async go(u, ms = 4500) { await this.send("Page.navigate", { url: u }); await sleep(ms); }
  close() { return this.send("Target.closeTarget", { targetId: this.t.id }).catch(() => {}); }
}
const fails = [], check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? "  " + extra : ""}`); if (!ok) fails.push(name); };
const done = async (...tabs) => { for (const t of tabs) await t.close(); console.log(fails.length ? `\n${fails.length} failed: ${fails.join(", ")}` : "\nall ok"); process.exit(fails.length ? 1 : 0); };

// ---------- the Snowflake pixel comparison: the same state drawn by this page and by origin/main ----------
if (mode === "pixels") {
  // a fixed clock and a fixed dice; the rAF loop is ours (frame(ts) is called by hand), animations and transitions are off
  const PRE = `(()=>{ let T=1000; performance.now=()=>T; Date.now=()=>1.7e12+T; Math.random=()=>.5;
    window.__setT=v=>{ T=v; }; window.__raf=[]; window.requestAnimationFrame=cb=>{ window.__raf.push(cb); return window.__raf.length; };
    document.addEventListener('DOMContentLoaded',()=>{ const s=document.createElement('style');
      s.textContent='*,*::before,*::after{transition:none!important;animation:none!important}#fx,#fxBack,#flash,#orbBack,#orbFront,#paint,#micBars{display:none!important}'; document.head.append(s); }); })();`;
  const STATES = {
    idle: "transientUntil=0;",
    happy: "poke('happy',1e12);",
    surprised: "poke('surprised',1e12);",
    bar: "transientUntil=0; document.body.classList.add('bar','bar-done','e-top');",
    music: "transientUntil=0; info.look_music=true; info.look_beat=false; SIT.music=true; sitOn.music=true;",
  };
  const shoot = async (u) => {
    const tab = await Tab.open();
    await tab.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    await tab.send("Animation.enable"); await tab.send("Animation.setPlaybackRate", { playbackRate: 0 });
    await tab.send("Page.addScriptToEvaluateOnNewDocument", { source: PRE });
    await tab.go(u, 3500);
    const out = {};
    for (const [name, js] of Object.entries(STATES)) {
      await tab.ev(`document.body.classList.remove('bar','bar-done','e-top'); ORBS.length=0;
        for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; SIT.weather=null; SIT.day=true;
        AMB={sys:[],cal:null,weather:null}; attnPend=null; AM=null; propOn=null; FID=null; lowFx=true;
        applyLook({body:'#1b2a4a',pupL:'#3e5993',pupR:'#3e5993',whiteL:'#ffffff',whiteR:'#ffffff',skin:'none',skinColor:'',link:true,random:false,follow_theme:false});
        ${js}
        // timers parked far in the future, the eyes open; then settle the springs on a fixed 16 ms clock
        nextBlink=nextFidAt=saccadeAt=idleSwapAt=1e15; openAt=0; lastMouse=-1e9; lastActive=1000; lastTs=0;
        let ts=1000; for(let i=0;i<700;i++){ ts+=16; __setT(ts); nextBlink=nextFidAt=saccadeAt=idleSwapAt=1e15; frame(ts); }
        __setT(20000); frame(20000); __raf.length=0; return 1`);
      await sleep(250);
      out[name] = { png: (await tab.send("Page.captureScreenshot", { format: "png" })).result.data,
        opacity: name === "music" ? await tab.ev("return +SIT_P.hf.getAttribute('opacity')") : null };
    }
    await tab.close(); return out;
  };
  const mine = await shoot(url), base = await shoot(arg);
  const cmp = await Tab.open();
  for (const name of Object.keys(STATES)) {
    const r = await cmp.ev(`const px=async b=>{ const bm=await createImageBitmap(await (await fetch('data:image/png;base64,'+b)).blob()); const c=new OffscreenCanvas(bm.width,bm.height).getContext('2d'); c.drawImage(bm,0,0); return c.getImageData(0,0,bm.width,bm.height); };
      const a=await px(${JSON.stringify(mine[name].png)}), b=await px(${JSON.stringify(base[name].png)}); if(a.width!==b.width||a.height!==b.height) return [-1,0,0];
      let off=0, worst=0; for(let i=0;i<a.data.length;i+=4){ const d=Math.max(Math.abs(a.data[i]-b.data[i]),Math.abs(a.data[i+1]-b.data[i+1]),Math.abs(a.data[i+2]-b.data[i+2])); if(d>${name === "music" ? 0 : 8}) off++; if(d>worst) worst=d; }
      return [off,a.width*a.height,worst];`);
    check(r[0] >= 0 && (name === "music" ? mine[name].opacity === 1 && base[name].opacity === 1 && r[0] === 0 : r[0] <= r[1] * 0.0005),
      `snowflake pixels match origin/main: ${name}`, `${r[0]} of ${r[1]} px off by >${name === "music" ? 0 : 8} (worst ${r[2]})${name === "music" ? `, opacity ${mine[name].opacity}/${base[name].opacity}` : ""}`);
  }
  await done(cmp);
}

// ---------- #213: a plugin character's label, clip and removal (the test server serves plug:fixture) ----------
if (mode === "plugpage") {
  const tab = await Tab.open();
  await tab.go(url);
  const r = await tab.ev(`const bad=[], c=CHARACTERS['plug:fixture']; if(!c) return ['no plug:fixture'];
    applyLook({...LOOK, character:'plug:fixture'}); await new Promise(r=>setTimeout(r,400));
    if(BODY!==c) bad.push('BODY'); if(document.querySelector('#body>path.ball').getAttribute('fill')!=='#778899') bad.push('flat fill');
    if(document.getElementById('rim').getAttribute('fill')!=='none') bad.push('rim filled');
    const clipped=(inner,where)=>{ if(!inner) return bad.push('no nested svg '+where);   // dots past each edge of x ±96, y -120…+100
      for(const [cx,cy] of [[-130,0],[130,0],[0,-150],[0,130]]){ const d=sv('circle',{cx,cy,r:20,fill:'#ff00ff'},inner), r=d.getBoundingClientRect();
        if(r.width&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===d) bad.push(where+' dot '+cx+','+cy+' not clipped'); d.remove(); } };
    clipped(document.querySelector('#body>.nix>svg'),'stage');
    renderSettings();
    const b=document.querySelector('#characterGrid [data-character="plug:fixture"]');
    if(!b) bad.push('not in the grid'); else { settings(true,'look'); await new Promise(r=>setTimeout(r,300));
      const g=document.querySelector('#characterGrid [data-character="plug:fixture"]'); g.scrollIntoView({block:'center'}); await new Promise(r=>setTimeout(r,100));
      if(!g.getBoundingClientRect().width) bad.push('grid not shown'); clipped(g.querySelector('g[data-part="body"]>svg'),'grid'); if(!b.textContent.includes('<b>x</b>')) bad.push('label not text'); if(b.querySelector('b')) bad.push('label is markup'); }
    info.look={...(info.look||{}),character:'plug:fixture',random:true}; syncLook(true);   // random colours: a changed plugin is still redrawn
    info.plugin_characters=info.plugin_characters.map(p=>({...p,fill:'#112233'})); syncLook();
    if(BODY!==CHARACTERS['plug:fixture']||document.querySelector('#body>path.ball').getAttribute('fill')!=='#112233') bad.push('random mode kept the old art');
    info.plugin_characters=[]; syncLook(); renderSettings();
    if(Object.keys(CHARACTERS).some(k=>k.startsWith('plug:'))) bad.push('plug: left in CHARACTERS');
    if(document.querySelector('#characterGrid [data-character^="plug:"]')) bad.push('plug: left in the grid');
    if(BODY===c) bad.push('still drawn');
    return bad;`);
  check(r.length === 0, "plug:fixture: label as text, art clipped, gone after the plugin goes", r.join(", "));
  await done(tab);
}

// ---------- the per-character cases ----------
if (mode !== "char") { console.log("usage: character_fit.mjs <cdp> <url> char <id> | pixels <base-url>"); process.exit(2); }
const ID = arg;
const tab = await Tab.open();
const ev = js => tab.ev(js);
await tab.go(url);
if (!(await ev(`return typeof CHARACTERS!=='undefined' && !!CHARACTERS[${JSON.stringify(ID)}]`))) {
  console.log(`no character "${ID}" in CHARACTERS`); await tab.close(); process.exit(77);
}
const prep = async () => { await ev("setInterval(()=>{ nextFidAt=1e15; },50); window.__hold=null; await post('/api/settings',{idle_mode:'off'}).then(r=>r.json()).then(j=>{info=j;}); if(window.setIdle) setIdle('full'); return 1"); };
await prep();
await ev(`window.__id=${JSON.stringify(ID)}; applyLook({...LOOK, character:__id}); return 1`);

// helpers in the page: boxes in #body's own coordinates (the squash, sway and bounce cancel out)
await ev(`window.bodyBox=el=>{ const b=el.getBBox(), m=document.getElementById('body').getScreenCTM().inverse().multiply(el.getScreenCTM());
    const p=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>{ const q=new DOMPoint(x,y).matrixTransform(m); return [q.x,q.y]; });
    return [Math.min(...p.map(q=>q[0])),Math.min(...p.map(q=>q[1])),Math.max(...p.map(q=>q[0])),Math.max(...p.map(q=>q[1]))]; };
  window.uni=(a,b)=>a?[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])]:b;
  window.hit=(a,b)=>a[0]<b[2]-.01&&b[0]<a[2]-.01&&a[1]<b[3]-.01&&b[1]<a[3]-.01; return 1`);

// 1. the registry entry has the whole contract
{
  const r = await ev(`const c=CHARACTERS[__id], A=['head','face','neck','base','left','right'], bad=[];
    if(typeof c.label!=='string'||!c.label) bad.push('label'); if(typeof c.ball!=='string'||!c.ball) bad.push('ball');
    if(typeof c.back!=='string') bad.push('back'); if(typeof c.front!=='string') bad.push('front');
    if(__id.startsWith('plug:')&&!(Array.isArray(c.nodes?.back)&&Array.isArray(c.nodes?.front)&&c.nodes.back.length>1)) bad.push('nodes'); if(typeof c.gloss!=='boolean') bad.push('gloss');
    if(!Array.isArray(c.faceBox)||c.faceBox.length!==4||!c.faceBox.every(Number.isFinite)) bad.push('faceBox');
    if(!Number.isFinite(c.cupX)) bad.push('cupX'); if(typeof c.band!=='string'||!c.band) bad.push('band');
    if(!A.every(k=>Array.isArray(c.anchors?.[k])&&c.anchors[k].length===2&&c.anchors[k].every(Number.isFinite))) bad.push('anchors');
    if(__id==='snowflake'&&(!A.every(k=>c.anchors[k][0]===0&&c.anchors[k][1]===0)||c.pivot!==76||c.shadow!==62||!c.gloss||c.cupX!==88||c.band!=='M-84 -20C-100 -144 100 -144 84 -20')) bad.push('snowflake numbers');
    if(c.anchors?.face&&(c.anchors.face[0]||c.anchors.face[1])) bad.push('face anchor is not [0,0]');
    if(!Number.isFinite(c.pivot)) bad.push('pivot'); if(!Number.isFinite(c.shadow)) bad.push('shadow'); if(!(c.fits instanceof Set)) bad.push('fits');
    if(!(c.touch===null||typeof c.touch==='string')) bad.push('touch');
    setCharacter(__id==='robot'?'devil':'robot'); setCharacter(__id); if(BODY!==c) bad.push('BODY');
    if(![...SIT_P.bd.querySelectorAll('path')].every(p=>p.getAttribute('d')===c.band)) bad.push('band d');
    if(document.querySelector('#body>path.ball').getAttribute('d')!==c.ball||document.getElementById('rim').getAttribute('d')!==c.ball) bad.push('d');
    if(!document.querySelector('#body>.bfront')) bad.push('no .bfront');
    if([...document.querySelectorAll('#body>ellipse')].some(e=>(e.getAttribute('display')==='none')===c.gloss)) bad.push('gloss display');
    return bad;`);
  check(r.length === 0, `${ID}: registry entry and setCharacter`, r.join(", "));
}

// 2. both eyes stay inside faceBox and clear of every .avoid, in each mood, at the full talk swell and at the gaze extremes
{
  const states = [["idle", "transientUntil=0; gazeHook=null;"], ["happy", "poke('happy',1e9); gazeHook=null;"], ["surprised", "poke('surprised',1e9); gazeHook=null;"],
    ["talk swell", "window.__rms=window.__rms||rms; rms=()=>1; poke('talking',1e9); gazeHook=null;"],
    ...[["left", -14, 0], ["right", 14, 0], ["up", 0, -10], ["down", 0, 10]].map(([n, x, y]) => [`gaze ${n}`, `transientUntil=0; window.gazeHook=()=>[${x},${y}];`])];
  const r = await ev(`const c=CHARACTERS[__id], [fx,fy,fw,fh]=c.faceBox, out=[]; setCharacter(__id);
    const avoid=[...document.querySelectorAll('#body .avoid')].map(e=>[e,bodyBox(e)]);
    for(const [n,js] of ${JSON.stringify(states)}){ new Function(js)(); if(js.includes('rms=')) rms=()=>1; else if(window.__rms) rms=window.__rms;
      await new Promise(r=>setTimeout(r,1400)); let u=null;
      const hitS=new Map();
      for(let i=0;i<10;i++){ for(const e of [E.pL,E.pR]){ const b=bodyBox(e); if(b[2]-b[0]<=1) continue; u=uni(u,b);
          // the eye's real shape against each .avoid's real shape (a box round a leaning oval has empty corners)
          const l=e.getBBox(); for(const [a,ab] of avoid){ if(!hit(b,ab)) continue; const m=a.getScreenCTM().inverse().multiply(e.getScreenCTM());
            for(let x=l.x;x<=l.x+l.width&&!hitS.has(a);x+=1) for(let y=l.y;y<=l.y+l.height;y+=1){ const p=new DOMPoint(x,y); if(!e.isPointInFill(p)) continue; const q=p.matrixTransform(m);
              if(a.isPointInFill(q)||a.isPointInStroke(q)){ hitS.set(a,[x,y]); break; } } } }
        await new Promise(r=>setTimeout(r,60)); }
      const inside=u&&u[0]>=fx-.5&&u[1]>=fy-.5&&u[2]<=fx+fw+.5&&u[3]<=fy+fh+.5, hs=[...hitS.keys()].map(e=>[e,bodyBox(e)]), hits=hs.length;
      out.push([n,!!u,inside,hits,u&&u.map(v=>+v.toFixed(1)).join(',')+hs.map(([e,b])=>' | '+e.tagName+'.'+(e.getAttribute('class')||'')+' '+b.map(v=>v.toFixed(1)).join(',')).join('')]); }
    if(window.__rms) rms=window.__rms; gazeHook=null; transientUntil=0; return [out,avoid.length];`);
  for (const [n, seen, inside, hits, box] of r[0]) check(seen && inside && hits === 0, `${ID}: eyes inside faceBox, clear of .avoid (${n})`, `eyes ${box}${hits ? `, ${hits} .avoid hit` : ""}`);
}

if (process.env.CHARACTER_ONLY === "face") await done(tab);   // (a quick run of just the face box)
// Cups may cover the case, ears and wings, but their ink must clear the face and marks.
if (ID !== "snowflake") {
  const r = await ev(`setCharacter(__id); idleSwapAt=nextFidAt=1e15; const on=()=>{ SIT.music=true; info.look_music=info.look_beat=true; }; on(); const hold=setInterval(on,60);   // (a refresh replaces info)
    await new Promise(r=>setTimeout(r,4800)); const out=[], [fx,fy,fw,fh]=BODY.faceBox;
    for(const gaze of [0,-14,14]) for(const lift of [0,1]){
      gazeHook=()=>[gaze,0]; if(lift) poke('talking',1e9); else transientUntil=0;
      await new Promise(r=>setTimeout(r,1400));
      for(const sway of [0,-28,28]) for(const bt of [0,1]){
        on(); const ts=lastTs+16; beat=bt?1+.016*8:0; beatAt=bt?ts:-1e9;
        G.sitLift.x=lift; G.sitLift.v=0; G.sitW.x=sway/.9784; G.sitW.v=0;
        frame(ts);
        const left=SIT_P.cL.getAttribute('transform'), head=SIT_P.hf.getAttribute('transform');
        if(lift&&bt&&(!left.includes('rotate(-20.00)')||!left.includes('scale(1.070)'))) out.push([gaze,lift,sway,bt,'left cup '+left]);
        if(Math.abs(sway)===28&&!head.includes('rotate('+Math.sign(sway)*7+'.00)')) out.push([gaze,lift,sway,bt,'head sway '+head]);
        const marks=[...document.querySelectorAll('#body .avoid')].map(bodyBox);
        for(const [side,cu] of [['left',SIT_P.cL],['right',SIT_P.cR]]){
          const m=document.getElementById('body').getScreenCTM().inverse().multiply(cu.firstChild.getScreenCTM());
          for(let i=0;i<48;i++){
            const a=i*2*Math.PI/48, p=new DOMPoint(18.5*Math.cos(a),29.5*Math.sin(a)).matrixTransform(m);
            if((p.x>fx&&p.x<fx+fw&&p.y>fy&&p.y<fy+fh)||marks.some(b=>p.x>b[0]&&p.x<b[2]&&p.y>b[1]&&p.y<b[3])) out.push([gaze,lift,sway,bt,side+' cup '+p.x.toFixed(2)+','+p.y.toFixed(2)]);
          }
        }
      }
    }
    clearInterval(hold); gazeHook=null; transientUntil=0; SIT.music=false; info.look_music=false; return out;`);
  check(r.length === 0, `${ID}: headphone cups clear face and marks`, r.slice(0,8).map(x=>x.join('/')).join('; '));
}

// 3. the whole body fits his window area
{
  const b = await ev(`setCharacter(__id); let u=null; for(const e of document.querySelectorAll('#body>path.ball,#body>.nix,#body>.bfront')){ try{ const x=bodyBox(e); if(x[2]>x[0]) u=uni(u,x); }catch(e){} } return u;`);
  // (decision 5 is the limit for new art: Snowflake's lambdas reach ±149 by design, and its surface case covers the window)
  check(ID === "snowflake" ? !!b : b && b[0] >= -96 && b[2] <= 96 && b[1] >= -120 && b[3] <= 100, `${ID}: body within x ±96, y -120…+100`, b && b.map(v => v.toFixed(0)).join(","));
}

// 4. switching while frost and the glint show: Snowflake only
{
  const r = await ev(`const fr=document.getElementById('frost'), nx=()=>document.querySelector('#body>.nix'), out={};
    setCharacter('snowflake'); onEvent({t:'ambient',sys:[],cal:null,weather:'cold',glint:true}); await new Promise(r=>setTimeout(r,100));
    out.on=[fr.getAttribute('display')!=='none', nx().classList.contains('glint')];
    setCharacter(__id); await new Promise(r=>setTimeout(r,100));
    out.sw=[fr.getAttribute('display')!=='none', nx().classList.contains('glint')];
    onEvent({t:'ambient',sys:[],cal:null,weather:'cold',glint:true}); await new Promise(r=>setTimeout(r,100));
    out.again=[fr.getAttribute('display')!=='none', nx().classList.contains('glint')];
    setCharacter('snowflake'); await new Promise(r=>setTimeout(r,100)); out.back=[fr.getAttribute('display')!=='none'];
    onEvent({t:'ambient',sys:[],cal:null,weather:'cold',glint:true}); await new Promise(r=>setTimeout(r,100)); out.back.push(nx().classList.contains('glint'));
    AMB={sys:[],cal:null,weather:null}; renderCue(); setCharacter(__id); return out;`);
  check(r.on.join() === "true,true", `${ID}: frost and glint show on Snowflake`, r.on.join());
  if (ID !== "snowflake") {
    check(r.sw.join() === "false,false" && r.again.join() === "false,false", `${ID}: switching to it removes frost and glint, and they stay off`, `${r.sw} / ${r.again}`);
    check(r.back.join() === "true,true", `${ID}: both come back on switching to Snowflake`, r.back.join());
  }
}

// 5. a saved character and its anchors survive a reload and a colour change (applyLook)
{
  const row = await ev(`await setLook({character:'snowflake'}); settings(true,'look'); await new Promise(r=>setTimeout(r,200)); const grid=()=>[...document.querySelectorAll('#characterGrid button')], pick=grid().find(b=>b.dataset.character===__id); pick.scrollIntoView({block:'center'}); await new Promise(r=>setTimeout(r,100)); const r=pick.getBoundingClientRect();
    const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
    const drawn=grid().filter(b=>b.querySelector('svg path[data-part="body"]')?.getAttribute('d')===CHARACTERS[b.dataset.character].ball).length;
    const reached=!!hit&&pick.contains(hit); pick.focus(); pick.click(); for(let i=0;i<20;i++){ await new Promise(r=>setTimeout(r,100)); await refresh(); if(info.look?.character===__id) break; }
    const now=grid().find(b=>b.dataset.character===__id);
    return {count:grid().length, total:Object.keys(CHARACTERS).length, drawn, reached, live:BODY===CHARACTERS[__id], saved:(await (await fetch('/api/state',{headers:hdr()})).json()).look?.character, pressed:now?.getAttribute('aria-pressed'), focused:document.activeElement===now};`);
  check(row.count===row.total && row.total>=4 && row.drawn===row.total && row.reached && row.live && row.saved===ID && row.pressed==="true" && row.focused, `${ID}: Character row previews, picks, saves and keeps focus`, JSON.stringify(row));
  await ev(`settings(false); return 1`);
  const wx = await ev(`await new Promise(r=>setTimeout(r,200)); return [document.querySelector('#wx').getAttribute('transform'), Math.max(CHARACTERS[__id].anchors.head[1],-3)];`);
  check(wx[0].endsWith(` ${wx[1]})`), `${ID}: the weather stays at his head, frame after frame`, String(wx));
  const anc = `const c=CHARACTERS[__id], w=[...document.querySelectorAll('.anc')], bad=[]; if(BODY!==c) bad.push('BODY'); if(document.querySelector('#body>path.ball').getAttribute('d')!==c.ball) bad.push('d');
    if(!w.length) bad.push('no .anc wrappers');
    for(const e of w){ const a=e.dataset.a, want=c.anchors[a]; if(!want){ bad.push('unknown anchor '+a); continue; }
      const m=(e.getAttribute('transform')||'').match(/-?[\\d.]+(?:e-?\\d+)?/g)||[0,0]; if(Math.abs(m[0]-want[0])>.01||Math.abs((m[1]||0)-want[1])>.01) bad.push(a+' '+m.join(' ')); }
    return bad;`;
  await ev(`await post('/api/settings',{look:{character:__id}}); return 1`);
  await tab.go(url); await prep();
  await ev(`window.__id=${JSON.stringify(ID)}; applyLook({...LOOK, skin:'halo'}); return 1`);
  check((await ev(`${anc}`)).length === 0, `${ID}: saved character and its anchors kept after a reload`, (await ev(anc)).join(", "));
  await ev(`applyLook({...LOOK, body:'#aa3322', skin:'crown'}); return 1`);
  const after = await ev(anc);
  check(after.length === 0, `${ID}: character and anchors kept after a colour change`, after.join(", "));
  await ev(`applyLook({...LOOK, skin:'none'}); return 1`);
}

// A saved skin stays saved when this body cannot wear it, and returns on Snowflake.
if (ID === "snowflake" || ID === "robot") {
  const r = await ev(`settings(true,'look'); const tiles=()=>[...document.querySelectorAll('#skinGrid button')], crown=()=>document.querySelector('#accFront .anc[data-fit="crown"]'); const out={};
    await setLook({character:'snowflake',skin:'none'}); out.snow=tiles().map(b=>b.dataset.skin);
    if(__id==='robot'){
      await setLook({character:'robot',skin:'none'}); out.robot=tiles().map(b=>b.dataset.skin);
      await setLook({skin:'crown'}); sitOn.night=sitOn.party=sitOn.cold2=false; out.hidden=[info.look.skin,tiles().find(b=>b.dataset.skin==='none')?.classList.contains('on'),
        !!document.querySelector('#partChips [data-part="skin"]'),wxHat(),crown()?.style.display];
      await setLook({skin:'bow'}); await slash('/skin crown'); out.slash=[info.look.skin,chip.textContent,chip.classList.contains('bad')];
      await setLook({skin:'crown'}); await setLook({character:'snowflake'});
      out.restored=[crown()?.style.display==='',
        tiles().find(b=>b.dataset.skin==='crown')?.classList.contains('on')];
    }
    await setLook({character:__id,skin:'none'}); settings(false); return out;`);
  if (ID === "snowflake") check(["none","halo","crown","sprout","bow"].every(k=>r.snow.includes(k)), `${ID}: all five skin tiles show`, r.snow.join());
  else {
    check(!r.robot.includes("crown") && !r.robot.includes("sprout"), `${ID}: crown and sprout tiles hidden`, r.robot.join());
    check(r.hidden.join() === "crown,true,false,false,none", `${ID}: saved crown is unworn`, r.hidden.join());
    check(r.slash.join() === "bow,crown doesn't fit Robot,true", `${ID}: /skin crown leaves bow saved`, r.slash.join());
    check(r.restored.join() === "true,true", `${ID}: saved crown returns on Snowflake`, r.restored.join());
  }
}

// 6. the bar state: every .ball child of #body is invisible
{
  const r = await ev(`setCharacter(__id); document.body.classList.add('bar','bar-done','e-top'); await new Promise(r=>setTimeout(r,1600));
    const o=[...document.querySelectorAll('#body>.ball,#body>ellipse')].map(e=>getComputedStyle(e).opacity); document.body.classList.remove('bar','bar-done','e-top'); return o;`);
  check(r.length >= 4 && r.every(v => v === "0"), `${ID}: bar state, every .ball child has opacity 0`, r.join());
}

// 7. the touch: it runs, only transform and opacity, paused under body.still, none under reduced motion; still follows the clock
{
  const touch = await ev(`return CHARACTERS[__id].touch`);
  if (touch) {
    const q = `const els=[...document.querySelectorAll('#body .${touch}')]; const st=e=>getComputedStyle(e);`;
    const r = await ev(`${q} document.body.classList.remove('still'); await new Promise(r=>setTimeout(r,200));
      const run=els.map(e=>[st(e).animationName,st(e).animationPlayState]); document.body.classList.add('still'); await new Promise(r=>setTimeout(r,200));
      const paused=els.map(e=>st(e).animationPlayState); document.body.classList.remove('still');
      const props=new Set(); for(const s of document.styleSheets) for(const rule of s.cssRules) if(rule.type===CSSRule.KEYFRAMES_RULE&&els.some(e=>st(e).animationName===rule.name)) for(const k of rule.cssRules) for(const p of k.style) props.add(p);
      return {n:els.length,run,paused,props:[...props]};`);
    check(r.n > 0 && r.run.every(([n, p]) => n !== "none" && p === "running"), `${ID}: touch .${touch} runs`, JSON.stringify(r.run));
    check(r.paused.every(p => p === "paused"), `${ID}: touch paused under body.still`, r.paused.join());
    check(r.props.length > 0 && r.props.every(p => p === "transform" || p === "opacity"), `${ID}: touch animates transform and opacity only`, r.props.join());
    await tab.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] }); await sleep(300);
    const rm = await ev(`${q} return els.map(e=>st(e).animationName)`);
    await tab.send("Emulation.setEmulatedMedia", { features: [] });
    check(rm.length > 0 && rm.every(n => n === "none"), `${ID}: no touch animation under reduced motion`, rm.join());
  } else check(await ev(`return document.querySelectorAll('#body [class*=tCursor],#body [class*=tAntenna],#body [class*=tTail]').length===0`), `${ID}: no touch (null) draws none`);
  // body.still: not at startup, not 1 s after wake(), set after 60 s of nobody there (the clock faked through performance.now)
  await tab.go(url); await prep();
  const s0 = await ev(`return document.body.classList.contains('still')`);
  await ev(`wake(); lastUser=performance.now(); return 1`); await sleep(1100);
  const s1 = await ev(`return document.body.classList.contains('still')`);
  const s2 = await ev(`const o=performance.now.bind(performance); performance.now=()=>o()+61000; await new Promise(r=>setTimeout(r,1200)); const v=document.body.classList.contains('still'); performance.now=o; return v;`);
  check(s0 === false && s1 === false && s2 === true, `${ID}: body.still not at startup / 1 s after wake(), set after 60 s idle`, `${s0} ${s1} ${s2}`);
}

// 8. contrast: each class="accent" (a fixed colour, which must have a stroke) against its stroke, at least 3:1
{
  const r = await ev(`setCharacter(__id); const rgb=s=>{ const m=(s||'').match(/rgba?\\(([^)]+)\\)/); if(!m) return null; const p=m[1].split(',').map(Number); return p.length>3&&p[3]===0?null:p.slice(0,3); };
    const L=c=>{ const f=v=>{ v/=255; return v<=.03928?v/12.92:((v+.055)/1.055)**2.4; }; return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2]); };
    const bad=[]; let n=0; for(const e of document.querySelectorAll('#body>.nix .accent,#body>.bfront .accent,#body>.nix.accent,#body>.bfront.accent')){ const s=getComputedStyle(e), f=rgb(s.fill), k=rgb(s.stroke); n++;
      if(!f||!k||!(parseFloat(s.strokeWidth)>0)){ bad.push(e.tagName+' accent has no literal fill or no stroke ('+s.fill+' / '+s.stroke+')'); continue; } const a=L(f), b=L(k), cr=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      if(cr<3) bad.push(e.tagName+' '+s.fill+' on '+s.stroke+' '+cr.toFixed(2)); }
    return {n,bad};`);
  if (ID !== "snowflake" && !ID.startsWith("plug:")) check(r.n >= 1, `${ID}: at least one .accent is marked`, `${r.n} found`);
  check(r.bad.length === 0, `${ID}: fixed accents vs their outline are at least 3:1 (${r.n} checked)`, r.bad.join("; "));
}

// 9. the surface: every look / skin / prop in fits stays inside 340 × 460, at rest and through a bounce
{
  await ev(`window.wxSleep=ms=>new Promise(r=>setTimeout(r,ms)); window.raf2=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    window.wxSet=async o=>{ clearInterval(window.__hold);
      const hold=()=>{ for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; Object.assign(SIT,{day:o.day!==false,weather:o.kind||null,heavy:false,windy:false,lean:0,party:false,meeting:false,cold:o.cold||0});
        Object.assign(info,{look_weather:true,look_party:true,look_meeting:true}); lowFx=false; nextFidAt=1e15; };
      hold(); window.__hold=setInterval(hold,50);
      const want={rain:0,snow:0,clear:0,partly:0,cloudy:0,windy:false,party:false,meeting:false,night:0,cold2:(o.cold||0)>=2}; if(o.kind) want[o.kind]=true;
      for(let i=0;i<400;i++){ if(Object.keys(want).every(k=>sitOn[k]===!!want[k])){ await wxSleep(1200); return 1; } await wxSleep(50); }
      throw new Error('looks did not settle '+JSON.stringify(sitOn)); }; return 1`);
  const fits = new Set(await ev(`setCharacter(__id); return [...BODY.fits]`));
  const cases = [];
  const clear = "clearInterval(__hold); for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; SIT.weather='';";
  const LOOKS = { tie: ["meeting", "SIT_P.tie", null], headphones: ["music", "SIT_P.hb", "SIT_P.hf"], shades: ["fullscreen", "SIT_P.sh", null], glasses: ["coding", "SIT_P.lensL", "SIT_P.lensR"], nightcap: ["night", "SIT_P.nc", null], party: ["party", "SIT_P.ph", null] };
  for (const [fit, [sit, el, also]] of Object.entries(LOOKS)) if (fits.has(fit)) cases.push({ name: fit, wait: 4800, el, also,
    on: `${clear} await new Promise(r=>setTimeout(r,8500)); __hold=setInterval(()=>{ for(const k of Object.keys(SIT)) if(typeof SIT[k]==='boolean') SIT[k]=false; SIT.${sit}=true; info.look_${sit}=true; info.look_beat=true; beat=1; beatAt=performance.now(); },60);` });
  for (const skin of ["halo", "crown", "sprout", "bow"]) if (fits.has(skin)) cases.push({ name: `skin ${skin}`, wait: 1500, el: "document.getElementById('accFront')", also: "document.getElementById('accBack')",
    on: `${clear} applyLook({...LOOK, skin:'${skin}'});`, after: "applyLook({...LOOK, skin:'none'});" });
  for (const [fit, o, el, also] of [["scarf", { cold: 1 }, "SIT_P.sc", null], ["beanie", { cold: 2 }, "SIT_P.bn", null]]) if (fits.has(fit)) cases.push({ name: fit, wait: 4000, el, also, on: `await wxSet(${JSON.stringify(o)});` });
  for (const cat of ["chat", "feed"]) if (fits.has(cat)) cases.push({ name: cat, wait: 1500, el: `SIT_P.${cat}.g`, on: `${clear} propOn={cat:'${cat === "chat" ? "chat" : "video"}',t0:performance.now(),until:performance.now()+60000,n:3};`, after: "propOn=null;" });
  for (const [n, o] of [["rain", { kind: "rain" }], ["clear day", { kind: "clear" }], ["cloudy", { kind: "cloudy" }]]) cases.push({ name: `weather ${n}`, noBounce: true, wait: 100, el: "({getBoundingClientRect:()=>window.__wxU})", after: "WXT=null;",
    on: `await wxSet(${JSON.stringify(o)}); let u=null;
      for(const t of [0,3.5,7,10.5,13.9]){ WXT=t; await raf2(); await wxSleep(60);
        for(const g of document.getElementById('wx').children){ if(g.tagName!=='g'||g.getAttribute('display')==='none') continue; const r=g.getBoundingClientRect(); if(!r.width||!r.height) continue;
          u=u?{left:Math.min(u.left,r.left),top:Math.min(u.top,r.top),right:Math.max(u.right,r.right),bottom:Math.max(u.bottom,r.bottom)}:{left:r.left,top:r.top,right:r.right,bottom:r.bottom}; } }
      window.__wxU=u?{...u,width:u.right-u.left,height:u.bottom-u.top}:{left:0,top:0,right:0,bottom:0,width:0,height:0};` });
  const box = e => `(()=>{ const e=${e}; if(!e) return null; const r=e.getBoundingClientRect(); return r.width&&r.height?[r.left,r.top,r.right,r.bottom]:null; })()`;
  const headphoneInk = `if(+SIT_P.hf.getAttribute('opacity')<.9) return [null,null];   // (not drawn: never a pass)
    const bounds=(pts,pad=0)=>[Math.min(...pts.map(p=>p.x))-pad,Math.min(...pts.map(p=>p.y))-pad,Math.max(...pts.map(p=>p.x))+pad,Math.max(...pts.map(p=>p.y))+pad];
    const path=SIT_P.bd.querySelector('path'), pm=path.getScreenCTM(), len=path.getTotalLength();
    const band=bounds(Array.from({length:60},(_,i)=>path.getPointAtLength(len*i/59).matrixTransform(pm)),5*Math.max(Math.hypot(pm.a,pm.b),Math.hypot(pm.c,pm.d)));
    const cups=[SIT_P.cL,SIT_P.cR].map(cu=>{ const m=cu.firstChild.getScreenCTM(); return bounds(Array.from({length:48},(_,i)=>{ const a=i*2*Math.PI/48; return new DOMPoint(18.5*Math.cos(a),29.5*Math.sin(a)).matrixTransform(m); })); });
    return [band,...cups];`;
  for (const c of cases) {
    await ev(c.on + " return 1"); await sleep(c.wait);
    let worst = null; const grow = b => { for (const r of b) if (r) worst = worst ? [Math.min(worst[0], r[0]), Math.min(worst[1], r[1]), Math.max(worst[2], r[2]), Math.max(worst[3], r[3])] : r; };
    const sample = c.name === "headphones" ? headphoneInk : `const a=${box(c.el)}, b=${c.also ? box(c.also) : "null"}; return [a,b];`;
    for (let i = 0; i < 6; i++) { grow(await ev(sample)); await sleep(120); }
    if (!c.noBounce) {
      const during = (start, ms) => ev(`${start}; const out=[]; const t0=performance.now(); while(performance.now()-t0<${ms}){ const s=(()=>{${sample}})(); out.push(...s); await new Promise(r=>requestAnimationFrame(r)); } return out;`);
      grow(await during("poke('happy',1500)", 1400)); await sleep(1200);
      grow(await during("FID={name:'roll',t0:performance.now(),dur:FIDGETS.roll.dur}; FIDGETS.roll.start&&FIDGETS.roll.start(FID)", 2600)); await ev("FID=null; return 1");
    }
    const ok = worst && worst[0] >= 3 && worst[1] >= 3 && worst[2] <= 337 && worst[3] <= 457;
    check(!!ok, `${ID}: ${c.name} fits 340 × 460`, worst ? worst.map(v => v.toFixed(0)).join(",") : "not drawn");
    if (c.after) await ev(c.after + " return 1");
  }
  await ev("clearInterval(__hold); WXT=null; return 1");
}
await done(tab);
