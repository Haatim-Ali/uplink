const AGENTS = ["Speed","Cost","Need"];
const GOALS = {Speed:"Cares about arrival time and driver reliability", Cost:"Cares about what the trip costs", Need:"Cares about which shelter: whoever has waited longest"};
const COLORS = {Speed:"var(--speed)",Cost:"var(--cost)",Need:"var(--need)"};
const ICON = {Speed:"",Cost:"",Need:""};   // agents are identified by name; color only reinforces it
const OUTCOME = {
  consensus:{ic:"",t:"All three agents agree",d:"The plan goes ahead."},
  majority:{ic:"",t:"Majority decision, dissent on record",d:"Two accepted, none vetoed. The objection is kept."},
  urgent:{ic:"",t:"Time is short: acting now",d:"The best-supported plan nobody vetoed goes."},
  irreconcilable:{ic:"",t:"No majority: asking a human",d:"After 3 rounds no plan has majority support."},
  unacceptable:{ic:"",t:"Unacceptable compromise: asking a human",d:"The majority's plan crosses an agent's red line."},
  over_budget:{ic:"",t:"Over budget: asking a human",d:"The winning plan costs more than the $25 limit."},
  insufficient_evidence:{ic:"",t:"Not enough evidence: asking the business",d:"An unconfirmed fact (allergens) blocks the decision."},
  human_timeout:{ic:"",t:"No answer in time: fallback rule used",d:"The top-ranked option was sent. The feed says so."},
};
let view = "live", sub = null;
let S = null, roundSel = null, lastNegKey = null, pinned = null;
// Debate playback: a new negotiation is revealed one message at a time, then the outcome lands.
const PLAY_MS = 900;
let play = {seq: null, shown: 0, total: 0};
setInterval(()=>{ if(voiceOn && speaking) return;   // with voices on, the next line waits for the current one
  if(play.seq !== null && play.shown < play.total){ play.shown++; if(S && view==="live") drawNegotiation(); } }, PLAY_MS);

// ---- Voices: each agent speaks in its own ElevenLabs voice (browser voice if there's no key) ----
let voiceOn = false, speaking = false, lastSpoken = null, speakTimer = null;
const audioCache = {};
const PITCH = {Speed:1.25, Cost:0.8, Need:1.05, Dispatch:1, Shelter:0.85};
const plain = html => { const t = document.createElement("div"); t.innerHTML = html; return t.textContent; };
function audioFor(who, text){
  const url = `/api/tts?who=${encodeURIComponent(who)}&text=${encodeURIComponent(text)}`;
  if(!audioCache[url]){ const a = new Audio(url); a.preload = "auto"; audioCache[url] = a; }
  return audioCache[url];
}
function endSpeak(){ speaking = false; clearTimeout(speakTimer); }
function browserSpeak(who, text){
  if(!window.speechSynthesis){ endSpeak(); return; }
  const u = new SpeechSynthesisUtterance(text); u.pitch = PITCH[who] ?? 1; u.rate = 1.08;
  u.onend = u.onerror = endSpeak; speechSynthesis.speak(u);
}
function speak(who, text, next){
  if(!voiceOn || !text) return;
  who = PITCH[who] !== undefined ? who : "Dispatch";
  speaking = true; clearTimeout(speakTimer); speakTimer = setTimeout(endSpeak, 20000);  // never stall the debate
  if(S && S.mode && S.mode.voice === "elevenlabs"){
    const a = audioFor(who, text); a.currentTime = 0;
    a.onended = endSpeak; a.onerror = ()=>browserSpeak(who, text);
    a.play().catch(()=>browserSpeak(who, text));
    if(next) audioFor(next.agent in PITCH ? next.agent : "Dispatch", next.text);   // fetch the next line while this one plays
  } else browserSpeak(who, text);
}
function replay(){ const n = pinned ? (S.negotiations||[]).find(h=>h.seq===pinned) : S.negotiation; if(!n) return; callFor = n.seq;
  play = {seq: n.seq, shown: 0, total: n.rounds.reduce((k,r)=>k+r.messages.length,0)}; drawNegotiation(); }
const $ = id => document.getElementById(id);
// Write HTML only when it changed: no flicker, hover and scroll survive the 1-second refresh.
function setHTML(el, html){ if(typeof el==="string") el=$(el); if(el._html!==html){ el._html=html; el.innerHTML=html; } }
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function toast(msg, kind="info"){
  const el = document.createElement("div");
  el.className = "toast " + kind; el.textContent = msg;
  $("toasts").appendChild(el);
  while($("toasts").children.length > 2) $("toasts").firstChild.remove();
  setTimeout(()=>{ el.classList.add("out"); setTimeout(()=>el.remove(), 400); }, 4500);
}
// Pop up the moments the audience should notice.
let lastSeq = null;
function toastNewEvents(){
  const seqs = S.feed.map(f=>f.seq||0); const max = seqs.length ? Math.max(...seqs) : 0;
  if(lastSeq === null || max < lastSeq){ lastSeq = max; return; }   // first load or reset
  S.feed.filter(f => f.seq > lastSeq).forEach(f => {
    const t = f.text;
    if(f.agent==="World" && /full tonight/.test(t)) toast(t.replace(/"/g,""), "bad");
    else if(f.agent==="World" && /cancelled/.test(t)) toast(t.split(".")[0], "bad");
    else if(f.agent==="World" && /delivered to/.test(t) && !/unsafe/.test(t)) toast(t.split(".")[0], "good");
    else if(f.agent==="World" && /(unsafe|lost|Turned away)/.test(t)) toast(t.split(".")[0], "bad");
    else if(f.agent==="Directory") toast("New pantry: " + t.split("(")[0], "info");
    else if(f.agent==="Adapt") toast(t, "info");
    else if(f.agent==="Human" && /asking a coordinator|no safe plan/.test(t)) toast("Coordinator needed for " + (f.donation||""), "warn");
    else if(f.agent==="Contact" && /(accepted|declined|No answer)/.test(t)) toast(t.split(".")[0], /accepted/.test(t) ? "good" : "warn");
  });
  lastSeq = max;
}
async function post(url, body){ const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}); const j = await r.json().catch(()=>({})); if(!r.ok) toast(j.error||"Request failed"); return j; }

// ---------- map ----------
// Calm basemap: standard OpenStreetMap tiles, desaturated and lightened in CSS (CARTO's light tiles now need an API key).
// Few, clear markers: shelters are labeled pins when they matter, drivers on a job stand out, idle ones fade back.
let map=null, layers={}, mapTried=false;
function ensureMap(){
  if(mapTried){ if(map) setTimeout(()=>map.invalidateSize(), 0); return; }
  mapTried = true;
  try{
    map = L.map("map",{zoomControl:true}).setView([37.377,-121.97],13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"© OpenStreetMap contributors"}).addTo(map);
    layers = {route:L.layerGroup().addTo(map), np:L.layerGroup().addTo(map), biz:L.layerGroup().addTo(map), drv:L.layerGroup().addTo(map)};
  }catch(e){ map = null; $("map").innerHTML = "<p class='empty' style='padding:12px'>The map needs internet for its tiles. Everything else still works.</p>"; }
}

