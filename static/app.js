// Uplink customer site: plain-language flow for a business that wants leftover food picked up.
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const store = {
  get:(k)=>{ try{ return localStorage.getItem(k); }catch(e){ return null; } },
  set:(k,v)=>{ try{ localStorage.setItem(k,v); }catch(e){} },
};
let S = null, view = "home", arg = null;
const DONE = ["delivered","spoiled","expired"];
const ICON = {
  scale:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 8h14l1.5 12h-17zM9 8a3 3 0 0 1 6 0"/></svg>',
  box:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10"/></svg>',
  clock:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  alert:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l10 18H2zM12 10v5M12 18h.01"/></svg>',
  check:'<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>',
};

// ---------- small helpers ----------
let _html = {};
function setHTML(id, html){ const el = $(id); if(_html[id] !== html){ _html[id] = html; el.innerHTML = html; } }
function clock(t){   // "15:15" -> "3:15 PM"
  const m = /^(\d{1,2}):(\d{2})/.exec(t || ""); if(!m) return t || "";
  let h = +m[1]; const ap = h >= 12 ? "PM" : "AM"; h = h % 12 || 12; return `${h}:${m[2]} ${ap}`;
}
const firstName = n => String(n || "").replace(/\s*\(.*?\)\s*/g, "").trim();
function cap(s){ return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
function itemsText(items){
  const a = (items || []).filter(Boolean);
  if(!a.length) return "Food";
  return cap(a.slice(0,3).join(", ") + (a.length > 3 ? ` and ${a.length-3} more` : ""));
}
function duration(m){
  if(m < 90) return `${Math.round(m)} minutes`;
  const h = Math.round(m / 30) / 2; return `${h} hours`;
}
const TRANSPORT = {volunteer:"Volunteer driver", paid:"Paid courier", "nonprofit van":"Shelter's own van"};
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body || {})});
  const j = await r.json().catch(()=>({})); if(!r.ok) throw new Error(j.error || "Request failed"); return j;
}

// ---------- plain-language status ----------
const STEPS = ["Received", "Finding a place", "Driver assigned", "Picked up", "Delivered"];
function stage(d){
  const np = d.plan && d.plan.np_name, drv = d.plan && firstName(d.plan.driver_name);
  switch(d.status){
    case "delivered": return {step:5, head:"Delivered", sub:`Your food reached ${np || "the shelter"}.`, tag:"Delivered", tone:"good"};
    case "spoiled": case "expired": return {step:0, fail:true, head:"We couldn't deliver this in time", sub:"Please schedule another pickup if you still have the food.", tag:"Not delivered", tone:"bad"};
    case "en_route": return d.picked
      ? {step:4, head:"Picked up and on its way", sub:`Heading to ${np}.`, tag:"On its way", tone:""}
      : {step:3, head:"A driver is on the way to you", sub: drv ? `${drv} is coming to pick it up.` : "", tag:"Driver on the way", tone:""};
    case "awaiting_info": return {step:2, head:"We need one answer from you", sub:"Answer below so we can choose the right place.", tag:"Needs your answer", tone:"warn"};
    case "awaiting_shelter": return {step:2, head:"Waiting for a shelter to say yes", sub: np ? `${np} is confirming.` : "A shelter is confirming.", tag:"Finding a place", tone:""};
    case "awaiting_human": return {step:2, head:"Choosing the best option", sub:"Our team is picking the best match for your food.", tag:"Finding a place", tone:""};
    case "stuck": return {step:2, head:"Still looking for a driver", sub:"We're checking again every few minutes.", tag:"Finding a driver", tone:"warn"};
    default: return {step:2, head:"Finding a place for your food", sub:"We're checking which shelters can take it right now.", tag:"Finding a place", tone:""};
  }
}
const donation = id => S && S.donations.find(d => d.id === id);

// ---------- router ----------
const VIEWS = ["home","schedule","track","donations","receipt","help"];
function route(){
  const h = (location.hash || "#/").replace(/^#\/?/, "").split("/");
  view = h[0] === "" ? "home" : VIEWS.includes(h[0]) ? h[0] : "home";
  arg = decodeURIComponent(h[1] || "") || null;
  document.querySelectorAll(".view").forEach(v => v.hidden = v.dataset.view !== view);
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("active", a.dataset.nav === view || (view==="receipt" && a.dataset.nav==="donations")));
  if(view === "schedule") resetSchedule(false);
  if(view !== "track"){ destroyMap(); try{ sessionStorage.removeItem("uplink_new"); }catch(e){} }
  window.scrollTo(0, 0);
  render();
  const m = $("main"); if(m) m.focus({preventScroll:true});
}
window.addEventListener("hashchange", route);

