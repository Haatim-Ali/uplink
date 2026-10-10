const AGENTS = ["Speed","Cost","Need"];
const GOALS = {Speed:"Fast, reliable, big safety margin", Cost:"Spend as little as possible", Need:"Feed whoever needs it most"};
const COLORS = {Speed:"var(--speed)",Cost:"var(--cost)",Need:"var(--need)"};
let S = null, roundSel = null, lastNegKey = null, pinned = null;
const $ = id => document.getElementById(id);
// Write HTML only when it changed: no flicker, hover and scroll survive the 1-second refresh.
function setHTML(el, html){ if(typeof el==="string") el=$(el); if(el._html!==html){ el._html=html; el.innerHTML=html; } }
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function toast(msg){ const t=$("toast"); t.textContent=msg; t.style.display="block"; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none",2600); }
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
  layers.route.clearLayers();   // routes change shape every tick, so these are redrawn
  S.donations.filter(d=>d.status==="en_route" && d.plan).forEach(d=>{
    const dr = S.drivers.find(x=>x.id===d.plan.driver);
    const pts = d.picked ? [[dr.lat,dr.lng],[d.dest.lat,d.dest.lng]] : [[dr.lat,dr.lng],[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]];
    L.polyline(pts,{color:"#2563a8",weight:3,dashArray:"6 6"}).addTo(layers.route);
  });
}

