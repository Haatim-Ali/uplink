const AGENTS = ["Speed","Cost","Need"];
const GOALS = {Speed:"Fast, reliable, big safety margin", Cost:"Spend as little as possible", Need:"Feed whoever needs it most"};
const COLORS = {Speed:"var(--speed)",Cost:"var(--cost)",Need:"var(--need)"};
let S = null, roundSel = null, lastNegKey = null, pinned = null;
// Debate playback: a new negotiation is revealed one message at a time, then the outcome lands.
const PLAY_MS = 900;
let play = {seq: null, shown: 0, total: 0};
setInterval(()=>{ if(voiceOn && speaking) return;   // with voices on, the next line waits for the current one
  if(play.seq !== null && play.shown < play.total){ play.shown++; if(S) drawNegotiation(); } }, PLAY_MS);

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
  while($("toasts").children.length > 4) $("toasts").firstChild.remove();
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
let map=null, layers={};
try{
  map = L.map("map",{zoomControl:true}).setView([37.377,-121.97],13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"© OpenStreetMap"}).addTo(map);
  layers = {np:L.layerGroup().addTo(map), biz:L.layerGroup().addTo(map), drv:L.layerGroup().addTo(map), route:L.layerGroup().addTo(map)};
}catch(e){ $("map").innerHTML = "<p class='empty' style='padding:12px'>Map needs internet for its tiles. Everything else still works.</p>"; }