function render(){
  if(!S) return;
  fillBusinesses();
  if(view === "home") drawHome();
  else if(view === "track") drawTrack();
  else if(view === "donations") drawDonations();
  else if(view === "receipt") drawReceipt();
}
async function refresh(){
  try{ S = await (await fetch("/api/state")).json(); render(); }catch(e){ /* keep the last good view */ }
}

// ---------- businesses ----------
function fillBusinesses(){
  const bs = S.businesses || [];
  const sig = bs.map(b => b.id).join(",");
  if($("biz")._sig === sig) return;
  $("biz")._sig = sig;
  const saved = store.get("uplink_biz");
  $("biz").innerHTML = bs.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  if(saved && bs.some(b => b.id === saved)) $("biz").value = saved;
  const f = $("bizFilter"), cur = f.value || store.get("uplink_biz") || "all";
  f.innerHTML = `<option value="all">All businesses</option>` + bs.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  f.value = bs.some(b => b.id === cur) ? cur : "all";
}
$("biz").onchange = () => store.set("uplink_biz", $("biz").value);
$("bizFilter").onchange = () => { if(S) drawDonations(); };
function bizName(id){ const b = S && S.businesses.find(x => x.id === id); return b ? b.name : null; }

// ---------- home ----------
function drawHome(){
  const last = store.get("uplink_last"), d = last && donation(last);
  if(d && !DONE.includes(d.status)){
    const st = stage(d);
    setHTML("home-active", `<a class="active-card" href="#/track/${esc(d.id)}"><span><small>Your latest pickup</small><b>${esc(st.head)}</b></span><span class="go">Track it</span></a>`);
  } else setHTML("home-active", "");
}