const markers = {};   // id -> Leaflet marker, created once and updated in place
function upsert(id, make, update){ if(!markers[id]) markers[id]=make(); update(markers[id]); }
const DONE_ST = ["delivered","spoiled","expired"];
function focusSets(){
  const np = new Set(), biz = new Set(), drv = new Set();
  S.donations.filter(d=>!DONE_ST.includes(d.status)).forEach(d=>{
    const b = S.businesses.find(x=>x.name===d.business_name); if(b) biz.add(b.id);
    if(d.plan){ np.add(d.plan.np); drv.add(d.plan.driver); }
    (d.options||[]).slice(0,2).forEach(o=>np.add(o.np));
  });
  return {np, biz, drv};
}
function npIcon(n, inv){
  return L.divIcon({className:"", iconSize:[16,16], iconAnchor:[8,8],
    html:`<div class="mp ${inv?"inv":""} ${n.full?"full":""}"><i></i><span>${esc(n.name)}${n.full?" (full)":""}</span></div>`});
}
function bizIcon(b, inv){ return L.divIcon({className:"", iconSize:[12,12], iconAnchor:[6,6], html:`<div class="mb ${inv?"inv":""}"><i></i><span>${esc(b.name)}</span></div>`}); }
function driverIcon(dr, active){
  if(active) return L.divIcon({className:"", iconSize:[28,28], iconAnchor:[14,14], html:`<div class="drv on">${esc(dr.name[0])}</div>`});
  return L.divIcon({className:"", iconSize:[12,12], iconAnchor:[6,6], html:`<div class="drv ${dr.status==="off"?"off":"idle"}"></div>`});
}
function bearing(a, b){ const dx = (b[1]-a[1]) * Math.cos(a[0]*Math.PI/180), dy = b[0]-a[0]; return Math.atan2(dx, dy) * 180 / Math.PI; }
function median(a){ const s = a.slice().sort((x,y)=>x-y); return s.length ? s[Math.floor(s.length/2)] : 0; }
function core(points){   // drop far-away outliers so the view fits the area that matters
  if(points.length < 4) return points;
  const c = [median(points.map(p=>p[0])), median(points.map(p=>p[1]))];
  const dist = p => Math.hypot(p[0]-c[0], p[1]-c[1]), lim = 2.5 * median(points.map(dist)) + 0.01;
  return points.filter(p => dist(p) <= lim);
}
function drawMap(){
  if(!map) return;
  const live = new Set(), F = focusSets();
  S.nonprofits.forEach(n=>{
    const id="np:"+n.id; live.add(id); const inv = F.np.has(n.id);
    upsert(id, ()=>L.marker([n.lat,n.lng],{icon:npIcon(n,inv)}).bindTooltip("",{direction:"top",offset:[0,-8]}).addTo(layers.np), m=>{
      const key = inv+"|"+n.full+"|"+n.name; if(m._key!==key){ m._key=key; m.setIcon(npIcon(n,inv)); m.setZIndexOffset(inv?500:0); }
      m.setTooltipContent(`<b>${esc(n.name)}</b>${n.full?" (full)":""}<br>${n.has_fridge?"Fridge":"No fridge"} · open until ${n.open_until}<br>${n.received}/${n.capacity_servings} servings · last fed ${n.last_donation_days}d ago`);
    });
  });
  S.businesses.forEach(b=>{
    const id="biz:"+b.id; live.add(id); const inv = F.biz.has(b.id);
    upsert(id, ()=>L.marker([b.lat,b.lng],{icon:bizIcon(b,inv)}).bindTooltip(esc(b.name),{direction:"top",offset:[0,-6]}).addTo(layers.biz), m=>{
      if(m._key!==inv){ m._key=inv; m.setIcon(bizIcon(b,inv)); m.setZIndexOffset(inv?400:0); }
    });
  });
  S.drivers.forEach(dr=>{
    const id="dr:"+dr.id; live.add(id); const active = F.drv.has(dr.id) || dr.status==="busy";
    upsert(id, ()=>L.marker([dr.lat,dr.lng],{icon:driverIcon(dr,active)}).bindTooltip("",{direction:"top",offset:[0,-8]}).addTo(layers.drv), m=>{
      m.setLatLng([dr.lat,dr.lng]);
      const key = active+"|"+dr.status; if(m._key!==key){ m._key=key; m.setIcon(driverIcon(dr,active)); m.setZIndexOffset(active?1000:-100); }
      m.setTooltipContent(`${esc(dr.name)}<br>${active?"On a job":dr.status==="off"?"Off shift":"Available"} · ${Math.round(dr.reliability*100)}% reliable`);
    });
  });
  for(const id in markers){ if(!live.has(id)){ markers[id].remove(); delete markers[id]; } }   // e.g. after a reset

  // routes: bold solid lines with an arrow near the destination
  layers.route.clearLayers();
  const active = S.donations.filter(d=>d.status==="en_route" && d.plan);
  const focus = [];
  active.forEach(d=>{
    const dr = S.drivers.find(x=>x.id===d.plan.driver); if(!dr) return;
    const to = [d.dest.lat,d.dest.lng], me = [dr.lat,dr.lng], from = [d.origin.lat,d.origin.lng];
    const pts = d.picked ? [me,to] : [me,from,to];
    L.polyline(pts,{color:"#f05a22",weight:5,opacity:.85,lineCap:"round"}).addTo(layers.route);
    const a = pts[pts.length-2], t = 0.82, at = [a[0]+(to[0]-a[0])*t, a[1]+(to[1]-a[1])*t];
    L.marker(at,{interactive:false,icon:L.divIcon({className:"",iconSize:[16,16],iconAnchor:[8,8],html:`<div class="arrow" style="transform:rotate(${bearing(a,to).toFixed(0)}deg)"></div>`})}).addTo(layers.route);
    focus.push(me, from, to);
  });
  // fit to the active routes, else to the shelters, whenever that focus changes
  let pts = focus, mode = "routes";
  if(!pts.length){
    pts = S.donations.filter(d=>!DONE_ST.includes(d.status) && d.origin).map(d=>[d.origin.lat,d.origin.lng]);
    pts = pts.concat(S.nonprofits.filter(n=>F.np.has(n.id)).map(n=>[n.lat,n.lng]));
    mode = "pending";
  }
  if(!pts.length){ pts = S.nonprofits.map(n=>[n.lat,n.lng]); mode = "all"; }
  const fitKey = mode + "|" + active.map(d=>d.id+(d.picked?"p":"")).join(",") + "|" + (mode==="all" ? S.nonprofits.length : [...F.np].join(","));
  if(map._fitKey !== fitKey && pts.length){
    map._fitKey = fitKey;
    const c = core(pts);
    map.fitBounds(L.latLngBounds(c), {padding:[50,50], maxZoom:15});
  }
}

// ---------- negotiation ----------
function planName(id){
  const [np,dr,join] = id.split("|");
  const N = S.nonprofits.find(x=>x.id===np);
  if(join) return `${esc(N?N.name:np)} <span class="muted">· combined trip with ${esc(join.replace("join-",""))}</span>`;
  const D = S.drivers.find(x=>x.id===dr);
  return `${esc(N?N.name:np)} <span class="muted">via ${esc(D?D.name:dr)}</span>`;
}
function currentNeg(){ return pinned ? (S.negotiations||[]).find(h=>h.seq===pinned) : S.negotiation; }

// Current donation card: the donation whose negotiation is on screen.
function drawDonationCard(n){
  let d = n ? S.donations.find(x=>x.id===n.donation) : null;
  if(!d) d = S.donations.slice().reverse().find(x=>!["delivered","spoiled","expired"].includes(x.status)) || null;
  if(!d){
    setHTML("cur-don", `<div class="empty-state"><p><b>No donation in progress</b></p><p class="muted">Choose a scenario under Demo controls and run it, or send a real donation from the Business page.</p><button class="btn primary sm" type="button" onclick="document.getElementById('start').click()">▶ Run selected scenario</button></div>`);
    return;
  }
  const live = !["delivered","spoiled","expired"].includes(d.status);
  const where = d.plan ? `${esc(d.plan.np_name)} <span class="muted">via ${esc(d.plan.driver_name)}</span>` : `<span class="muted">Destination not chosen yet</span>`;
  const pct = Math.max(0, Math.min(100, Math.round(100 * d.minutes_left / (d.food.safe_minutes || 120))));
  setHTML("cur-don", `<div class="cd">
    <div class="cd-top"><span class="card-title">Current donation · ${esc(d.id)}</span><span class="st ${d.status}">${STATUS[d.status] || esc(d.status.replace("_"," "))}</span></div>
    <div class="cd-food">${d.food.servings} servings of ${esc(d.food.items.join(", "))}</div>
    <div class="cd-route">${esc(d.business_name)} to ${where}</div>
    <div class="cd-meta"><span class="pill outline">${esc(d.food.category)}</span>${d.food.needs_cold?'<span class="pill outline">Keep cold</span>':""}${d.food.allergens.length?`<span class="pill warn">Allergens: ${esc(d.food.allergens.join(", "))}</span>`:""}</div>
    ${live?`<div class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left} min until unsafe (${esc(d.safe_until)})</div><div class="tbar" aria-hidden="true"><i style="width:${pct}%"></i></div>`:""}</div>`);
}

