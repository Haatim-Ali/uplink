const AGENTS = ["Speed","Cost","Need"];
const GOALS = {Speed:"Fast, reliable, big safety margin", Cost:"Spend as little as possible", Need:"Feed whoever needs it most"};
const COLORS = {Speed:"var(--speed)",Cost:"var(--cost)",Need:"var(--need)"};
const ICON = {Speed:"⚡",Cost:"$",Need:"♥"};   // every agent color is paired with an icon and its name
const OUTCOME = {
  consensus:{ic:"✓",t:"Consensus: all 3 agents agree",d:"Every agent accepted the same plan, so it goes ahead."},
  majority:{ic:"⚖",t:"Majority decision, dissent kept on record",d:"Two agents accepted and none vetoed. The objecting agent's reason is saved so the trade-off stays visible."},
  urgent:{ic:"⏱",t:"Time is short: acting on the best-supported plan",d:"The food is close to unsafe, so the plan with the most support and no veto goes now."},
  irreconcilable:{ic:"👤",t:"Irreconcilable: asking a human",d:"After 3 rounds no plan has majority support. The agents refuse to force a deal and ask a person."},
  unacceptable:{ic:"⛔",t:"Unacceptable compromise: asking a human",d:"The majority's plan crosses an agent's red line (a veto), so it is not allowed. A person decides."},
  over_budget:{ic:"$",t:"Over budget: asking a human to approve",d:"The winning plan costs more than the $25 limit, so a person must approve it."},
  insufficient_evidence:{ic:"?",t:"Not enough evidence: asking the business",d:"The decision hinges on a fact nobody has confirmed (allergens), so the agents ask instead of guessing."},
  human_timeout:{ic:"⏱",t:"No one answered: fallback rule used",d:"Nobody replied before the food ran short, so the agents' top-ranked option was sent. This is labeled in the feed."},
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
const PITCH = {Speed:1.25, Cost:0.8, Need:1.05, Dispatch:1};
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
function replay(){ const n = pinned ? (S.negotiations||[]).find(h=>h.seq===pinned) : S.negotiation; if(!n) return;
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
    if(f.agent==="World" && /full tonight/.test(t)) toast("🚫 " + t.replace(/"/g,""), "bad");
    else if(f.agent==="World" && /cancelled/.test(t)) toast("⚠ " + t.split(".")[0], "bad");
    else if(f.agent==="World" && /delivered to/.test(t) && !/unsafe/.test(t)) toast("✓ " + t.split(".")[0], "good");
    else if(f.agent==="World" && /(unsafe|lost|Turned away)/.test(t)) toast("✗ " + t.split(".")[0], "bad");
    else if(f.agent==="Directory") toast("＋ " + t.split("(")[0], "info");
    else if(f.agent==="Adapt") toast("↑ " + t, "info");
    else if(f.agent==="Human" && /asking a coordinator|no safe plan/.test(t)) toast("👤 Coordinator needed for " + (f.donation||""), "warn");
    else if(f.agent==="Contact" && /(accepted|declined|No answer)/.test(t)) toast("📱 " + t.split(".")[0], /accepted/.test(t) ? "good" : "warn");
  });
  lastSeq = max;
}
async function post(url, body){ const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}); const j = await r.json().catch(()=>({})); if(!r.ok) toast(j.error||"Request failed"); return j; }

// ---------- map ----------
let map=null, layers={}, mapTried=false;
function ensureMap(){
  if(mapTried){ if(map) setTimeout(()=>map.invalidateSize(), 0); return; }
  mapTried = true;
  try{
    map = L.map("map",{zoomControl:true}).setView([37.377,-121.97],13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"© OpenStreetMap"}).addTo(map);
    layers = {np:L.layerGroup().addTo(map), biz:L.layerGroup().addTo(map), drv:L.layerGroup().addTo(map), route:L.layerGroup().addTo(map)};
  }catch(e){ map = null; $("map").innerHTML = "<p class='empty' style='padding:12px'>The map needs internet for its tiles. Everything else still works.</p>"; }
}