// ---------- schedule ----------
let photo = null, source = null, cur = null;
function setStep(n){
  [1,2,3].forEach(i => { const li = $("st"+i); li.className = i<n ? "done" : i===n ? "active" : ""; if(i===n) li.setAttribute("aria-current","step"); else li.removeAttribute("aria-current"); });
}
function resetSchedule(full){
  $("sch-photo").hidden = false; $("sch-confirm").hidden = true; setStep(1);
  if(full){ photo = null; $("file").value = ""; $("preview").style.display = "none"; $("dropText").textContent = "Take or choose a photo"; $("analyze").disabled = true; }
}
$("file").onchange = e => {
  photo = e.target.files[0]; if(!photo) return;
  $("preview").src = URL.createObjectURL(photo); $("preview").style.display = "block";
  $("dropText").textContent = "Photo added. Tap to change it";
  $("analyze").disabled = false;
};
// Shrink the photo in the browser before upload: faster, and keeps it within the model's limits.
// If the browser can't decode it (e.g. HEIC in Chrome), send the original; the server converts it.
function shrink(file, maxEdge = 1568){
  return new Promise(resolve => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxEdge / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob(b => resolve(b || file), "image/jpeg", 0.9);
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}
function readForm(){
  const num = id => +$(id).value;
  return {
    items: $("items").value.split(",").map(s=>s.trim()).filter(Boolean),
    servings: num("servings"), safe_minutes: num("safe"),
    weight_lbs: [num("wlo"), num("whi")], category: $("category").value,
    allergens: $("allergens").value.split(",").map(s=>s.trim().toLowerCase()).filter(Boolean),
    needs_cold: $("cold").checked, allergens_unverified: $("unsure").checked,
  };
}
function drawSummary(){
  const f = readForm(), w = f.weight_lbs;
  const wt = (w[0] && w[1]) ? (w[0] === w[1] ? `${w[0]} lbs` : `${w[0]}–${w[1]} lbs`) : "";
  const type = {"hot prepared":"Hot, prepared food", "cold prepared":"Cold, prepared food", packaged:"Packaged food", produce:"Produce"}[f.category] || f.category;
  const storage = f.needs_cold ? "keep refrigerated" : f.category === "hot prepared" ? "keep warm" : "room temperature is fine";
  const fact = (icon, t) => `<li>${icon}<span>${t}</span></li>`;
  setHTML("summary", `<div class="big">${esc(itemsText(f.items))}</div>
    <div class="sub">About ${f.servings || "?"} servings</div>
    <ul class="facts">
      ${wt ? fact(ICON.scale, esc(wt)) : ""}
      ${fact(ICON.box, `${esc(type)}, ${storage}`)}
      ${fact(ICON.clock, `Safe for about ${esc(duration(f.safe_minutes || 0))}`)}
      ${fact(ICON.alert, f.allergens.length ? `Contains: ${esc(f.allergens.join(", "))}` : "No allergens listed")}
    </ul>`);
}
["items","servings","safe","wlo","whi","category","allergens","cold"].forEach(id => $(id).addEventListener("input", drawSummary));
function notice(kind, text){ const n = $("notice"); n.hidden = !text; n.className = "notice " + (kind || ""); n.textContent = text || ""; }
function openForm(open){ $("form").hidden = !open; $("edit").setAttribute("aria-expanded", String(open)); $("edit").textContent = open ? "Hide details" : "Edit details"; }
$("edit").onclick = () => openForm($("form").hidden);
function showSource(r){
  const f = r.food || {};
  $("servings").classList.remove("check"); $("items").classList.remove("check");
  if(r.source === "demo"){ notice("warn", "This is a sample result (demo mode), not your photo. Please edit anything that's wrong."); }
  else if(r.source === "fallback"){ notice("bad", "We couldn't read this photo. Please fill in what you have."); openForm(true); }
  else if(f.confidence === "high"){ notice("ok", "We read your photo. Please check that it looks right."); }
  else { notice("warn", "We're not sure about the amount. Please check the number of servings."); openForm(true); }
}
function fill(f){
  $("items").value = f.items.join(", "); $("servings").value = f.servings; $("safe").value = f.safe_minutes;
  $("wlo").value = f.weight_lbs[0]; $("whi").value = f.weight_lbs[1]; $("category").value = f.category;
  $("allergens").value = f.allergens.join(", "); $("cold").checked = !!f.needs_cold; $("unsure").checked = !!f.allergens_unverified;
  $("err").hidden = true; openForm(false); drawSummary();
  $("sch-photo").hidden = true; $("sch-confirm").hidden = false; setStep(2); window.scrollTo(0, 0);
}
$("analyze").onclick = async () => {
  $("analyze").disabled = true; $("analyze").textContent = "Reading your photo…";
  const fd = new FormData(); fd.append("photo", await shrink(photo), "photo.jpg");
  let r;
  try { r = await (await fetch("/api/vision", {method:"POST", body:fd})).json(); if(!r.food) throw new Error(); }
  catch(e){ r = {source:"fallback", food:{items:[],servings:1,safe_minutes:120,weight_lbs:[1,2],category:"hot prepared",allergens:[],needs_cold:false}}; }
  $("analyze").textContent = "Continue"; $("analyze").disabled = false;
  fill(r.food); showSource(r);
};
$("skip").onclick = () => { fill({items:["food"],servings:10,safe_minutes:120,weight_lbs:[2,4],category:"hot prepared",allergens:[],needs_cold:false}); notice("", ""); openForm(true); $("items").focus(); };
$("back").onclick = () => resetSchedule(false);
function showErr(m){ const e = $("err"); e.textContent = m; e.hidden = false; }
$("confirm").onclick = async () => {
  const food = readForm();
  if(!food.items.length){ openForm(true); return showErr("Please tell us what the food is."); }
  if(!(food.servings >= 1)){ openForm(true); return showErr("Servings must be at least 1."); }
  if(!(food.safe_minutes >= 10)){ openForm(true); return showErr("Please say how long the food stays safe (at least 10 minutes)."); }
  $("err").hidden = true; $("confirm").disabled = true; $("confirm").textContent = "Scheduling…";
  try{
    const r = await post("/api/donate", {food, business:$("biz").value});
    store.set("uplink_biz", $("biz").value); store.set("uplink_last", r.id); try{ sessionStorage.setItem("uplink_new", r.id); }catch(e){}
    resetSchedule(true);
    location.hash = "#/track/" + r.id;
    refresh();
  }catch(e){ showErr("We couldn't schedule this. Check your connection and try again."); }
  $("confirm").disabled = false; $("confirm").textContent = "Confirm pickup";
};

// ---------- track ----------
// The pickup ticket: printed-receipt style, like an order ticket in the kitchen. It "prints" once.
const printed = new Set();
function ticket(d, np, arrive){
  const f = d.food, done = d.status === "delivered";
  const keep = f.needs_cold ? "Keep cold." : f.category === "hot prepared" ? "Keep warm." : "";
  const alg = f.allergens.length ? `Contains ${f.allergens.join(", ")}.` : "";
  const fresh = !printed.has(d.id); printed.add(d.id);
  return `<div class="ticket${fresh ? " print-in" : ""}" role="group" aria-label="Pickup ticket">
    <div class="t-head"><span>Uplink pickup</span><b>${esc(d.id)}</b></div>
    <div class="t-from">${esc(d.business_name)}</div>
    <div class="t-rule"></div>
    <div class="t-food"><b>${f.servings}×</b> ${esc(itemsText(f.items))}</div>
    ${keep || alg ? `<div class="t-note">${esc([keep, alg].filter(Boolean).join(" "))}</div>` : ""}
    <div class="t-rule"></div>
    <dl class="t-lines">
      ${d.plan ? `<dt>Driver</dt><dd>${esc(firstName(d.plan.driver_name))}</dd>` : ""}
      <dt>To</dt><dd>${esc(np)}</dd>
      ${arrive ? `<dt>${done ? "Delivered" : "Arrives"}</dt><dd>${esc(clock(arrive))}</dd>` : ""}
    </dl>
    <div class="t-rule"></div>
    <div class="t-foot">${done ? "Delivered. Your receipt is ready." : "Show this to the driver at pickup."}</div>
  </div>`;
}
let tmap = null, tlayers = null, tFor = null, tTilesFailed = 0;
function destroyMap(){ if(tmap){ tmap.remove(); tmap = null; } tFor = null; _html.trackTop = _html.trackBottom = undefined; $("track").innerHTML = ""; }
function addTiles(m){
  // Standard OpenStreetMap tiles; app.css desaturates and lightens them so markers stand out.
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom:18, attribution:"© OpenStreetMap contributors"}).addTo(m);
}
function mkIcon(cls){ return L.divIcon({className:"", iconSize:[24,24], iconAnchor:[12,12], html:`<div class="mk ${cls}"></div>`}); }
function ensureTrackSkeleton(id){
  if(tFor === id) return;
  destroyMap(); tFor = id;
  $("track").innerHTML = `<div id="trackTop"></div><div id="tmapWrap" hidden><div id="tmap" role="img" aria-label="Map showing the pickup, the driver and the destination"></div></div><div id="trackBottom"></div>`;
}
function setIn(id, html){ const el = $(id); if(el._h !== html){ el._h = html; el.innerHTML = html; } }
function drawTrack(){
  if(!arg){ location.hash = "#/donations"; return; }
  ensureTrackSkeleton(arg);
  const d = donation(arg);
  if(!d){
    setIn("trackTop", `<div class="empty"><b>We can't find that pickup</b>It may be from an earlier session.<br><a class="btn primary" href="#/donations">See my donations</a></div>`);
    $("tmapWrap").hidden = true; setIn("trackBottom", ""); return;
  }
  const st = stage(d);
  let fresh = ""; try{ fresh = sessionStorage.getItem("uplink_new") === d.id ? "1" : ""; }catch(e){}
  const stepper = fresh ? `<ol class="steps" aria-label="Progress"><li class="done"><span class="dot">${ICON.check}</span>Photo</li><li class="done"><span class="dot">${ICON.check}</span>Confirm</li><li class="active" aria-current="step"><span class="dot">3</span>Scheduled</li></ol>` : "";
  const np = d.plan && d.plan.np_name;
  let destBlock = "";
  if(np && !st.fail){
    const arrive = d.status === "delivered" ? ((S.records.find(r => r.donation === d.id) || {}).delivered) : d.plan.arrive_hhmm;
    destBlock = ticket(d, np, arrive);
  }
  let question = "";
  if(d.status === "awaiting_info"){
    question = `<div class="question" role="alert"><h2>Is this food free of ${esc(d.asked_about || "the allergens we asked about")}?</h2><p>Some shelters can't take certain allergens. If you're not sure, say so and we'll stay on the safe side.</p>
      <button class="btn primary" type="button" id="q-yes">Yes, that's everything</button><button class="btn" type="button" id="q-no">Not sure</button></div>`;
  }
  const rec = d.status === "delivered" && S.records.find(r => r.donation === d.id);
  setIn("trackTop", `${stepper}${fresh && !stepper ? "" : ""}<div class="status-head"><div class="eyebrow">Pickup ${esc(d.id)} · ${esc(itemsText(d.food.items))}</div><h1>${esc(st.head)}</h1>${st.sub ? `<p class="lead">${esc(st.sub)}</p>` : ""}</div>${question}${destBlock}`);
  if(question){ $("q-yes").onclick = () => answer(d, true); $("q-no").onclick = () => answer(d, false); }

  // timeline
  const tl = STEPS.map((label, i) => {
    const n = i + 1;
    let cls = st.fail ? (n === 1 ? "done" : "") : n < st.step ? "done" : n === st.step ? (st.step === 5 ? "done" : "now") : "";
    let note = "";
    if(n === 2 && np && n < st.step) note = `<small>${esc(np)}</small>`;
    if(n === 3 && d.plan && n <= st.step) note = `<small>${esc(firstName(d.plan.driver_name))}</small>`;
    if(n === 5 && st.step === 5 && rec) note = `<small>${esc(clock(rec.delivered))}</small>`;
    return `<li class="${cls}"${cls==="now"?' aria-current="step"':""}><span class="pt">${cls === "done" ? ICON.check : ""}</span>${esc(label)}${note}</li>`;
  }).join("") + (st.fail ? `<li class="fail"><span class="pt"></span>Not delivered in time</li>` : "");
  const info = `<dl><dt>Food</dt><dd>${d.food.servings} servings of ${esc(d.food.items.join(", "))}</dd><dt>From</dt><dd>${esc(d.business_name)}</dd>${d.plan ? `<dt>Driver</dt><dd>${esc(firstName(d.plan.driver_name))}</dd>` : ""}</dl>`;
  const after = d.status === "delivered"
    ? `<a class="btn primary xl" href="#/receipt/${esc(d.id)}">View your receipt</a>`
    : st.fail ? `<a class="btn primary xl" href="#/schedule">Schedule another pickup</a>` : "";
  setIn("trackBottom", `<ol class="timeline" aria-label="Progress">${tl}</ol>${destBlock ? "" : `<div class="mini">${info}</div>`}${after}`);
  drawTrackMap(d);
}
async function answer(d, sure){
  $("q-yes").disabled = $("q-no").disabled = true;
  try{ await post("/api/confirm", {donation:d.id, allergens: sure ? d.food.allergens : null}); }catch(e){}
  refresh();
}
function drawTrackMap(d){
  const wrap = $("tmapWrap");
  if(!d.origin || DONE.includes(d.status) && d.status !== "delivered"){ wrap.hidden = true; return; }
  wrap.hidden = false;
  if(!tmap){
    try{
      tmap = L.map("tmap", {zoomControl:true, scrollWheelZoom:false}).setView([d.origin.lat, d.origin.lng], 14);
      addTiles(tmap); tlayers = {};
    }catch(e){ wrap.hidden = true; return; }
  }
  const put = (k, ll, cls, tip) => {
    if(!ll){ if(tlayers[k]){ tlayers[k].remove(); delete tlayers[k]; } return; }
    if(!tlayers[k]) tlayers[k] = L.marker(ll, {icon:mkIcon(cls)}).bindTooltip(tip, {permanent:false}).addTo(tmap);
    else tlayers[k].setLatLng(ll);
  };
  const drv = d.plan && S.drivers.find(x => x.id === d.plan.driver);
  const showDrv = drv && (d.status === "en_route" || d.status === "delivered");
  put("pickup", [d.origin.lat, d.origin.lng], "m-pickup", "Pickup: " + d.business_name);
  put("dest", d.plan && d.dest ? [d.dest.lat, d.dest.lng] : null, "m-dest", d.plan ? d.plan.np_name : "");
  put("drv", showDrv ? [drv.lat, drv.lng] : null, "m-drv", drv ? firstName(drv.name) : "");
  if(tlayers.line){ tlayers.line.remove(); delete tlayers.line; }
  if(d.plan && d.dest){
    const pts = showDrv && d.status === "en_route" ? (d.picked ? [[drv.lat,drv.lng],[d.dest.lat,d.dest.lng]] : [[drv.lat,drv.lng],[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]]) : [[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]];
    tlayers.line = L.polyline(pts, {color:"#127a3f", weight:4, opacity:.8}).addTo(tmap);
  }
  const all = ["pickup","dest","drv"].filter(k => tlayers[k]).map(k => tlayers[k].getLatLng());
  const key = all.length + "|" + (showDrv ? 1 : 0);
  if(tmap._k !== key || (all.length > 1 && !tmap.getBounds().pad(-0.05).contains(all[all.length-1]))){
    tmap._k = key; tmap.invalidateSize();
    if(all.length > 1) tmap.fitBounds(L.latLngBounds(all), {padding:[40,40], maxZoom:15}); else tmap.setView(all[0], 15);
  }
}