function pin(seq){ pinned = (pinned===seq ? null : seq); lastNegKey=null; drawNegotiation(); }
function drawNegotiation(){
  try{ drawWire(); }catch(e){ console.error(e); }
  const hero = $("hero-panel");
  const hist = S.negotiations || [];
  const n = currentNeg();
  drawDonationCard(n);
  if(S.busy && !pinned){ hero.hidden = false; setHTML("neg", `<div class="status-banner debating" role="status"><div><div class="t">Agents are deliberating…</div><div class="d">The simulated clock is paused until they finish.</div></div></div>`); return; }
  if(!n){ hero.hidden = true; return; }
  hero.hidden = false;
  const shownSeq = pinned || n.seq;
  const msgs = n.rounds.flatMap(r => r.messages.map(m => ({...m, round: r.round})));
  if(!pinned && n.seq !== play.seq && play.seq !== null && n.seq > play.seq){ play = {seq: n.seq, shown: 0, total: msgs.length}; callFor = n.seq; }
  if(play.seq === null){ play = {seq: n.seq, shown: msgs.length, total: msgs.length}; }   // first load: no replay of old news
  const shown = play.seq === n.seq ? play.shown : msgs.length;
  const playing = shown < msgs.length;
  const key = n.seq + "|" + n.donation + "|" + n.rounds.length + "|" + n.outcome + "|" + (n.plan?n.plan.id:"");
  if(playing){ roundSel = Math.max(0, (shown ? msgs[shown-1].round : 1) - 1); lastNegKey = null; }
  else if(key!==lastNegKey){ roundSel = n.rounds.length-1; lastNegKey = key; }
  if(roundSel >= n.rounds.length) roundSel = n.rounds.length-1;

  // ---- summary (always visible): agents, what each wants, outcome in plain words ----
  const rs = playing ? roundSel : n.rounds.length-1, rr = n.rounds[rs];
  const said = msgs.slice(0, shown);
  const cards = AGENTS.map(a=>{
    const pid = rr.proposals[a];
    const last = said.filter(m => m.agent === a).pop();   // what this agent just said: the debate, visible without a click
    const quote = last ? `<div class="says ${last.type}${playing && said[said.length-1] === last ? " now" : ""}" title="${esc(last.text)}">“${esc(last.text)}”</div>` : "";
    return `<div class="agent ${a}"><div class="agent-top"><h3><span aria-hidden="true">${ICON[a]}</span><span class="a-name">${a}</span></h3><span class="wt" title="Vote weight. It grows when this agent's earlier warning about a driver turned out right.">vote ×${(n.weights||{})[a]??1}</span></div><div class="goal">${GOALS[a]}</div><div class="wants">Proposes: <b>${pid ? planName(pid) : "—"}</b></div>${quote}</div>`;
  }).join("");
  const o = OUTCOME[n.outcome] || {ic:"•", t:(n.outcome||"Decision").replace(/_/g," "), d:""};
  const chosen = n.plan ? `<div class="pick">Decision: <b>${planName(n.plan.id)}</b></div>` : "";
  const dissent = (n.dissent||[]).map(x=>`<div class="dissent"><b>${esc(x.agent)} dissents:</b> ${esc(x.reason)}</div>`).join("");
  const banner = !playing
    ? `<div class="status-banner outcome ${OUTCOME[n.outcome]?n.outcome:"other"} pop" role="status"><div><div class="t">${o.t}</div><div class="d">${o.d}</div>${chosen}${dissent}</div></div>`
    : `<div class="status-banner debating" role="status"><div><div class="t">Debating, round ${rr.round} of up to 3…</div><div class="d">Each agent proposes a plan, then votes on every plan on the table.</div></div></div>`;
  setHTML("neg", `
    <div class="neg-title"><div><span class="don-id">${esc(n.donation)}</span><b class="food">${esc(n.food)}</b></div><span class="pill outline" title="How the agents reason: fixed scoring rules, or an AI model (red lines are always enforced in code)">${n.mode==="llm"?"AI reasoning":"Rules reasoning"}</span></div>
    ${banner}
    <div class="agents">${cards}</div>`);
  if(voiceOn && play.seq === n.seq){   // speak the newest line, then the outcome
    const k = n.seq + ":" + (playing ? shown : "end");
    if(k !== lastSpoken && !(speaking && !playing)){
      lastSpoken = k;
      if(playing && shown) speak(msgs[shown-1].agent, msgs[shown-1].text, msgs[shown]);
      else if(!playing) speak("Dispatch", plain(o.t + ". " + (n.plan ? "Decision: " + planName(n.plan.id) : "")));
    }
  }

  if(!playing && n.plan && callFor === n.seq && !pinned){ callFor = null; startCall(n); }

  // ---- detail (inside "See the debate"): only built when opened ----
  if(!$("debate-more").open) return;
  setHTML("history", hist.length > 1 ? `<span class="hist-label">Past negotiations</span>` +
    hist.map(h=>`<button class="hb ${shownSeq===h.seq?"on":""}" aria-pressed="${shownSeq===h.seq}" onclick="pin(${h.seq})">${esc(h.time)} · ${esc(h.donation)}</button>`).join("") +
    (pinned?`<button class="follow" onclick="pin(null)">Back to live</button>`:"") : "");
  setHTML("rounds", n.rounds.map((r,i)=>`<button class="${i===roundSel?"on":""}" aria-pressed="${i===roundSel}" title="Show round ${r.round}" onclick="roundSel=${i};drawNegotiation()">Round ${r.round}</button>`).join(" "));
  const r = n.rounds[roundSel];
  const final = roundSel===n.rounds.length-1;
  const rows = Object.keys(r.votes).map(pid=>{
    const win = n.plan && n.plan.id===pid && final;
    const cells = AGENTS.map(a=>{
      const v = r.votes[pid][a], sc = (n.scores[pid]||{})[a] ?? 0;
      const veto = !v.accept && v.reason.startsWith("Veto");
      const txt = v.accept ? "Accept" : veto ? "Veto" : "Object";
      return `<td title="${esc(v.reason)}"><span class="vote ${v.accept?"yes":veto?"veto":"no"}">${txt}</span>
        <div class="score" title="${a}'s score for this plan: ${Math.round(sc*100)} of 100"><div class="bar"><i style="width:${Math.round(sc*100)}%;background:${COLORS[a]}"></i></div><em>${Math.round(sc*100)}</em></div></td>`;
    }).join("");
    return `<tr class="${win?"winner":""}"><td class="plan">${win?'<span class="pill ok chosen">Chosen</span><br>':""}${planName(pid)}</td>${cells}</tr>`;
  }).join("");
  const bubbles = msgs.slice(0, shown).map((m,i) => `<div class="bubble ${m.agent} ${m.type}${i===shown-1 && playing ? " new" : ""}${i===shown-1 && playing && m.type==="objection" ? " shake" : ""}">
      <span class="b-who">${ICON[m.agent]||""} ${esc(m.agent)}</span><span class="b-r">R${m.round}</span>${esc(m.text)}</div>`).join("");
  setHTML("debate-body", `
    <div class="debate" id="debate" role="log" aria-label="Debate transcript">${bubbles || '<span class="muted">The agents are about to speak…</span>'}</div>
    <div class="matrix-wrap"><table class="matrix"><caption class="sr-only">Votes by each agent on every plan, round ${r.round}</caption><thead><tr><th scope="col">Plans on the table (round ${r.round})</th>${AGENTS.map(a=>`<th scope="col" class="${a}">${ICON[a]} ${a}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="vote-key"><b>Veto</b> = the plan crosses this agent's red line and is blocked. Bars are each agent's own score (0 to 100).</p>
    <div class="tools">${!playing?`<button class="replay" onclick="replay()">Replay debate</button>`:""}${tally()}</div>`);
  const deb = $("debate"); if(deb) deb.scrollTop = deb.scrollHeight;
}

function tally(){
  const o = S.outcomes || {}, names = {consensus:"agreed", majority:"majority", urgent:"time short", unacceptable:"unacceptable compromise",
    irreconcilable:"irreconcilable", insufficient_evidence:"asked for evidence", over_budget:"over budget", human_timeout:"fallback rule used"};
  const parts = Object.entries(o).map(([k,v])=>`<span>${names[k]||k}: <b>${v}</b></span>`).join("");
  return parts ? `<div class="tally"><span class="lead">How negotiations have ended so far:</span>${parts}</div>` : "";
}

function drawHuman(){
  const waiting = S.donations.filter(d=>d.status==="awaiting_human");
  const asking = S.donations.filter(d=>d.status==="awaiting_info");
  if(!waiting.length && !asking.length){ setHTML("human", `<div class="inbox-empty"><b>Nothing needs you right now</b>The agents are handling it. Questions for a coordinator or a business show up here, and a red badge appears in the menu.</div>`); return; }
  setHTML("human", waiting.map(d=>`
    <div class="human" role="alert"><span class="h-tag">Decision needed · coordinator</span>
      <div class="h-title">The agents are asking a person to decide ${esc(d.id)}</div>
      <div class="h-why"><b>Why:</b> ${esc(d.why||"the agents could not agree")}. ${esc(d.food.items.join(", "))}, ${d.minutes_left} min until unsafe.</div>
      ${d.decide_by?`<div class="h-why"><b>Decide by ${esc(d.decide_by)}.</b> After that, the agents' top option that can still arrive safely goes automatically.</div>`:""}
      <div class="opts">${d.options.map(o=>`<button class="opt" onclick="approve('${d.id}','${o.id}')"><b>${esc(o.np_name)}</b><span class="meta">via ${esc(o.driver_name)} · ${o.dur} min · $${o.cost.toFixed(2)}</span><span class="go">Approve this plan</span></button>`).join("")}</div></div>`).join("")
  + asking.map(d=>`
    <div class="human ask" role="alert"><span class="h-tag">Question for the business</span>
      <div class="h-title">${esc(d.business_name)}: is ${esc(d.id)} free of ${esc(d.asked_about)}?</div>
      <div class="h-why">${esc(d.food.items.join(", "))}. There is not enough evidence to decide yet. If nobody answers, the agents act on what they know and treat unconfirmed allergens as present.</div>
      <div class="opts"><button class="opt" onclick="confirmInfo('${d.id}',true)"><b>Listed allergens only</b><span class="meta">${esc(d.food.allergens.join(", ")||"none listed")}</span><span class="go">Business confirms</span></button>
      <button class="opt" onclick="confirmInfo('${d.id}',false)"><b>Can't say for sure</b><span class="meta">Allergens stay unconfirmed</span><span class="go">Business can't confirm</span></button></div></div>`).join(""));
}
async function approve(d,p){ await post("/api/approve",{donation:d,plan:p}); refresh(); }
async function confirmInfo(id, sure){ const d = S.donations.find(x=>x.id===id); await post("/api/confirm",{donation:id, allergens: sure ? d.food.allergens : null}); refresh(); }

// ---------- agent network ----------
const KIND = {announce:"Announces", accept:"Accept", counter:"Counter-offer", decline:"Decline", bid:"Bid", award:"Award", split:"Split", escalate:"Ask a human"};
function drawNetwork(){
  const a = S.agents_online;
  if(a) setHTML("net-agents", `${a.businesses} business agents · ${a.shelters} shelter agents · ${a.drivers} driver agents · ${a.coordinators} coordinators`);
  const n = currentNeg();
  if(!n){ setHTML("net", `<div class="empty-state"><p class="muted">No donation has been announced yet. When one is, every shelter and driver agent answers here.</p></div>`); return; }
  const all = (S.network||[]).filter(m => m.donation === n.donation);
  let start = 0; all.forEach((m,i) => { if(m.kind === "announce") start = i; });   // the latest round only
  const msgs = all.slice(start);
  const col = (num, title, kinds) => {
    const items = msgs.filter(m => kinds.includes(m.kind));
    return `<div class="net-col"><h3><span class="step" aria-hidden="true">${num}</span>${title}</h3>${items.map(m => `<div class="msg ${m.kind}"><div class="msg-top"><b>${esc(m.from)}</b><span class="k ${m.kind}">${KIND[m.kind]||m.kind}</span></div>${esc(m.text)}</div>`).join("") || '<p class="empty">Nothing yet.</p>'}</div>`;
  };
  setHTML("net", `<div class="net-grid">
    ${col(1, "Business agent announces", ["announce"])}
    ${col(2, "Shelter agents answer", ["accept","counter","decline"])}
    ${col(3, "Driver agents bid", ["bid"])}
    ${col(4, "Coordinators decide", ["escalate","award","split"])}
  </div>`);
}

// ---------- activity lists ----------
const STATUS = {awaiting_info:"Asking business", awaiting_human:"Asking human", awaiting_shelter:"Asking shelter", delivered:"Delivered", spoiled:"Spoiled", expired:"Expired", en_route:"En route"};
const groupOf = a => ["Speed","Cost","Need"].includes(a) ? "agents" : a==="Safety" ? "Safety" : ["Human","Contact"].includes(a) ? "humans" : "world";
function drawFeed(){
  const f = $("feed-filter").value;
  const rows = S.feed.slice().reverse().filter(x => f==="all" || groupOf(x.agent)===f);
  setHTML("feed", rows.map(f=>`<div><time>${esc(f.time)}</time><span class="who ${esc(f.agent)}">${ICON[f.agent]?ICON[f.agent]+" ":""}${esc(f.agent)}</span><span class="${f.type==="objection"?"objection":""}">${esc(f.text)}</span></div>`).join("") || "<div class='empty-state'><p class='muted'>Nothing here yet. Events appear as the agents work.</p></div>");
}
function drawLog(){
  const f = $("log-filter").value;
  const rows = S.decisions.slice().reverse().filter(x => f==="all" || x.verdict===f);
  setHTML("log", rows.map(x=>`<div><span class="v ${x.verdict}">${x.verdict==="allowed"?"Allowed":"Blocked"}</span><span class="tx"><b>${esc(x.donation)}</b> · ${esc(x.text)}</span></div>`).join("") || "<div class='empty-state'><p class='muted'>No safety decisions yet. Each blocked plan is listed here with its reason.</p></div>");
}
function drawDons(){
  setHTML("dons", S.donations.slice().reverse().map(d=>{
    const live = !["delivered","spoiled","expired"].includes(d.status);
    const where = d.plan ? `${esc(d.plan.np_name)} via ${esc(d.plan.driver_name)}` : "planning…";
    const pct = Math.max(0, Math.min(100, Math.round(100 * d.minutes_left / (d.food.safe_minutes || 120))));
    return `<div class="don"><div class="don-top"><b>${esc(d.id)}</b><span class="st ${d.status}">${STATUS[d.status] || esc(d.status.replace("_"," "))}</span></div>
      <div>${esc(d.food.items.join(", "))} · ${d.food.servings} servings</div>
      <div class="route">${esc(d.business_name)} to ${where}</div>
      ${live?`<div class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left} min until unsafe (${esc(d.safe_until)})</div><div class="tbar" aria-hidden="true"><i style="width:${pct}%"></i></div>`:""}</div>`;
  }).join("") || "<div class='empty-state'><p class='muted'>No donations yet. Run a scenario or send one from the Business page.</p></div>");
}

function drawCamera(){
  const cams = S.cameras || {};
  const names = Object.keys(cams);
  if(!names.length){ setHTML("cam-status", "No camera connected"); return; }
  setHTML("cam-status", names.map(b => {
    const biz = (S.businesses.find(x=>x.id===b)||{}).name || b;
    const seen = Object.entries(cams[b]).filter(([k,v])=>v>0).map(([k,v])=>`${v} ${k}`).join(", ") || "nothing yet";
    return `Camera at ${esc(biz)} sees: ${esc(seen)}`;
  }).join(" · "));
}

// ---------- always-on pieces: clock, mode, KPIs, decision badge ----------
let prevPending = null;
function pendingList(){ return S.donations.filter(d=>d.status==="awaiting_human"||d.status==="awaiting_info"); }
function drawGlobal(){
  const i = S.impact;
  const vals = {meals:i.meals, lbs:i.lbs, orgs:i.orgs, lost:i.spoiled, cost:"$"+i.cost.toFixed(2), esc:i.escalations};
  document.querySelectorAll("[data-k]").forEach(el=>{ el.textContent = vals[el.dataset.k]; if(el.hasAttribute("data-bad")) el.classList.toggle("nonzero", i.spoiled>0); });
  $("clock").textContent = S.now + (S.paused?" (paused)":"");
  $("mode").textContent = modeText(S.mode);
  const ax = S.agntcy || {}, xp = $("xport");
  if(xp){ xp.textContent = S.mode.mesh && S.mode.mesh_transport === "a2a" ? `AGNTCY · A2A over NATS · ${S.mode.mesh} agent processes`
      : ax.on ? `AGNTCY · A2A over NATS · ${ax.agents} agents${ax.last_ms != null ? " · " + ax.last_ms + " ms" : ""}`
      : S.mode.mesh ? `${S.mode.mesh} agent processes · HTTP` : "in-process";
    xp.title = ax.on ? `${ax.broadcasts} broadcasts, ${ax.messages} A2A messages so far` : (ax.reason || ""); xp.classList.toggle("on", !!(ax.on || S.mode.mesh)); }
  $("pause").textContent = S.paused ? "Resume" : "Pause";
  drawCamera();
  const pend = pendingList(), c = $("dec-count");
  c.hidden = !pend.length; c.textContent = pend.length;
  document.title = (pend.length ? `(${pend.length}) ` : "") + "Uplink · food rescue agents";
  if(prevPending !== null && pend.length > prevPending){
    c.classList.remove("pulse"); void c.offsetWidth; c.classList.add("pulse");
    if(pend.some(d=>d.status==="awaiting_info") && view!=="decisions") toast("The agents have a question for a business", "warn");
  }
  prevPending = pend.length;
}

function drawLive(){
  const scn = (S.scenarios.find(x=>x.name===S.scenario)||{}).title;
  const run = $("sl-run");
  run.className = "pill " + (S.paused ? "warn" : "ok"); run.textContent = S.paused ? "Paused" : `Running ${S.speed}×`;
  setHTML("sl-scn", scn ? esc(scn.split(":")[0]) : "No scenario running");
  setHTML("sl-extra", `${S.donations.length} donation${S.donations.length===1?"":"s"} · ${S.agents_online ? S.agents_online.shelters+" shelters · "+S.agents_online.drivers+" drivers" : ""}`);
  const pend = pendingList(), al = $("live-alert");
  al.hidden = !pend.length;
  setHTML(al, pend.length ? `<span>${pend.length} decision${pend.length>1?"s":""} waiting for you (${pend.map(d=>esc(d.id)).join(", ")}). Open Decisions</span>` : "");
  drawNegotiation(); drawMap();
}

// ---------- agent services (the mesh) ----------
const KIND_LABEL = {negotiator:"Negotiators", shelter:"Shelter agents", driver:"Driver agents"};
let meshBusy = false, meshHover = false;
$("mesh-agents").addEventListener("pointerenter", () => meshHover = true);
$("mesh-agents").addEventListener("pointerleave", () => meshHover = false);
async function drawMesh(){
  if(meshBusy) return; meshBusy = true;
  let m;
  try{ m = await (await fetch("/api/mesh")).json(); } catch(e){ meshBusy = false; return; }
  meshBusy = false;
  if(!m.enabled){
    setHTML("mesh-sum", `<div class="panel muted">The agents are running in-process right now. Start the app without <code>MESH=0</code> to run each agent as its own service.</div>`);
    setHTML("mesh-agents", ""); setHTML("mesh-trace", ""); return;
  }
  const online = m.agents.filter(a=>a.status==="online");
  const ms = m.trace.filter(t=>t.ok).map(t=>t.ms);
  const avg = ms.length ? (ms.reduce((a,b)=>a+b,0)/ms.length).toFixed(1) : "–";
  setHTML("mesh-sum", `<div class="kpis"><div class="kpi"><b>${online.length}</b><span>agents online, each its own process</span></div>
    <div class="kpi"><b>${m.messages.toLocaleString()}</b><span>messages sent</span></div>
    <div class="kpi"><b>${m.failed}</b><span>messages that got no answer</span></div>
    <div class="kpi"><b>${avg} ms</b><span>average reply time (recent)</span></div></div>
    <p class="muted small">Agent directory: <code>${esc(m.directory)}</code> · Messages: ${m.transport === "a2a" ? `<b>AGNTCY A2A over NATS</b> (<code>${esc(m.nats)}</code>), one broadcast per step` : "HTTP"}</p>`);
  const port = a => ((a.locator||{}).url||"").replace(/^https?:\/\/[^:]+:(\d+).*$/, ":$1");
  const groups = ["negotiator","shelter","driver"].map(k => {
    const rows = m.agents.filter(a=>a.kind===k).map(a => {
      const on = a.status==="online";
      const st = on ? `<span class="pill ok">● Online</span>` : a.status==="starting" ? `<span class="pill warn">Starting</span>` : `<span class="pill bad">✕ Stopped</span>`;
      const btn = on ? `<button class="btn sm" onclick="meshAct('stop','${esc(a.id)}')">Stop</button>` : `<button class="btn sm" onclick="meshAct('start','${esc(a.id)}')">Restart</button>`;
      return `<tr><td><b>${esc(a.agent)}</b><div class="muted small">${esc((a.skills||[]).join(" · "))}${(a.protocols||[]).includes("a2a/nats") ? ` · <b>A2A card</b> <code>${esc(a.a2a.name)}</code>` : ""}</div></td><td><code>${esc(port(a))}</code></td><td class="n">${a.pid||"–"}</td><td>${st}</td><td class="n">${a.sent??0}</td><td class="n">${a.avg_ms??"–"}</td><td>${btn}</td></tr>`;
    }).join("");
    return rows ? `<h3 class="mesh-h">${KIND_LABEL[k]}</h3><table class="data"><thead><tr><th>Agent · skills</th><th>Port</th><th class="n">PID</th><th>Status</th><th class="n">Messages</th><th class="n">Avg ms</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : "";
  }).join("");
  if(!meshHover) setHTML("mesh-agents", groups);   // hold still while the pointer is over the buttons
  const now = Date.now()/1000;
  setHTML("mesh-trace", m.trace.length ? `<table class="data"><thead><tr><th>When</th><th>From → to</th><th>Message → reply</th><th class="n">ms</th><th>Donation</th></tr></thead><tbody>${
    m.trace.slice(0, 60).map(t => `<tr><td class="muted">${Math.max(0, Math.round(now - t.t))}s ago</td><td><code>${esc(t.from)}</code> → <code>${esc(t.to)}</code></td><td>${esc(t.type)} → ${t.ok ? esc(t.reply) : `<span class="pill bad">${esc(t.error||"no answer")}</span>`} <span class="muted small">${esc(t.via||"")}</span></td><td class="n">${t.ms}</td><td>${esc(t.donation||"")}</td></tr>`).join("")
  }</tbody></table>` : `<p class="empty">No messages yet. Run a scenario from Demo controls.</p>`);
}
async function meshAct(action, id){
  const r = await post("/api/mesh/" + action, {id});
  toast(r.ok ? (action==="stop" ? `Stopped ${id}. It drops out of the agent directory.` : `Restarted ${id}.`) : `Couldn't ${action} ${id}.`, r.ok ? "info" : "bad");
  setTimeout(drawMesh, 300);
}