const markers = {};   // id -> Leaflet marker, created once and updated in place
function upsert(id, make, update){ if(!markers[id]) markers[id]=make(); update(markers[id]); }
function npColor(n){ return n.full ? "#b91c1c" : n.id==="maple-pantry" ? "#0f766e" : "#15803d"; }
function driverIcon(dr){
  const color = dr.status==="off" ? "#94a3b8" : dr.type==="paid" ? "#c2410c" : dr.type==="volunteer" ? "#1d4ed8" : "#6d28d9";
  const shape = dr.type==="paid" ? "paid" : dr.type==="volunteer" ? "" : "van";   // shape repeats the type, not just color
  return L.divIcon({className:"", iconSize:[27,27], html:`<div class="drv ${shape} ${dr.status==="busy"?"busy":""}" style="background:${color};opacity:${dr.status==="off"?.8:dr.status==="busy"?1:.85}">${esc(dr.name[0])}</div>`});
}
function drawMap(){
  if(!map) return;
  const live = new Set();
  S.nonprofits.forEach(n=>{
    const id="np:"+n.id; live.add(id);
    upsert(id, ()=>L.circleMarker([n.lat,n.lng],{radius:9,weight:2,fillOpacity:.85}).bindTooltip("").addTo(layers.np), m=>{
      m.setStyle({color:npColor(n), fillColor:npColor(n), dashArray:n.full?"3 3":null, weight:n.full?4:2});
      m.setTooltipContent(`<b>${esc(n.name)}</b><br>${n.has_fridge?"fridge":"no fridge"} · open until ${n.open_until}<br>${n.received}/${n.capacity_servings} servings · last fed ${n.last_donation_days}d ago${n.full?"<br><b>FULL</b>":""}`);
    });
  });
  S.businesses.forEach(b=>{
    const id="biz:"+b.id; live.add(id);
    upsert(id, ()=>L.marker([b.lat,b.lng],{icon:L.divIcon({className:"",html:'<div class="biz"></div>'})}).bindTooltip(esc(b.name)).addTo(layers.biz), ()=>{});
  });
  S.drivers.forEach(dr=>{
    const id="dr:"+dr.id; live.add(id);
    upsert(id, ()=>L.marker([dr.lat,dr.lng],{icon:driverIcon(dr)}).bindTooltip("").addTo(layers.drv), m=>{
      m.setLatLng([dr.lat,dr.lng]);
      const key = dr.status+dr.type; if(m._key!==key){ m._key=key; m.setIcon(driverIcon(dr)); }
      m.setTooltipContent(`${esc(dr.name)} · ${esc(dr.type)} · ${dr.status} · ${Math.round(dr.reliability*100)}% reliable`);
    });
  });
  for(const id in markers){ if(!live.has(id)){ markers[id].remove(); delete markers[id]; } }   // e.g. after a reset
  // zoom to fit every shelter and business whenever that set changes (e.g. city mode)
  const fitKey = S.nonprofits.length + "|" + S.businesses.length;
  if(map._fitKey !== fitKey){
    map._fitKey = fitKey;
    map.fitBounds(L.latLngBounds([...S.nonprofits, ...S.businesses].map(p=>[p.lat,p.lng])), {padding:[24,24]});
  }
  layers.route.clearLayers();   // routes change shape every tick, so these are redrawn
  S.donations.filter(d=>d.status==="en_route" && d.plan).forEach(d=>{
    const dr = S.drivers.find(x=>x.id===d.plan.driver);
    const pts = d.picked ? [[dr.lat,dr.lng],[d.dest.lat,d.dest.lng]] : [[dr.lat,dr.lng],[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]];
    L.polyline(pts,{color:"#1d4ed8",weight:3,dashArray:"6 6"}).addTo(layers.route);
  });
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
    setHTML("cur-don", `<div class="empty-state"><div class="es-icon" aria-hidden="true">🍽</div><p><b>No donation in progress</b></p><p class="muted">Choose a scenario under Demo controls and run it, or send a real donation from the Business page.</p><button class="btn primary sm" type="button" onclick="document.getElementById('start').click()">▶ Run selected scenario</button></div>`);
    return;
  }
  const live = !["delivered","spoiled","expired"].includes(d.status);
  const where = d.plan ? `${esc(d.plan.np_name)} <span class="muted">via ${esc(d.plan.driver_name)}</span>` : `<span class="muted">Destination not chosen yet</span>`;
  const pct = Math.max(0, Math.min(100, Math.round(100 * d.minutes_left / (d.food.safe_minutes || 120))));
  setHTML("cur-don", `<div class="cd">
    <div class="cd-top"><span class="card-title">Current donation · ${esc(d.id)}</span><span class="st ${d.status}">${STATUS[d.status] || esc(d.status.replace("_"," "))}</span></div>
    <div class="cd-food">${d.food.servings} servings of ${esc(d.food.items.join(", "))}</div>
    <div class="cd-route">${esc(d.business_name)} → ${where}</div>
    <div class="cd-meta"><span class="pill outline">${esc(d.food.category)}</span>${d.food.needs_cold?'<span class="pill info">❄ Keep cold</span>':""}${d.food.allergens.length?`<span class="pill warn">⚠ ${esc(d.food.allergens.join(", "))}</span>`:""}</div>
    ${live?`<div class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left<30?"⚠ ":""}${d.minutes_left} min until unsafe (${esc(d.safe_until)})</div><div class="tbar" aria-hidden="true"><i style="width:${pct}%"></i></div>`:""}</div>`);
}