// ---------- my donations ----------
function myDonations(){
  const f = $("bizFilter").value;
  const name = f === "all" ? null : bizName(f);
  return S.donations.slice().reverse().filter(d => !name || d.business_name === name);
}
function drawDonations(){
  const list = myDonations();
  if(!list.length){
    setHTML("donList", `<div class="empty"><b>No donations yet</b>When you schedule a pickup, it shows up here.<br><a class="btn primary" href="#/schedule">Schedule a pickup</a></div>`);
    return;
  }
  setHTML("donList", list.map(d => {
    const st = stage(d), np = d.plan && d.plan.np_name;
    const act = d.status === "delivered" ? `<a class="btn sm" href="#/receipt/${esc(d.id)}">Receipt</a>` : st.fail ? "" : `<a class="btn sm" href="#/track/${esc(d.id)}">Track</a>`;
    return `<div class="dcard"><div><b>${esc(itemsText(d.food.items))}</b><div class="meta">${d.food.servings} servings · ${esc(d.business_name)}${np ? ` · to ${esc(np)}` : ""}</div></div><div class="acts"><span class="tag ${st.tone}">${esc(st.tag)}</span>${act}</div></div>`;
  }).join(""));
}
const KEYS = ["donation","date","donor","recipient","items","category","servings","weight_lbs","picked_up","delivered","transport"];
$("csv").onclick = () => {
  if(!S) return;
  const f = $("bizFilter").value, name = f === "all" ? null : bizName(f);
  const recs = S.records.filter(r => !name || r.donor === name);
  const lines = [KEYS.join(",")].concat(recs.map(r => KEYS.map(k => `"${String(r[k]).replace(/"/g,'""')}"`).join(",")));
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], {type:"text/csv"}));
  a.download = "donation_records.csv"; a.click();
};