// ---------- routing ----------
const VIEWS = ["live","decisions","activity","evidence","how"], TABS = ["network","feed","safety","donations","mesh"];
function route(){
  const h = (location.hash || "#/live").replace(/^#\/?/, "").split("/");
  view = VIEWS.includes(h[0]) ? h[0] : "live";
  sub = view==="activity" ? (TABS.includes(h[1]) ? h[1] : "network") : null;
  document.querySelectorAll(".view").forEach(v => v.hidden = v.dataset.view !== view);
  document.querySelectorAll("[data-route]").forEach(a => { const on = a.dataset.route === view; a.classList.toggle("active", on); if(a.tagName==="A"){ if(on) a.setAttribute("aria-current","page"); else a.removeAttribute("aria-current"); } });
  document.querySelectorAll("#act-tabs a").forEach(a => { const on = a.dataset.tab === sub; a.classList.toggle("active", on); a.setAttribute("aria-selected", on); });
  document.querySelectorAll(".tabpanel").forEach(p => p.hidden = p.dataset.tabpanel !== sub);
  closeMenus();
  if(view==="live") ensureMap();
  if(view==="evidence") loadEvidence();
  window.scrollTo(0, 0);
  render();
}
function render(){
  if(!S) return;
  drawGlobal();
  if(view==="live") drawLive();
  else if(view==="decisions") drawHuman();
  else if(view==="activity"){
    if(sub==="network") drawNetwork(); else if(sub==="feed") drawFeed(); else if(sub==="safety") drawLog(); else if(sub==="mesh") drawMesh(); else drawDons();
  }
  toastNewEvents();
}
window.addEventListener("hashchange", route);

// ---------- dropdown menus (button + aria-expanded, Esc, click outside) ----------
function closeMenus(except){
  document.querySelectorAll(".dd-menu").forEach(m => { if(m!==except){ m.hidden = true; const b = document.querySelector(`[aria-controls="${m.id}"]`); if(b) b.setAttribute("aria-expanded","false"); } });
}
document.querySelectorAll(".dd-btn").forEach(b => b.addEventListener("click", e => {
  const m = $(b.getAttribute("aria-controls")), open = m.hidden;
  closeMenus(m); m.hidden = !open; b.setAttribute("aria-expanded", String(open)); e.stopPropagation();
}));
document.addEventListener("click", e => { if(!e.target.closest(".dd") || e.target.closest(".dd-menu a")) closeMenus(); });
document.addEventListener("focusin", e => { if(!e.target.closest(".dd")) closeMenus(); });
document.addEventListener("keydown", e => {
  if(e.key !== "Escape") return;
  const open = [...document.querySelectorAll(".dd-menu")].find(m => !m.hidden);
  if(open){ const b = document.querySelector(`[aria-controls="${open.id}"]`); closeMenus(); if(b) b.focus(); }
});

// ---------- data loop ----------
async function refresh(){
  try{
    S = await (await fetch("/api/state")).json();
    if(!$("scenario").options.length){
      $("scenario").innerHTML = S.scenarios.map(s=>`<option value="${s.name}">${esc(s.title)}</option>`).join("");
      if(S.scenarios.some(x=>x.name===S.scenario)) $("scenario").value = S.scenario;
    }
    $("speed").value = String(S.speed);
    render();
  }catch(e){ console.error(e); }
}

function resetLocal(){ lastNegKey=null; pinned=null; play={seq:0,shown:0,total:0}; lastSeq=0; }
$("start").onclick = async()=>{ closeMenus(); await post("/api/reset",{scenario:$("scenario").value}); resetLocal(); if(location.hash!=="#/live") location.hash = "#/live"; refresh(); };
$("blank").onclick = async()=>{ closeMenus(); await post("/api/reset",{}); resetLocal(); refresh(); };
$("speed").onchange = e=>post("/api/control",{speed:+e.target.value});
$("pause").onclick = ()=>post("/api/control",{paused:!S.paused}).then(refresh);
$("closing").onclick = async()=>{
  closeMenus();
  if(!Object.keys(S.cameras||{}).length){ toast("No camera connected. Start camera.py first.", "warn"); return; }
  await post("/api/closing", {}); toast("Closing time: cameras are reporting leftover food", "info");
};
document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=async()=>{ closeMenus(); await post("/api/event/"+b.dataset.ev); refresh(); });
$("feed-filter").onchange = ()=>{ if(S) drawFeed(); };
$("log-filter").onchange = ()=>{ if(S) drawLog(); };
$("debate-more").addEventListener("toggle", ()=>{ if(S && view==="live") drawNegotiation(); });