function pin(seq){ pinned = (pinned===seq ? null : seq); lastNegKey=null; drawNegotiation(); }
function drawNegotiation(){
  const hero = $("hero-panel");
  const hist = S.negotiations || [];
  const n = currentNeg();
  drawDonationCard(n);
  if(S.busy && !pinned){ hero.hidden = false; setHTML("neg", `<div class="status-banner debating" role="status"><span class="ic" aria-hidden="true">…</span><div><div class="t">Agents are deliberating…</div><div class="d">The simulated clock is paused until they finish.</div></div></div>`); return; }
  if(!n){ hero.hidden = true; return; }
  hero.hidden = false;
  const shownSeq = pinned || n.seq;
  const msgs = n.rounds.flatMap(r => r.messages.map(m => ({...m, round: r.round})));
  if(!pinned && n.seq !== play.seq && play.seq !== null && n.seq > play.seq){ play = {seq: n.seq, shown: 0, total: msgs.length}; }
  if(play.seq === null){ play = {seq: n.seq, shown: msgs.length, total: msgs.length}; }   // first load: no replay of old news
  const shown = play.seq === n.seq ? play.shown : msgs.length;
  const playing = shown < msgs.length;
  const key = n.seq + "|" + n.donation + "|" + n.rounds.length + "|" + n.outcome + "|" + (n.plan?n.plan.id:"");
  if(playing){ roundSel = Math.max(0, (shown ? msgs[shown-1].round : 1) - 1); lastNegKey = null; }
  else if(key!==lastNegKey){ roundSel = n.rounds.length-1; lastNegKey = key; }
  if(roundSel >= n.rounds.length) roundSel = n.rounds.length-1;

  // ---- summary (always visible): agents, what each wants, outcome in plain words ----
  const rs = playing ? roundSel : n.rounds.length-1, rr = n.rounds[rs];
  const cards = AGENTS.map(a=>{
    const pid = rr.proposals[a];
    return `<div class="agent ${a}"><div class="agent-top"><h3><span aria-hidden="true">${ICON[a]}</span><span class="a-name">${a}</span></h3><span class="wt" title="Vote weight. It grows when this agent's earlier warning about a driver turned out right.">vote ×${(n.weights||{})[a]??1}</span></div><div class="goal">${GOALS[a]}</div><div class="wants">Proposes: <b>${pid ? planName(pid) : "—"}</b></div></div>`;
  }).join("");
  const o = OUTCOME[n.outcome] || {ic:"•", t:(n.outcome||"Decision").replace(/_/g," "), d:""};
  const chosen = n.plan ? `<div class="pick">Decision: <b>${planName(n.plan.id)}</b></div>` : "";
  const dissent = (n.dissent||[]).map(x=>`<div class="dissent"><b>${esc(x.agent)} dissents:</b> ${esc(x.reason)}</div>`).join("");
  const banner = !playing
    ? `<div class="status-banner outcome ${OUTCOME[n.outcome]?n.outcome:"other"} pop" role="status"><span class="ic" aria-hidden="true">${o.ic}</span><div><div class="t">${o.t}</div><div class="d">${o.d}</div>${chosen}${dissent}</div></div>`
    : `<div class="status-banner debating" role="status"><span class="ic" aria-hidden="true">…</span><div><div class="t">Debating, round ${rr.round} of up to 3…</div><div class="d">Each agent proposes a plan, then votes on every plan on the table.</div></div></div>`;
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
      const txt = v.accept ? "✓ Accept" : veto ? "⛔ Veto" : "✗ Object";
      return `<td title="${esc(v.reason)}"><span class="vote ${v.accept?"yes":veto?"veto":"no"}">${txt}</span>
        <div class="score" title="${a}'s score for this plan: ${Math.round(sc*100)} of 100"><div class="bar"><i style="width:${Math.round(sc*100)}%;background:${COLORS[a]}"></i></div><em>${Math.round(sc*100)}</em></div></td>`;
    }).join("");
    return `<tr class="${win?"winner":""}"><td class="plan">${win?'<span class="pill ok chosen">★ Chosen</span><br>':""}${planName(pid)}</td>${cells}</tr>`;
  }).join("");
  const bubbles = msgs.slice(0, shown).map((m,i) => `<div class="bubble ${m.agent} ${m.type}${i===shown-1 && playing ? " new" : ""}${i===shown-1 && playing && m.type==="objection" ? " shake" : ""}">
      <span class="b-who">${ICON[m.agent]||""} ${esc(m.agent)}</span><span class="b-r">R${m.round}</span>${esc(m.text)}</div>`).join("");
  setHTML("debate-body", `
    <div class="debate" id="debate" role="log" aria-label="Debate transcript">${bubbles || '<span class="muted">The agents are about to speak…</span>'}</div>
    <div class="matrix-wrap"><table class="matrix"><caption class="sr-only">Votes by each agent on every plan, round ${r.round}</caption><thead><tr><th scope="col">Plans on the table (round ${r.round})</th>${AGENTS.map(a=>`<th scope="col" class="${a}">${ICON[a]} ${a}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="vote-key"><b>✓ Accept</b> the plan is good enough for this agent's goal. <b>✗ Object</b> it prefers another plan. <b>⛔ Veto</b> the plan crosses this agent's red line and is blocked. Bars show each agent's own score for the plan (0 to 100).</p>
    <div class="tools">${!playing?`<button class="replay" onclick="replay()">↻ Replay debate</button>`:""}${tally()}</div>`);
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
      <div class="opts">${d.options.map(o=>`<button class="opt" onclick="approve('${d.id}','${o.id}')"><b>${esc(o.np_name)}</b><span class="meta">via ${esc(o.driver_name)} · ${o.dur} min · $${o.cost.toFixed(2)}</span><span class="go">Approve this plan →</span></button>`).join("")}</div></div>`).join("")
  + asking.map(d=>`
    <div class="human ask" role="alert"><span class="h-tag">Question for the business</span>
      <div class="h-title">${esc(d.business_name)}: is ${esc(d.id)} free of ${esc(d.asked_about)}?</div>
      <div class="h-why">${esc(d.food.items.join(", "))}. There is not enough evidence to decide yet. If nobody answers, the agents act on what they know and treat unconfirmed allergens as present.</div>
      <div class="opts"><button class="opt" onclick="confirmInfo('${d.id}',true)"><b>Listed allergens only</b><span class="meta">${esc(d.food.allergens.join(", ")||"none listed")}</span><span class="go">Business confirms →</span></button>
      <button class="opt" onclick="confirmInfo('${d.id}',false)"><b>Can't say for sure</b><span class="meta">Allergens stay unconfirmed</span><span class="go">Business can't confirm →</span></button></div></div>`).join(""));
}
async function approve(d,p){ await post("/api/approve",{donation:d,plan:p}); refresh(); }
async function confirmInfo(id, sure){ const d = S.donations.find(x=>x.id===id); await post("/api/confirm",{donation:id, allergens: sure ? d.food.allergens : null}); refresh(); }