// ---------- receipt ----------
function drawReceipt(){
  const r = S.records.find(x => x.donation === arg);
  if(!r){ setHTML("receipt", `<div class="empty"><b>No receipt yet</b>A receipt is created once the food is delivered.<br><a class="btn primary" href="#/donations">Back to my donations</a></div>`); return; }
  const row = (k, v) => `<dt>${k}</dt><dd>${esc(v)}</dd>`;
  setHTML("receipt", `<div class="receipt"><div class="brandline">Uplink</div><h1>Food donation receipt</h1><p class="law">Edible food recovery record, as kept for California SB 1383</p>
    <dl>${row("Record number", r.donation)}${row("Date", r.date)}${row("Donated by", r.donor)}${row("Given to", r.recipient)}${row("Food", r.items)}${row("Type", r.category)}${row("Servings", r.servings)}${row("Weight", r.weight_lbs + " lbs")}${row("Picked up", clock(r.picked_up))}${row("Delivered", clock(r.delivered))}${row("Transport", TRANSPORT[r.transport] || r.transport)}</dl>
    <div class="acts"><button class="btn primary" type="button" onclick="window.print()">Print receipt</button><a class="btn" href="#/donations">Back</a></div></div>`);
}

route(); refresh(); setInterval(refresh, 1500);

// "Closing up": straight to the camera, the way a register's end-of-day button goes straight to the count
const closingBtn = document.getElementById("closing-up");
if(closingBtn) closingBtn.onclick = () => { location.hash = "#/schedule"; $("file").click(); };