// ---------- evidence page ----------
let evidence = null, evLoading = false;
async function loadEvidence(force){
  if(evLoading || (evidence && !force)) return;
  evLoading = true; setHTML("takeaway", ""); setHTML("cmp", "<p class='muted'>Running 50 random scenarios… this takes a few seconds.</p>");
  try{ evidence = await (await fetch("/api/compare?n=50")).json(); }
  catch(e){ evidence = null; evLoading = false; setHTML("cmp", "<p class='muted'>Couldn't load the comparison. Check the server and try again.</p>"); return; }
  evLoading = false; drawEvidence(evidence);
}
$("rerun").onclick = ()=>loadEvidence(true);
// Together vs alone: the challenge's question, "can agents decide better together than individually?"
function soloSection(R){
  const T = R.totals; if(!T["solo:Speed"]) return "";
  const P = [["solo:Speed","Speed alone","var(--speed)"],["solo:Cost","Cost alone","var(--cost)"],["solo:Need","Need alone","var(--need)"],["agents","Team (negotiating)","var(--brand)"]];
  const bestSolo = Math.min(...P.slice(0,3).map(([p]) => T[p].servings_lost));
  const fedSolo = Math.max(...P.slice(0,3).map(([p]) => T[p].shelters_fed));
  const pct = Math.round(100 * (1 - T.agents.servings_lost / (bestSolo || 1)));
  const num = v => Math.round(v).toLocaleString(), usd = v => "$" + Math.round(v).toLocaleString();
  const metric = (label, key, fmt, better) => {
    const max = Math.max(...P.map(([p]) => T[p][key])) || 1;
    return `<div class="cbar"><div class="cbar-label">${label} <span class="muted">(${better})</span></div>` + P.map(([p, nm, c]) =>
      `<div class="cbar-row"><span class="cbar-who">${nm}</span><div class="cbar-track"><i style="width:${Math.max(2, 100 * T[p][key] / max)}%;background:${c}" title="${nm}: ${fmt(T[p][key])}"></i></div><span class="cbar-val">${fmt(T[p][key])}</span></div>`).join("") + `</div>`;
  };
  const v = R.vs_solo || {};
  return `<h2 class="sec-h">Together vs each agent alone</h2>
    <p class="helper">Same ${R.n} random scenarios. "Alone" means one agent decides by itself with the same safety rules and no negotiation. Each one misses what it doesn't care about; together they cover each other.</p>
    <div class="hero-row">
      <div class="hero-stat"><b>${pct}%</b><span>less food lost than the best single agent</span></div>
      <div class="hero-stat"><b>${v.team_best_or_tied ?? "–"} of ${R.n}</b><span>runs where the team lost the least food (or tied)</span></div>
      <div class="hero-stat"><b>${num(T.agents.shelters_fed)}</b><span>shelters fed, vs ${num(fedSolo)} for the best agent alone</span></div>
      <div class="hero-stat"><b>${usd(T["solo:Cost"].money_spent)}</b><span>Cost alone is cheapest, but loses ${num(T["solo:Cost"].servings_lost)} servings</span></div>
    </div>
    <div class="cbars four">
      ${metric("Servings lost", "servings_lost", num, "lower is better")}
      ${metric("Meals delivered safely", "meals_delivered_safely", num, "higher is better")}
      ${metric("Shelters fed", "shelters_fed", num, "higher is better")}
      ${metric("Paid-driver cost", "money_spent", usd, "lower is better")}
    </div>`;
}
function drawEvidence(r){
  const b = r.random.totals.baseline, a = r.random.totals.agents, w = r.random.wins;
  const rel = (x,y)=> y ? Math.round(100*Math.abs(1-x/y)) : 0;
  const dir = (x,y,lo,hi)=> x<=y ? lo : hi;
  // three metrics, three scales: small multiples, never one shared axis
  const metric = (label, key, fmt, better) => {
    const max = Math.max(b[key], a[key]) || 1;
    const bar = (who, v, cls) => `<div class="cbar-row"><span class="cbar-who">${who}</span>
      <div class="cbar-track"><i class="${cls}" style="width:${Math.max(2, 100*v/max)}%" title="${who}: ${fmt(v)}"></i></div>
      <span class="cbar-val">${fmt(v)}</span></div>`;
    return `<div class="cbar"><div class="cbar-label">${label} <span class="muted">(${better})</span></div>
      ${bar("Baseline", b[key], "base")}${bar("Agents", a[key], "agt")}</div>`;
  };
  const num = v => v.toLocaleString(), usd = v => "$" + Math.round(v).toLocaleString();
  const sc = r.scripted, P = sc.order;  // the server sorts JSON keys, so the column order comes separately
  const M = [["meals_delivered_safely","Meals delivered safely",1],["servings_lost","Servings lost",-1],["money_spent","Money spent ($)",-1],
             ["shelters_fed","Shelters fed",1],["avg_spare_minutes","Avg minutes to spare (perishable)",1],["human_escalations","Asked a human",0]];
  const outcomeLine = o => Object.entries(o||{}).map(([k,v])=>`${k.replace(/_/g," ")} ${v}`).join(", ") || "none";
  const block = (title,res)=>`<tr class="sect"><th colspan="${P.length+1}">${esc(title)}</th></tr>` + M.map(([k,l,d])=>{
    const vals = P.map(p=>res[p][k]); const best = d>0 ? Math.max(...vals) : Math.min(...vals);
    return `<tr><td>${l}</td>${P.map(p=>`<td class="${d&&res[p][k]===best?"better":""}">${res[p][k]}</td>`).join("")}</tr>`;}).join("")
    + `<tr><td colspan="${P.length+1}" class="muted small note">Team outcomes: ${outcomeLine(res.agents.outcomes)}</td></tr>`;
  const lostWord = dir(a.servings_lost, b.servings_lost, "less", "more"), mealWord = dir(b.meals_delivered_safely, a.meals_delivered_safely, "more", "fewer"), costWord = dir(a.money_spent, b.money_spent, "less", "more");
  setHTML("cmp", `

    <div class="hero-row">
      <div class="hero-stat"><b>${rel(a.servings_lost, b.servings_lost)}%</b><span>${lostWord} food lost</span></div>
      <div class="hero-stat"><b>${rel(a.meals_delivered_safely, b.meals_delivered_safely)}%</b><span>${mealWord} meals delivered</span></div>
      <div class="hero-stat"><b>${rel(a.money_spent, b.money_spent)}%</b><span>${costWord} driver cost</span></div>
      <div class="hero-stat"><b>${w.more_food_lost} of ${r.random.n}</b><span>runs where agents lost more food</span></div>
    </div>
    <p class="muted small">Runs include 3–6 donations, driver no-shows, full shelters and new pantries.</p>
    <div class="dlg-key" aria-hidden="true"><span><i style="background:#64748b"></i>Baseline (nearest shelter)</span><span><i style="background:var(--brand)"></i>Agents together</span></div>
    <div class="cbars">
      ${metric("Meals delivered safely","meals_delivered_safely",num,"higher is better")}
      ${metric("Servings lost","servings_lost",num,"lower is better")}
      ${metric("Money spent on paid drivers","money_spent",usd,"lower is better")}
    </div>
    ${soloSection(r.random)}
    <h2 class="sec-h">The ${sc.rows.length} scripted demo scenarios</h2>
    <p class="helper">Speed / Cost / Need alone: same safety rules, but one agent decides with no negotiation. Green = best in the row.</p>
    <div class="cmp-scroll"><table><thead><tr><th scope="col">Metric</th>${P.map(p=>`<th scope="col">${esc(sc.policies[p])}</th>`).join("")}</tr></thead><tbody>
      ${block("All scenarios",sc.totals)}
      ${sc.rows.map(x=>block(x.title,x.results)).join("")}</tbody></table></div>`);
}