// ---------- agent network ----------
const KIND = {announce:"Announces", accept:"✓ Accept", counter:"↔ Counter-offer", decline:"✗ Decline", bid:"$ Bid", award:"★ Award", split:"⇄ Split", escalate:"👤 Ask a human"};
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
const STATUS = {awaiting_info:"? asking business", awaiting_human:"👤 asking human", awaiting_shelter:"📱 asking shelter", delivered:"✓ delivered", spoiled:"✗ spoiled", expired:"✗ expired", en_route:"→ en route"};
const groupOf = a => ["Speed","Cost","Need"].includes(a) ? "agents" : a==="Safety" ? "Safety" : ["Human","Contact"].includes(a) ? "humans" : "world";
function drawFeed(){
  const f = $("feed-filter").value;
  const rows = S.feed.slice().reverse().filter(x => f==="all" || groupOf(x.agent)===f);
  setHTML("feed", rows.map(f=>`<div><time>${esc(f.time)}</time><span class="who ${esc(f.agent)}">${ICON[f.agent]?ICON[f.agent]+" ":""}${esc(f.agent)}</span><span class="${f.type==="objection"?"objection":""}">${esc(f.text)}</span></div>`).join("") || "<div class='empty-state'><p class='muted'>Nothing here yet. Events appear as the agents work.</p></div>");
}
function drawLog(){
  const f = $("log-filter").value;
  const rows = S.decisions.slice().reverse().filter(x => f==="all" || x.verdict===f);
  setHTML("log", rows.map(x=>`<div><span class="v ${x.verdict}">${x.verdict==="allowed"?"✓ ALLOWED":"✕ BLOCKED"}</span><span class="tx"><b>${esc(x.donation)}</b> · ${esc(x.text)}</span></div>`).join("") || "<div class='empty-state'><p class='muted'>No safety decisions yet. Each blocked plan is listed here with its reason.</p></div>");
}
function drawDons(){
  setHTML("dons", S.donations.slice().reverse().map(d=>{
    const live = !["delivered","spoiled","expired"].includes(d.status);
    const where = d.plan ? `${esc(d.plan.np_name)} via ${esc(d.plan.driver_name)}` : "planning…";
    const pct = Math.max(0, Math.min(100, Math.round(100 * d.minutes_left / (d.food.safe_minutes || 120))));
    return `<div class="don"><div class="don-top"><b>${esc(d.id)}</b><span class="st ${d.status}">${STATUS[d.status] || esc(d.status.replace("_"," "))}</span></div>
      <div>${esc(d.food.items.join(", "))} · ${d.food.servings} servings</div>
      <div class="route">${esc(d.business_name)} → ${where}</div>
      ${live?`<div class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left<30?"⚠ ":""}${d.minutes_left} min until unsafe (${esc(d.safe_until)})</div><div class="tbar" aria-hidden="true"><i style="width:${pct}%"></i></div>`:""}</div>`;
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
  $("clock").textContent = S.now + (S.paused?" ⏸":"");
  $("mode").textContent = `${S.mode.agents} agents · ${S.mode.vision} vision · ${S.mode.voice||"browser"} voice`;
  $("pause").textContent = S.paused ? "▶ Resume" : "⏸ Pause";
  drawCamera();
  const pend = pendingList(), c = $("dec-count");
  c.hidden = !pend.length; c.textContent = pend.length;
  document.title = (pend.length ? `(${pend.length}) ` : "") + "Uplink · food rescue agents";
  if(prevPending !== null && pend.length > prevPending){
    c.classList.remove("pulse"); void c.offsetWidth; c.classList.add("pulse");
    if(pend.some(d=>d.status==="awaiting_info") && view!=="decisions") toast("❓ The agents have a question for a business", "warn");
  }
  prevPending = pend.length;
}

function drawLive(){
  const scn = (S.scenarios.find(x=>x.name===S.scenario)||{}).title;
  const run = $("sl-run");
  run.className = "pill " + (S.paused ? "warn" : "ok"); run.textContent = S.paused ? "⏸ Paused" : `● Running ${S.speed}×`;
  setHTML("sl-scn", scn ? esc(scn.split(":")[0]) : "No scenario running");
  setHTML("sl-extra", `${S.donations.length} donation${S.donations.length===1?"":"s"} · ${S.agents_online ? S.agents_online.shelters+" shelters · "+S.agents_online.drivers+" drivers" : ""}`);
  const pend = pendingList(), al = $("live-alert");
  al.hidden = !pend.length;
  setHTML(al, pend.length ? `<span aria-hidden="true">👤</span><span>${pend.length} decision${pend.length>1?"s":""} waiting for you (${pend.map(d=>esc(d.id)).join(", ")}). Open Decisions →</span>` : "");
  drawNegotiation(); drawMap();
}

// ---------- routing ----------
const VIEWS = ["live","decisions","activity","evidence","how"], TABS = ["network","feed","safety","donations"];
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
    if(sub==="network") drawNetwork(); else if(sub==="feed") drawFeed(); else if(sub==="safety") drawLog(); else drawDons();
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
  await post("/api/closing", {}); toast("🕘 Closing time: cameras are reporting leftover food", "info");
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
    <h2 class="sec-h">The ${sc.rows.length} scripted demo scenarios</h2>
    <p class="helper">Team vs nearest shelter vs each agent deciding alone. <b>Speed / Cost / Need alone</b> use the same safety rules as the team, but one agent decides by itself with no negotiation. Cells marked <b>★</b> (green) are best in the row.</p>
    <div class="cmp-scroll"><table><thead><tr><th scope="col">Metric</th>${P.map(p=>`<th scope="col">${esc(sc.policies[p])}</th>`).join("")}</tr></thead><tbody>
      ${block("All scenarios",sc.totals)}
      ${sc.rows.map(x=>block(x.title,x.results)).join("")}</tbody></table></div>`);
}

route(); refresh(); setInterval(refresh, 1000);

$("voice").onclick = ()=>{
  voiceOn = !voiceOn;
  const b = $("voice"); b.textContent = voiceOn ? "🔊 Voices on" : "🔈 Voices off";
  b.classList.toggle("primary", voiceOn); b.setAttribute("aria-pressed", voiceOn);
  if(voiceOn){ toast(S && S.mode.voice==="elevenlabs" ? "Voices on (ElevenLabs). Replaying the debate." : "Voices on (browser voice; add an ElevenLabs key for real voices)", "info"); lastSpoken = null; if(S) replay(); }
  else { endSpeak(); if(window.speechSynthesis) speechSynthesis.cancel(); Object.values(audioCache).forEach(a=>a.pause()); }
};