// ---------- negotiation ----------
function pin(seq){ pinned = (pinned===seq ? null : seq); lastNegKey=null; drawNegotiation(); }
function drawNegotiation(){
  const hist = S.negotiations || [];
  const shown = pinned || (S.negotiation && S.negotiation.seq);
  setHTML("history", hist.length > 1 ? `<span class="hist-label">Past negotiations:</span>` +
    hist.map(h=>`<button class="hb ${shown===h.seq?"on":""}" onclick="pin(${h.seq})">${h.time} ${h.donation}</button>`).join("") +
    (pinned?`<button class="follow" onclick="pin(null)">follow live</button>`:"") : "");
  const n = pinned ? hist.find(h=>h.seq===pinned) : S.negotiation;
  if(S.busy && !pinned){ setHTML("rounds", ""); setHTML("neg", `<p><b>Agents are deliberating…</b> The clock is paused until they finish.</p>`); return; }
  if(!n){ return; }
  const key = n.seq + "|" + n.donation + "|" + n.rounds.length + "|" + n.outcome + "|" + (n.plan?n.plan.id:"");
  if(key!==lastNegKey){ roundSel = n.rounds.length-1; lastNegKey = key; }
  setHTML("rounds", n.rounds.map((r,i)=>`<button class="${i===roundSel?"on":""}" onclick="roundSel=${i};drawNegotiation()">R${r.round}</button>`).join(" "));
  const r = n.rounds[roundSel];
  const planIds = Object.keys(r.votes);
  const nm = id => { const [np,dr] = id.split("|"); const N = S.nonprofits.find(x=>x.id===np); const D = S.drivers.find(x=>x.id===dr); return `${N?N.name:np} <span class="muted">via ${D?D.name:dr}</span>`; };
  const cards = AGENTS.map(a=>{
    const pid = r.proposals[a];
    return `<div class="agent ${a}"><span class="w">vote ×${(n.weights||{})[a]??1}</span><h3>${a}</h3><div class="goal">${GOALS[a]}</div><div>Wants: <b>${nm(pid)}</b></div></div>`;
  }).join("");
  const rows = planIds.map(pid=>{
    const win = n.plan && n.plan.id===pid && roundSel===n.rounds.length-1;
    const cells = AGENTS.map(a=>{
      const v = r.votes[pid][a], sc = (n.scores[pid]||{})[a] ?? 0;
      return `<td title="${esc(v.reason)}"><span class="vote ${v.accept?"yes":"no"}">${v.accept?"✓ accept":"✗ object"}</span>
        <div class="bar"><i style="width:${Math.round(sc*100)}%;background:${COLORS[a]}"></i></div></td>`;
    }).join("");
    return `<tr class="${win?"winner":""}"><td>${nm(pid)}</td>${cells}</tr>`;
  }).join("");
  const label = {consensus:"Agreed 3 of 3", majority:"Majority decision, dissent kept on record", urgent:"Time is short: acting on the best-supported plan", escalate:"No agreement: asking a human"}[n.outcome];
  const chosen = n.plan ? ` → ${nm(n.plan.id)}` : "";
  const dissent = (n.dissent||[]).map(x=>`<div class="dissent">${x.agent}: ${esc(x.reason)}</div>`).join("");
  setHTML("neg", `
    <div class="neg-title"><b>${esc(n.donation)}</b> · ${esc(n.food)} <span class="badge light">${n.mode==="llm"?"AI reasoning":"rules reasoning"}</span></div>
    <div class="agents">${cards}</div>
    <table class="matrix"><thead><tr><th>Plans on the table (round ${r.round})</th>${AGENTS.map(a=>`<th style="color:${COLORS[a]}">${a}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>
    ${roundSel===n.rounds.length-1?`<div class="outcome ${n.outcome}">${label}${chosen}${dissent}</div>`:""}`);
}

function drawHuman(){
  const waiting = S.donations.filter(d=>d.status==="awaiting_human");
  setHTML("human", waiting.map(d=>`
    <div class="human"><b>Coordinator needed for ${d.id}</b> (${esc(d.food.items.join(", "))}, ${d.minutes_left} min until unsafe). The agents could not agree or the cost is over the limit.
      <div>${d.options.map(o=>`<button onclick="approve('${d.id}','${o.id}')">Approve ${esc(o.np_name)} via ${esc(o.driver_name)} · ${o.dur} min · $${o.cost.toFixed(2)}</button>`).join("")}</div></div>`).join(""));
}
async function approve(d,p){ await post("/api/approve",{donation:d,plan:p}); refresh(); }

// ---------- lists ----------
function drawLists(){
  setHTML("feed", S.feed.slice().reverse().map(f=>`<div><time>${f.time}</time><span class="who ${f.agent}">${f.agent}</span><span class="${f.type==="objection"?"objection":""}">${esc(f.text)}</span></div>`).join("") || "<p class='empty'>Nothing yet.</p>");
  setHTML("log", S.decisions.slice().reverse().map(x=>`<div><span class="v ${x.verdict}">${x.verdict==="allowed"?"ALLOWED":"BLOCKED"}</span>${esc(x.donation)} · ${esc(x.text)}</div>`).join("") || "<p class='empty'>No decisions yet.</p>");
  setHTML("dons", S.donations.slice().reverse().map(d=>{
    const live = !["delivered","spoiled","expired"].includes(d.status);
    const where = d.plan ? `${esc(d.plan.np_name)} via ${esc(d.plan.driver_name)}` : "planning…";
    return `<div class="don"><span class="st ${d.status}">${d.status.replace("_"," ")}</span><b>${d.id}</b> ${esc(d.food.items.join(", "))} · ${d.food.servings} servings<br>
      <span class="muted">${esc(d.business_name)} → ${where}</span>
      ${live?`<br><span class="timer ${d.minutes_left<30?"low":""}">${d.minutes_left} min until unsafe (${d.safe_until})</span>`:""}</div>`;
  }).join("") || "<p class='empty'>No donations yet.</p>");
}

function drawKpis(){
  const i = S.impact;
  $("k-meals").textContent = i.meals; $("k-lbs").textContent = i.lbs; $("k-orgs").textContent = i.orgs;
  $("k-lost").textContent = i.spoiled; $("k-cost").textContent = "$"+i.cost.toFixed(2); $("k-esc").textContent = i.escalations;
  $("clock").textContent = S.now + (S.paused?" ⏸":"");
  $("mode").textContent = `Agents: ${S.mode.agents} · Vision: ${S.mode.vision}`;
  $("pause").textContent = S.paused ? "Resume" : "Pause";
}

async function refresh(){
  try{
    S = await (await fetch("/api/state")).json();
    if(!$("scenario").options.length){
      $("scenario").innerHTML = S.scenarios.map(s=>`<option value="${s.name}">${esc(s.title)}</option>`).join("");
    }
    $("speed").value = String(S.speed);
    drawKpis(); drawMap(); drawNegotiation(); drawHuman(); drawLists();
  }catch(e){ console.error(e); }
}

$("start").onclick = async()=>{ await post("/api/reset",{scenario:$("scenario").value}); lastNegKey=null; pinned=null; refresh(); };
$("blank").onclick = async()=>{ await post("/api/reset",{}); lastNegKey=null; pinned=null; refresh(); };
$("speed").onchange = e=>post("/api/control",{speed:+e.target.value});
$("pause").onclick = ()=>post("/api/control",{paused:!S.paused}).then(refresh);
document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=async()=>{ await post("/api/event/"+b.dataset.ev); refresh(); });

const dlg = $("dlg");
$("compare").onclick = async()=>{
  dlg.showModal(); $("cmp").textContent = "Running all scenarios…";
  const r = await (await fetch("/api/compare")).json();
  const M = [["meals_delivered_safely","Meals delivered safely",1],["servings_lost","Servings lost",-1],["money_spent","Money spent ($)",-1],["shelters_fed","Shelters fed",1],["human_escalations","Asked a human",0]];
  const block = (title,b,a)=>`<tr><th colspan="3" style="text-align:left;padding-top:14px">${esc(title)}</th></tr>` + M.map(([k,l,dir])=>{
    const better = dir && (dir>0 ? a[k]>b[k] : a[k]<b[k]);
    return `<tr><td>${l}</td><td>${b[k]}</td><td class="${better?"better":""}">${a[k]}</td></tr>`;}).join("");
  $("cmp").innerHTML = `<table><thead><tr><th></th><th>Baseline</th><th>Agents</th></tr></thead><tbody>
    ${block("All scenarios",r.totals.baseline,r.totals.agents)}
    ${r.rows.map(x=>block(x.title,x.baseline,x.agents)).join("")}</tbody></table>`;
};

refresh(); setInterval(refresh, 1000);