route(); refresh(); setInterval(refresh, 1000);

$("voice").onclick = ()=>{
  voiceOn = !voiceOn; ringCtx();
  const b = $("voice"); b.textContent = voiceOn ? "Voices on" : "Voices off";
  b.classList.toggle("primary", voiceOn); b.setAttribute("aria-pressed", voiceOn);
  if(voiceOn){ toast(S && S.mode.voice==="elevenlabs" ? "Voices on (ElevenLabs). Replaying the debate." : "Voices on (browser voice; add an ElevenLabs key for real voices)", "info"); lastSpoken = null; if(S) replay(); }
  else { endSpeak(); if(window.speechSynthesis) speechSynthesis.cancel(); Object.values(audioCache).forEach(a=>a.pause()); }
};

// ---------- Agent network: a live diagram of who is talking to whom for the current donation ----------
const W_NS = "http://www.w3.org/2000/svg";
const wireSeen = new Set();
const short = (t, k=22) => { t = String(t||""); return t.length > k ? t.slice(0, k-1) + "…" : t; };
function wireCurve(x1, y1, x2, y2, bend){ const mx = (x1+x2)/2, my = (y1+y2)/2 + (bend||0); return `M${x1},${y1} Q${mx},${my} ${x2},${y2}`; }
function drawWire(){
  const svg = $("wire"); if(!svg || !S) return;
  const n = currentNeg();
  const stat = $("wire-stat");
  if(!n){ svg.innerHTML = `<text x="500" y="150" text-anchor="middle" class="w-empty">Waiting for a donation. Run a scenario under Demo controls.</text>`; setHTML("wire-log", ""); stat.className = "wire-stat"; stat.innerHTML = `<i class="dot"></i>idle`; return; }
  const all = (S.network||[]).filter(m => m.donation === n.donation);
  let start = 0; all.forEach((m,i) => { if(m.kind === "announce") start = i; });
  const msgs = all.slice(start);
  const d = S.donations.find(x => x.id === n.donation) || {};
  // the debate, revealed in step with the playback
  const lines = n.rounds.flatMap(r => r.messages.map(m => ({...m, round:r.round})));
  const shown = play.seq === n.seq ? play.shown : lines.length;
  const playing = shown < lines.length;
  const rIdx = playing ? Math.max(0, (shown ? lines[shown-1].round : 1) - 1) : n.rounds.length - 1;
  const R = n.rounds[rIdx];

  // nodes
  const replies = {}; msgs.filter(m => ["accept","counter","decline"].includes(m.kind)).forEach(m => replies[m.from] = m);
  const bids = {}; msgs.filter(m => m.kind === "bid").forEach(m => bids[m.from] = m);
  const shelterNames = Object.keys(replies).concat((S.nonprofits||[]).map(x => x.name).filter(nm => !replies[nm])).slice(0, 7);
  const driverNames = Object.keys(bids).concat((S.drivers||[]).map(x => x.name).filter(nm => !bids[nm])).slice(0, 6);
  const spread = (k, i, top=34, bot=266) => k <= 1 ? 150 : top + (bot - top) * i / (k - 1);
  const pos = {};
  pos.biz = {x:70, y:150};
  shelterNames.forEach((nm, i) => pos["s:"+nm] = {x:330, y:spread(shelterNames.length, i)});
  driverNames.forEach((nm, i) => pos["d:"+nm] = {x:600, y:spread(driverNames.length, i, 50, 250)});
  pos.Speed = {x:850, y:70}; pos.Cost = {x:850, y:150}; pos.Need = {x:850, y:230}; pos.hub = {x:790, y:150};
  const chosenNp = n.plan && n.plan.np_name, chosenDr = n.plan && n.plan.driver_name;
  const done = !playing;

  const edges = [];
  const add = (key, a, b, cls, bend) => { if(pos[a] && pos[b]) edges.push({key, a, b, cls, bend}); };
  if(msgs.some(m => m.kind === "announce")) shelterNames.forEach(nm => add("ann:"+nm, "biz", "s:"+nm, "e-ann", 0));
  Object.values(replies).forEach(m => add("rep:"+m.from+m.kind, "s:"+m.from, "biz", "e-"+m.kind, 26));
  Object.values(bids).forEach(m => add("bid:"+m.from, "d:"+m.from, "hub", "e-bid", 0));
  // the debate: an objection draws an arc from the objector to whoever proposed that plan
  if(R && shown){
    const said = new Set(lines.slice(0, shown).filter(l => l.round === R.round).map(l => l.agent));
    ["Speed","Cost","Need"].forEach(a => {
      if(!said.has(a)) return;
      Object.entries(R.votes||{}).forEach(([pid, v]) => {
        if(!v[a] || v[a].accept) return;
        ["Speed","Cost","Need"].filter(b => b !== a && R.proposals[b] === pid).forEach(b => add(`obj:${R.round}:${a}>${b}`, a, b, "e-obj " + a, a === "Cost" ? 60 : -60));
      });
    });
  }
  if(done && chosenNp && pos["s:"+chosenNp]) add("award:"+n.seq, "hub", "s:"+chosenNp, "e-award", -70);

  let html = `<g class="w-cols"><text x="70" y="16">Business</text><text x="330" y="16">Shelter agents</text><text x="600" y="16">Driver agents</text><text x="850" y="16">Coordinators</text></g>`;
  html += edges.map(e => { const A = pos[e.a], B = pos[e.b], isNew = !wireSeen.has(n.seq + e.key);
    return `<path class="edge ${e.cls}${isNew ? " new" : ""}" d="${wireCurve(A.x, A.y, B.x, B.y, e.bend)}"/>`; }).join("");
  const node = (k, label, sub, cls) => { const P = pos[k]; return `<g class="node ${cls||""}" transform="translate(${P.x},${P.y})"><circle r="9"/><text x="15" y="-1">${esc(short(label))}</text>${sub ? `<text x="15" y="12" class="sub">${esc(sub)}</text>` : ""}</g>`; };
  html += node("biz", d.business_name || "Business", `${d.food ? d.food.servings + " servings" : ""}`, "biz");
  shelterNames.forEach(nm => { const r = replies[nm];
    const sub = r ? (r.kind === "accept" ? "yes" : r.kind === "counter" ? (r.text.match(/take (\d+)/) ? "takes " + r.text.match(/take (\d+)/)[1] : "counter") : "no") : "";
    html += node("s:"+nm, nm, done && nm === chosenNp ? "chosen" : sub, (r ? r.kind : "quiet") + (done && nm === chosenNp ? " chosen" : "")); });
  driverNames.forEach(nm => { const b = bids[nm]; const price = b ? ((b.text.match(/\$\d+(\.\d+)?|[Ff]ree/) || ["bid"])[0]).toLowerCase() : "";
    html += node("d:"+nm, nm, done && nm === chosenDr ? "chosen" : price, (b ? "bid" : "quiet") + (done && nm === chosenDr ? " chosen" : "")); });
  html += `<g class="node hub" transform="translate(790,150)"><circle r="5"/></g>`;
  ["Speed","Cost","Need"].forEach(a => { const pid = R && R.proposals[a]; const vetoed = R && Object.values(R.votes||{}).some(v => v[a] && !v[a].accept && /^Veto/.test(v[a].reason));
    const wants = pid ? "wants " + short((S.nonprofits.find(x => x.id === pid.split("|")[0]) || {}).name || "", 16) : "";
    html += node(a, a, vetoed ? "veto" : wants, "coord " + a + (vetoed ? " vetoed" : "")); });
  if(done){ const o = (OUTCOME[n.outcome] || {}).t || n.outcome; html += `<text x="790" y="290" text-anchor="middle" class="w-outcome ${n.outcome}">${esc(o)}</text>`; }
  if(svg._h !== html){ svg._h = html; svg.innerHTML = html; edges.forEach(e => wireSeen.add(n.seq + e.key)); }

  // the message log: network messages, then the debate lines as they're revealed
  const log = msgs.map(m => ({t:m.time, from:m.from, to:m.to === "network" ? "all shelters" : m.to, kind:m.kind, text:m.text}))
    .concat(lines.slice(0, shown).map(l => ({t:n.time, from:l.agent === "News" ? "World" : l.agent, to:"team", kind:l.type === "objection" ? (/Veto/.test(l.text) ? "veto" : "object") : l.type === "news" ? "news" : l.type === "revise" ? "revise" : "propose", text:l.text.replace(/^R\d+ · /, "")})));
  if(done && n.plan) log.push({t:n.time, from:"Team", to:n.plan.np_name, kind:"decide", text:((OUTCOME[n.outcome]||{}).t || n.outcome) + ". " + n.plan.np_name + " via " + n.plan.driver_name});
  setHTML("wire-log", log.slice(-40).map(l => `<li class="k-${esc(l.kind)}"><span class="t">${esc(l.t||"")}</span><span class="r">${esc(short(l.from, 18))} → ${esc(short(l.to, 18))}</span><span class="kd">${esc(l.kind)}</span><span class="tx">${esc(l.text)}</span></li>`).join(""));
  const wl = $("wire-log"); wl.scrollTop = wl.scrollHeight;
  stat.className = "wire-stat" + (playing || S.busy ? " live" : "");
  stat.innerHTML = `<i class="dot"></i>${playing || S.busy ? "live" : "done"} · ${esc(n.donation)}`;
}