const markers = {};   // id -> Leaflet marker, created once and updated in place
function upsert(id, make, update){ if(!markers[id]) markers[id]=make(); update(markers[id]); }
function npColor(n){ return n.full ? "#c23b3b" : n.id==="maple-pantry" ? "#13858a" : "#2f8f4e"; }
function driverIcon(dr){
  const color = dr.status==="off" ? "#999" : dr.type==="paid" ? "#d9622b" : dr.type==="volunteer" ? "#2563a8" : "#7a4fc9";
  return L.divIcon({className:"", iconSize:[26,26], html:`<div class="drv" style="background:${color};opacity:${dr.status==="busy"?1:.75}">${esc(dr.name[0])}</div>`});
}
function drawMap(){
  if(!map) return;
  const live = new Set();
  S.nonprofits.forEach(n=>{
    const id="np:"+n.id; live.add(id);
    upsert(id, ()=>L.circleMarker([n.lat,n.lng],{radius:9,weight:2,fillOpacity:.85}).bindTooltip("").addTo(layers.np), m=>{
      m.setStyle({color:npColor(n), fillColor:npColor(n)});
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
      m.setTooltipContent(`${esc(dr.name)} · ${dr.status} · ${Math.round(dr.reliability*100)}% reliable`);
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
    L.polyline(pts,{color:"#2563a8",weight:3,dashArray:"6 6"}).addTo(layers.route);
  });
}

// ---------- negotiation ----------
function pin(seq){ pinned = (pinned===seq ? null : seq); lastNegKey=null; drawNegotiation(); drawNetwork(); }
function drawNegotiation(){
  const hist = S.negotiations || [];
  const shownSeq = pinned || (S.negotiation && S.negotiation.seq);
  setHTML("history", hist.length > 1 ? `<span class="hist-label">Past negotiations:</span>` +
    hist.map(h=>`<button class="hb ${shownSeq===h.seq?"on":""}" onclick="pin(${h.seq})">${h.time} ${h.donation}</button>`).join("") +
    (pinned?`<button class="follow" onclick="pin(null)">follow live</button>`:"") : "");
  const n = pinned ? hist.find(h=>h.seq===pinned) : S.negotiation;
  if(S.busy && !pinned){ setHTML("rounds", ""); setHTML("neg", `<p><b>Agents are deliberating…</b> The clock is paused until they finish.</p>`); return; }
  if(!n){ return; }
  const msgs = n.rounds.flatMap(r => r.messages.map(m => ({...m, round: r.round})));
  if(!pinned && n.seq !== play.seq && play.seq !== null && n.seq > play.seq){ play = {seq: n.seq, shown: 0, total: msgs.length}; }
  if(play.seq === null){ play = {seq: n.seq, shown: msgs.length, total: msgs.length}; }   // first load: no replay of old news
  const shown = play.seq === n.seq ? play.shown : msgs.length;
  const playing = shown < msgs.length;
  const key = n.seq + "|" + n.donation + "|" + n.rounds.length + "|" + n.outcome + "|" + (n.plan?n.plan.id:"");
  if(playing){ roundSel = Math.max(0, (shown ? msgs[shown-1].round : 1) - 1); lastNegKey = null; }
  else if(key!==lastNegKey){ roundSel = n.rounds.length-1; lastNegKey = key; }
  setHTML("rounds", n.rounds.map((r,i)=>`<button class="${i===roundSel?"on":""}" onclick="roundSel=${i};drawNegotiation()">R${r.round}</button>`).join(" "));
  const r = n.rounds[roundSel];
  const planIds = Object.keys(r.votes);
  const nm = id => { const [np,dr,join] = id.split("|"); if(join) return `${(S.nonprofits.find(x=>x.id===np)||{}).name||np} <span class="muted">· combined trip with ${join.replace("join-","")}</span>`; const N = S.nonprofits.find(x=>x.id===np); const D = S.drivers.find(x=>x.id===dr); return `${N?N.name:np} <span class="muted">via ${D?D.name:dr}</span>`; };
  const cards = AGENTS.map(a=>{
    const pid = r.proposals[a];
    return `<div class="agent ${a}"><span class="w">vote ×${(n.weights||{})[a]??1}</span><h3>${a}</h3><div class="goal">${GOALS[a]}</div><div>Wants: <b>${nm(pid)}</b></div></div>`;
  }).join("");
  const rows = planIds.map(pid=>{
    const win = n.plan && n.plan.id===pid && roundSel===n.rounds.length-1;
    const cells = AGENTS.map(a=>{
      const v = r.votes[pid][a], sc = (n.scores[pid]||{})[a] ?? 0;
      const veto = !v.accept && v.reason.startsWith("Veto");
      return `<td title="${esc(v.reason)}"><span class="vote ${v.accept?"yes":veto?"veto":"no"}">${v.accept?"✓ accept":veto?"⛔ veto":"✗ object"}</span>
        <div class="bar"><i style="width:${Math.round(sc*100)}%;background:${COLORS[a]}"></i></div></td>`;
    }).join("");
    return `<tr class="${win?"winner":""}"><td>${nm(pid)}</td>${cells}</tr>`;
  }).join("");
  const label = {consensus:"Agreed 3 of 3", majority:"Majority decision, dissent kept on record", urgent:"Time is short: acting on the best-supported plan",
    irreconcilable:"Irreconcilable: no plan has a majority, asking a human", unacceptable:"Unacceptable compromise: the majority's plan crosses a red line, asking a human"}[n.outcome];
  const chosen = n.plan ? ` → ${nm(n.plan.id)}` : "";
  const dissent = (n.dissent||[]).map(x=>`<div class="dissent">${x.agent}: ${esc(x.reason)}</div>`).join("");
  const bubbles = msgs.slice(0, shown).map((m,i) => `<div class="bubble ${m.agent} ${m.type}${i===shown-1 && playing ? " new" : ""}${i===shown-1 && playing && m.type==="objection" ? " shake" : ""}">
      <span class="b-who">${m.agent}</span><span class="b-r">R${m.round}</span>${esc(m.text)}</div>`).join("");
  const done = !playing;
  setHTML("neg", `
    <div class="debate" id="debate">${bubbles || '<span class="muted">The agents are about to speak…</span>'}</div>
    <div class="neg-title"><b>${esc(n.donation)}</b> · ${esc(n.food)} <span class="badge light">${n.mode==="llm"?"AI reasoning":"rules reasoning"}</span></div>
    <div class="agents">${cards}</div>
    <table class="matrix"><thead><tr><th>Plans on the table (round ${r.round})</th>${AGENTS.map(a=>`<th style="color:${COLORS[a]}">${a}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>
    ${done && roundSel===n.rounds.length-1?`<div class="outcome ${n.outcome} pop">${label}${chosen}${dissent}</div>`:""}
    ${done?`<button class="replay" onclick="replay()">↻ Replay debate</button>`:""}
    ${tally()}`);
  const deb = $("debate"); if(deb) deb.scrollTop = deb.scrollHeight;
  if(voiceOn && play.seq === n.seq){
    const k = n.seq + ":" + (playing ? shown : "end");
    if(k !== lastSpoken && !(speaking && !playing)){
      lastSpoken = k;
      if(playing && shown) speak(msgs[shown-1].agent, msgs[shown-1].text, msgs[shown]);
      else if(!playing) speak("Dispatch", plain((label||"Decision made") + chosen));
    }
  }
}

function tally(){
  const o = S.outcomes || {}, names = {consensus:"agreed", majority:"majority", urgent:"time short", unacceptable:"unacceptable compromise",
    irreconcilable:"irreconcilable", insufficient_evidence:"asked for evidence", over_budget:"over budget", human_timeout:"fallback rule used"};
  const parts = Object.entries(o).map(([k,v])=>`<span>${names[k]||k}: <b>${v}</b></span>`).join("");
  return parts ? `<div class="tally"><span class="muted" style="background:none;padding-left:0">How negotiations ended so far:</span>${parts}</div>` : "";
}

function drawHuman(){
  const waiting = S.donations.filter(d=>d.status==="awaiting_human");
  const asking = S.donations.filter(d=>d.status==="awaiting_info");
  setHTML("human", waiting.map(d=>`
    <div class="human"><b>Coordinator needed for ${d.id}</b> (${esc(d.food.items.join(", "))}, ${d.minutes_left} min until unsafe).
      <div style="margin-top:4px">Why: ${esc(d.why||"the agents could not agree")}.</div>
      <div>${d.options.map(o=>`<button onclick="approve('${d.id}','${o.id}')">Approve ${esc(o.np_name)} via ${esc(o.driver_name)} · ${o.dur} min · $${o.cost.toFixed(2)}</button>`).join("")}</div></div>`).join("")
  + asking.map(d=>`
    <div class="human" style="border-color:var(--need)"><b>Agents are asking ${esc(d.business_name)} about ${d.id}</b> (${esc(d.food.items.join(", "))}):
      "Is this free of ${esc(d.asked_about)}?" Not enough evidence to decide yet; they act on what they know if there's no answer.
      <div><button onclick="confirmInfo('${d.id}',true)">Business: listed allergens only (${esc(d.food.allergens.join(", ")||"none")})</button>
      <button onclick="confirmInfo('${d.id}',false)">Business: can't say for sure</button></div></div>`).join(""));
}
async function approve(d,p){ await post("/api/approve",{donation:d,plan:p}); refresh(); }
async function confirmInfo(id, sure){ const d = S.donations.find(x=>x.id===id); await post("/api/confirm",{donation:id, allergens: sure ? d.food.allergens : null}); refresh(); }

// ---------- agent network ----------
const KIND = {announce:"Announces", accept:"Accept", counter:"Counter-offer", decline:"Decline", bid:"Bids", award:"Award", split:"Split", escalate:"Ask a human"};
function drawNetwork(){
  const a = S.agents_online;
  if(a) setHTML("net-agents", `${a.businesses} business agents · ${a.shelters} shelter agents · ${a.drivers} driver agents · ${a.coordinators} coordinators`);
  const n = pinned ? (S.negotiations||[]).find(h=>h.seq===pinned) : S.negotiation;
  if(!n) return;
  const all = (S.network||[]).filter(m => m.donation === n.donation);
  let start = 0; all.forEach((m,i) => { if(m.kind === "announce") start = i; });   // the latest round only
  const msgs = all.slice(start);
  const col = (title, kinds) => {
    const items = msgs.filter(m => kinds.includes(m.kind));
    return `<div class="net-col"><h3>${title}</h3>${items.map(m => `<div class="msg ${m.kind}"><div class="msg-top"><b>${esc(m.from)}</b><span class="k ${m.kind}">${KIND[m.kind]||m.kind}</span></div>${esc(m.text)}</div>`).join("") || '<p class="empty">—</p>'}</div>`;
  };
  setHTML("net", `<div class="net-grid">
    ${col("1 · Business agent", ["announce"])}
    ${col("2 · Shelter agents answer", ["accept","counter","decline"])}
    ${col("3 · Driver agents bid", ["bid"])}
    ${col("4 · Coordinators decide", ["escalate","award","split"])}
  </div>`);
}

// ---------- lists ----------
function drawLists(){
  setHTML("feed", S.feed.slice().reverse().map(f=>`<div><time>${f.time}</time><span class="who ${f.agent}">${f.agent}</span><span class="${f.type==="objection"?"objection":""}">${esc(f.text)}</span></div>`).join("") || "<p class='empty'>Nothing yet.</p>");
  setHTML("log", S.decisions.slice().reverse().map(x=>`<div><span class="v ${x.verdict}">${x.verdict==="allowed"?"ALLOWED":"BLOCKED"}</span>${esc(x.donation)} · ${esc(x.text)}</div>`).join("") || "<p class='empty'>No decisions yet.</p>");
  setHTML("dons", S.donations.slice().reverse().map(d=>{
    const live = !["delivered","spoiled","expired"].includes(d.status);
    const statusText = {awaiting_info:"asking business", awaiting_human:"asking human", awaiting_shelter:"asking shelter"}[d.status] || d.status.replace("_"," ");
    const where = d.plan ? `${esc(d.plan.np_name)} via ${esc(d.plan.driver_name)}` : "planning…";
    return `<div class="don"><span class="st ${d.status}">${statusText}</span><b>${d.id}</b> ${esc(d.food.items.join(", "))} · ${d.food.servings} servings<br>
      <span class="muted">${esc(d.business_name)} → ${where}</span>
      ${live?`<br><span class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left} min until unsafe (${d.safe_until})</span>`:""}</div>`;
  }).join("") || "<p class='empty'>No donations yet.</p>");
}

function drawCamera(){
  const cams = S.cameras || {};
  const names = Object.keys(cams);
  if(!names.length){ setHTML("cam-status", "No camera connected"); return; }
  setHTML("cam-status", names.map(b => {
    const biz = (S.businesses.find(x=>x.id===b)||{}).name || b;
    const seen = Object.entries(cams[b]).filter(([k,v])=>v>0).map(([k,v])=>`${v} ${k}`).join(", ") || "nothing yet";
    return `<span class="live-dot"></span>Camera at ${esc(biz)} sees: ${esc(seen)}`;
  }).join(" · "));
}

function drawKpis(){
  const i = S.impact;
  $("k-meals").textContent = i.meals; $("k-lbs").textContent = i.lbs; $("k-orgs").textContent = i.orgs;
  $("k-lost").textContent = i.spoiled; $("k-cost").textContent = "$"+i.cost.toFixed(2); $("k-esc").textContent = i.escalations;
  $("clock").textContent = S.now + (S.paused?" ⏸":"");
  $("mode").textContent = `Agents: ${S.mode.agents} · Vision: ${S.mode.vision} · Voice: ${S.mode.voice}`;
  $("pause").textContent = S.paused ? "Resume" : "Pause";
}

async function refresh(){
  try{
    S = await (await fetch("/api/state")).json();
    if(!$("scenario").options.length){
      $("scenario").innerHTML = S.scenarios.map(s=>`<option value="${s.name}">${esc(s.title)}</option>`).join("");
    }
    $("speed").value = String(S.speed);
    drawKpis(); drawMap(); drawNegotiation(); drawNetwork(); drawHuman(); drawLists(); drawCamera(); toastNewEvents();
  }catch(e){ console.error(e); }
}

$("start").onclick = async()=>{ await post("/api/reset",{scenario:$("scenario").value}); lastNegKey=null; pinned=null; play={seq:0,shown:0,total:0}; lastSeq=0; refresh(); };
$("blank").onclick = async()=>{ await post("/api/reset",{}); lastNegKey=null; pinned=null; play={seq:0,shown:0,total:0}; lastSeq=0; refresh(); };
$("speed").onchange = e=>post("/api/control",{speed:+e.target.value});
$("pause").onclick = ()=>post("/api/control",{paused:!S.paused}).then(refresh);
$("closing").onclick = async()=>{
  if(!Object.keys(S.cameras||{}).length){ toast("No camera connected. Start camera.py first.", "warn"); return; }
  await post("/api/closing", {}); toast("🕘 Closing time: cameras are reporting leftover food", "info");
};
document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=async()=>{ await post("/api/event/"+b.dataset.ev); refresh(); });

const dlg = $("dlg");
$("voice").onclick = ()=>{
  voiceOn = !voiceOn;
  $("voice").textContent = voiceOn ? "🔊 Voices on" : "🔈 Voices off";
  $("voice").classList.toggle("primary", voiceOn);
  if(voiceOn){ toast(S && S.mode.voice==="elevenlabs" ? "Voices on (ElevenLabs). Replaying the debate." : "Voices on (browser voice; add an ElevenLabs key for real voices)", "info"); lastSpoken = null; replay(); }
  else { endSpeak(); if(window.speechSynthesis) speechSynthesis.cancel(); Object.values(audioCache).forEach(a=>a.pause()); }
};
$("compare").onclick = async()=>{
  dlg.showModal(); setHTML("cmp", "Running 50 random scenarios…");
  const r = await (await fetch("/api/compare?n=50")).json();
  const b = r.random.totals.baseline, a = r.random.totals.agents, w = r.random.wins;
  const pct = (x,y)=> Math.round(100*Math.abs(1-x/y));
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
  const block = (title,res)=>`<tr><th colspan="${P.length+1}" style="text-align:left;padding-top:14px">${esc(title)}</th></tr>` + M.map(([k,l,dir])=>{
    const vals = P.map(p=>res[p][k]); const best = dir>0 ? Math.max(...vals) : Math.min(...vals);
    return `<tr><td>${l}</td>${P.map(p=>`<td class="${dir&&res[p][k]===best?"better":""}">${res[p][k]}</td>`).join("")}</tr>`;}).join("")
    + `<tr><td colspan="${P.length+1}" style="text-align:left" class="muted small">Team outcomes: ${outcomeLine(res.agents.outcomes)}</td></tr>`;
  setHTML("cmp", `
    <div class="hero-row">
      <div class="hero"><b>${pct(a.servings_lost, b.servings_lost)}%</b><span>less food lost</span></div>
      <div class="hero"><b>${pct(a.meals_delivered_safely, b.meals_delivered_safely)}%</b><span>more meals delivered</span></div>
      <div class="hero"><b>${pct(a.money_spent, b.money_spent)}%</b><span>lower driver cost</span></div>
      <div class="hero"><b>${w.more_food_lost} of ${r.random.n}</b><span>runs where agents lost more food</span></div>
    </div>
    <p class="muted small">Across ${r.random.n} seeded random lunch rushes (3–6 donations, driver no-shows, full shelters, new pantries). Agents lost less food in ${w.less_food_lost}, the same in ${w.same_food_lost}.</p>
    <div class="cbars">
      ${metric("Meals delivered safely","meals_delivered_safely",num,"higher is better")}
      ${metric("Servings lost","servings_lost",num,"lower is better")}
      ${metric("Money spent on paid drivers","money_spent",usd,"lower is better")}
    </div>
    <details><summary>The ${sc.rows.length} scripted demo scenarios: team vs nearest shelter vs each agent alone</summary>
      <p class="muted small"><b>Speed / Cost / Need alone</b> use the same safety rules as the team, but one agent decides by itself with no negotiation. <b>Green</b> = best in the row.</p>
      <table><thead><tr><th></th>${P.map(p=>`<th>${esc(sc.policies[p])}</th>`).join("")}</tr></thead><tbody>
      ${block("All scenarios",sc.totals)}
      ${sc.rows.map(x=>block(x.title,x.results)).join("")}</tbody></table></details>`);
};

refresh(); setInterval(refresh, 1000);