// light / dark (light can read better on a projector in a bright room)
(function(){
  const b = $("theme"); if(!b) return;
  const sync = () => { b.textContent = document.documentElement.dataset.theme === "dark" ? "Light mode" : "Dark mode"; };
  b.onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; try{ localStorage.setItem("uplink_theme", t); }catch(e){} sync(); };
  sync();
})();

// ---------- Phone line: after the agents decide, the dispatcher agent calls the shelter agent ----------
// Both sides speak with ElevenLabs voices (Dispatch and Shelter); a staff member's spoken answer on the
// shelter phone shows up here too, transcribed by ElevenLabs Scribe.
let callFor = null, call = null, actx = null;
function ringCtx(){ try{ actx = actx || new (window.AudioContext || window.webkitAudioContext)(); actx.resume(); }catch(e){} }
function ringTone(){
  if(!voiceOn || !actx) return;
  [0, .5].forEach(t => [440, 480].forEach(f => { const o = actx.createOscillator(), g = actx.createGain(); o.frequency.value = f;
    g.gain.setValueAtTime(.06, actx.currentTime + t); g.gain.setValueAtTime(0, actx.currentTime + t + .38);
    o.connect(g).connect(actx.destination); o.start(actx.currentTime + t); o.stop(actx.currentTime + t + .4); }));
}
const wait = ms => new Promise(r => setTimeout(r, ms));
function callSay(who, text){
  return new Promise(resolve => {
    const done = () => { clearTimeout(t); resolve(); };
    const t = setTimeout(resolve, Math.max(2500, text.length * 75));   // never hang the call
    if(!voiceOn){ clearTimeout(t); setTimeout(resolve, Math.max(1600, text.length * 45)); return; }
    if(S && S.mode && S.mode.voice === "elevenlabs"){
      const a = audioFor(who, text); a.currentTime = 0; a.onended = done;
      a.onerror = () => { if(window.speechSynthesis){ const u = new SpeechSynthesisUtterance(text); u.pitch = PITCH[who] ?? 1; u.onend = done; speechSynthesis.speak(u); } else done(); };
      a.play().catch(a.onerror);
    } else if(window.speechSynthesis){ const u = new SpeechSynthesisUtterance(text); u.pitch = PITCH[who] ?? 1; u.rate = 1.05; u.onend = done; speechSynthesis.speak(u); }
    else done();
  });
}
function callScript(n){
  const d = S.donations.find(x => x.id === n.donation) || {food:{items:[], servings:0}};
  const np = n.plan.np_name, drv = String(n.plan.driver_name || "").split(" (")[0];
  const reply = (S.network || []).filter(m => m.donation === n.donation && m.from === np && ["accept","counter","decline"].includes(m.kind)).pop();
  const items = (d.food.items || []).join(", ");
  const ask = `Hi ${np}, this is the Uplink dispatcher. ${d.business_name || "A business"} has ${d.food.servings} servings of ${items}${d.food.needs_cold ? ", and it has to stay cold" : ""}. ${drv} can bring it by ${n.plan.arrive_hhmm}. Can you take it?`;
  const ans = reply ? reply.text : "Yes, please send it over.";
  const close = !reply || reply.kind === "accept" ? `Great. ${drv} is on the way. Thank you!` : reply.kind === "counter" ? "Got it. We'll send you that much and find a home for the rest." : "Understood. We'll try another shelter.";
  return {np, lines:[{who:"Dispatch", side:"a", name:"Uplink dispatcher", text:ask}, {who:"Shelter", side:"b", name:np, text:ans}, {who:"Dispatch", side:"a", name:"Uplink dispatcher", text:close}]};
}
async function startCall(n){
  const sc = callScript(n);
  const me = call = {seq:n.seq, donation:n.donation, np:sc.np, phase:"ringing", said:[], talking:null, t0:Date.now(), voiced:[]};
  drawCall();
  for(let i = 0; i < 40 && speaking; i++) await wait(250);   // let the spoken outcome finish first
  ringTone(); await wait(1300); ringTone(); await wait(1100);
  if(call !== me) return;
  me.phase = "talk"; me.t0 = Date.now();
  for(const ln of sc.lines){
    if(call !== me) return;
    me.talking = ln.side; me.said.push(ln); drawCall();
    await callSay(ln.who, ln.text);
    me.talking = null; drawCall(); await wait(350);
  }
  me.phase = "ended"; me.secs = Math.round((Date.now() - me.t0) / 1000); drawCall();
}
const WAVE = "<i></i>".repeat(14);
function drawCall(){
  const card = $("call-card"); if(!card) return;
  if(!call){ setHTML("call-card", `<p class="call-idle">No call yet. When the agents choose a shelter, the dispatcher agent calls it here.</p>`); setHTML("call-tx", ""); return; }
  // a staff member who answered on the shelter phone by voice (ElevenLabs Scribe transcribed it)
  const human = (S && S.feed || []).filter(f => f.donation === call.donation && /^\(by voice\)/.test(f.text));
  const secs = call.phase === "ended" ? call.secs : Math.round((Date.now() - call.t0) / 1000);
  const state = call.phase === "ringing" ? "Ringing…" : call.phase === "talk" ? `On the call · ${Math.floor(secs/60)}:${String(secs%60).padStart(2,"0")}` : `Call ended · ${Math.floor(secs/60)}:${String(secs%60).padStart(2,"0")}`;
  const side = (k, name, role, letter) => `<div class="caller ${k}${call.talking === k ? " talking" : ""}"><span class="av">${esc(letter)}</span><b>${esc(name)}</b><small>${esc(role)}</small><div class="wave" aria-hidden="true">${WAVE}</div></div>`;
  setHTML("call-card", `${side("a", "Uplink dispatcher", "agent · ElevenLabs voice", "U")}
    <div class="line ${call.phase}"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg><span>${esc(state)}</span></div>
    ${side("b", call.np, human.length ? "shelter staff · answered by voice" : "shelter agent · ElevenLabs voice", (call.np || "S").charAt(0))}`);
  setHTML("call-tx", call.said.map(l => `<li class="${l.side}"><b>${esc(l.name)}</b><span>${esc(l.text)}</span><small>${l.who === "Dispatch" ? "spoken with ElevenLabs (dispatcher voice)" : "spoken with ElevenLabs (shelter voice)"}</small></li>`).join("")
    + human.map(f => `<li class="b human"><b>${esc(f.agent)} staff</b><span>${esc(f.text.replace(/^\(by voice\)\s*/, ""))}</span><small>said out loud on the shelter phone · transcribed by ElevenLabs Scribe</small></li>`).join(""));
  const tx = $("call-tx"); tx.scrollTop = tx.scrollHeight;
}
setInterval(() => { if(call && call.phase === "talk") drawCall(); }, 1000);

// status badge: say plainly which AI is doing what
function modeText(m){
  const who = (prov, model) => prov === "anthropic" ? `Claude${model ? " (" + model.replace(/^claude-/, "") + ")" : ""}` : prov === "openai" ? (model || "open model") : "demo";
  const agents = m.agents === "llm" ? who(m.vision === "anthropic" ? "anthropic" : "openai", m.agents_model) : "rules";
  return `Agents: ${agents} · Vision: ${who(m.vision, m.vision_model)} · Voice: ${m.voice === "elevenlabs" ? "ElevenLabs" : "browser"}`;
}

