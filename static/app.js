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
  loadMenu();
  const f = $("bizFilter"), cur = f.value || store.get("uplink_biz") || "all";
  f.innerHTML = `<option value="all">All businesses</option>` + bs.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  f.value = bs.some(b => b.id === cur) ? cur : "all";
}
$("biz").onchange = () => { store.set("uplink_biz", $("biz").value); qty = {}; extras = []; loadMenu(); };
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
  $("sch-pick").hidden = false; $("sch-confirm").hidden = true; setStep(1);
  if(full){ photo = null; $("file").value = ""; $("preview").style.display = "none"; $("dropText").textContent = "Take or choose a photo"; $("analyze").disabled = true; }
}
const isVideo = f => f && /^video\//.test(f.type);
$("file").onchange = e => {
  photo = e.target.files[0]; if(!photo) return;
  const url = URL.createObjectURL(photo), vid = isVideo(photo);
  $("preview").style.display = vid ? "none" : "block"; if(!vid) $("preview").src = url;
  $("previewVid").hidden = !vid; if(vid) $("previewVid").src = url;
  $("dropText").textContent = vid ? "Video added. Tap to change it" : "Photo added. Tap to change it";
  $("analyze").disabled = false;
};
// A video becomes one image: four frames spread across it, tiled 2x2. The vision model is told they are
// views of the same food, so it counts each item once.
function videoSheet(file, frames = 4){
  return new Promise((resolve, reject) => {
    const v = document.createElement("video"); v.muted = true; v.playsInline = true; v.preload = "auto";
    v.src = URL.createObjectURL(file);
    v.onerror = () => reject(new Error("This browser can't read that video. Try an MP4, or take a photo."));
    v.onloadedmetadata = async () => {
      const W = 784, k = W / Math.max(v.videoWidth, v.videoHeight), w = Math.round(v.videoWidth * k), h = Math.round(v.videoHeight * k);
      const c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2;
      const g = c.getContext("2d"); g.fillStyle = "#000"; g.fillRect(0, 0, c.width, c.height);
      const dur = isFinite(v.duration) && v.duration > 0 ? v.duration : 1;
      for(let i = 0; i < frames; i++){
        await new Promise(ok => { v.onseeked = ok; v.currentTime = Math.min(dur - 0.05, dur * (0.1 + 0.8 * i / (frames - 1))); });
        g.drawImage(v, (i % 2) * w, Math.floor(i / 2) * h, w, h);
      }
      URL.revokeObjectURL(v.src);
      c.toBlob(b => b ? resolve(b) : reject(new Error("Couldn't read frames from the video.")), "image/jpeg", 0.88);
    };
  });
}
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
// ---------- allergens: picked by a person; typed ingredients tick the ones they contain ----------
const ALLERGENS = ["dairy","eggs","gluten","nuts","peanuts","soy","fish","shellfish","sesame"];
const ALG_NAME = {nuts:"Tree nuts"};
const ALG_ALIAS = {milk:"dairy", wheat:"gluten", egg:"eggs", "tree nuts":"nuts", "tree nut":"nuts", peanut:"peanuts"};
const CONTAINS = {
  dairy:/\b(milk|cheese|butter|cream|yogurt|ricotta|mozzarella|parmesan|cheddar|feta|whey|ghee|paneer)/,
  eggs:/\b(eggs?|mayo|mayonnaise|aioli|meringue)\b/,
  gluten:/\b(wheat|flour|bread|pasta|noodles?|lasagna|spaghetti|tortillas?|buns?|crust|barley|rye|couscous|croissants?|pastry|cake|cookies?|bagels?|croutons?|seitan)/,
  nuts:/\b(almonds?|walnuts?|pecans?|cashews?|pistachios?|hazelnuts?|macadamias?|pine nuts?)/,
  peanuts:/\bpeanut/, soy:/\b(soy|tofu|edamame|miso|tempeh)/,
  fish:/\b(fish|salmon|tuna|cod|tilapia|anchov|halibut|trout|sardines?)/,
  shellfish:/\b(shrimp|crab|lobster|prawns?|clams?|mussels?|oysters?|scallops?)/, sesame:/\b(sesame|tahini)/,
};
function algNorm(a){ a = String(a).trim().toLowerCase(); return ALG_ALIAS[a] || a; }
function allergensIn(text){ const t = String(text).toLowerCase(); return ALLERGENS.filter(a => CONTAINS[a].test(t)); }
function chipsHTML(sel, attr = ""){
  return [...ALLERGENS, ...sel.filter(a => !ALLERGENS.includes(a))].map(a => { const on = sel.includes(a);
    return `<button type="button" class="chip${on ? " on" : ""}" aria-pressed="${on}" data-a="${esc(a)}" ${attr}>${esc(ALG_NAME[a] || cap(a))}</button>`; }).join("");
}
function splitList(v){ return String(v).split(",").map(s => s.trim()).filter(Boolean); }

function readForm(){
  const num = id => +$(id).value;
  return {
    items: $("items").value.split(",").map(s=>s.trim()).filter(Boolean),
    servings: num("servings"), safe_minutes: num("safe"),
    weight_lbs: [num("wlo"), num("whi")], category: $("category").value,
    allergens: $("allergens").value.split(",").map(s=>s.trim().toLowerCase()).filter(Boolean),
    ingredients: splitList($("ingredients").value),
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
function setAllergens(list){ $("allergens").value = [...new Set(list.map(algNorm))].join(", "); $("algChips").innerHTML = chipsHTML(readForm().allergens); drawSummary(); }
$("algChips").onclick = e => {
  const b = e.target.closest("button[data-a]"); if(!b) return;
  const cur = readForm().allergens;
  setAllergens(cur.includes(b.dataset.a) ? cur.filter(a => a !== b.dataset.a) : [...cur, b.dataset.a]);
};
$("ingredients").addEventListener("input", () => setAllergens([...readForm().allergens, ...allergensIn($("ingredients").value)]));
function notice(kind, text){ const n = $("notice"); n.hidden = !text; n.className = "notice " + (kind || ""); n.textContent = text || ""; }
function openForm(open){ $("form").hidden = !open; $("edit").setAttribute("aria-expanded", String(open)); $("edit").textContent = open ? "Hide details" : "Edit details"; }
$("edit").onclick = () => openForm($("form").hidden);
function showSource(r){
  const f = r.food || {};
  $("servings").classList.remove("check"); $("items").classList.remove("check");
  if(r.source === "demo"){ notice("warn", "This is a sample result (demo mode), not your photo. Please edit anything that's wrong."); }
  else if(r.source === "fallback"){ notice("bad", "We couldn't read this photo. Please fill in what you have."); openForm(true); }
  else if(f.off_menu && f.off_menu.length){ notice("warn", `Not on your menu: ${f.off_menu.join(", ")}. Please check its ingredients and allergens below, then untick "I'm not sure".${f.menu_matches ? ` The other ${f.menu_matches === 1 ? "item" : f.menu_matches + " items"} matched your menu.` : ""}`); openForm(true); }
  else if(f.allergens_unverified){ notice("warn", `We couldn't confirm the allergens from the photo. Please check the ingredients and allergens below, then untick "I'm not sure".`); openForm(true); }
  else if(f.menu_matches){ notice("ok", `We matched ${f.menu_matches === 1 ? "1 item" : f.menu_matches + " items"} to your menu, so the allergens come from your recipes. Please check the amounts.`); }
  else if(f.confidence === "high"){ notice("ok", "We read your photo. Please check that it looks right."); }
  else { notice("warn", "We're not sure about the amount. Please check the number of servings."); openForm(true); }
}
function fill(f){
  $("items").value = f.items.join(", "); $("servings").value = f.servings; $("safe").value = f.safe_minutes;
  $("wlo").value = f.weight_lbs[0]; $("whi").value = f.weight_lbs[1]; $("category").value = f.category;
  $("ingredients").value = (f.ingredients || []).join(", "); setAllergens(f.allergens);
  $("cold").checked = !!f.needs_cold; $("unsure").checked = !!f.allergens_unverified;
  $("err").hidden = true; openForm(false); drawSummary();
  $("sch-pick").hidden = true; $("sch-confirm").hidden = false; setStep(2); window.scrollTo(0, 0);
}
$("analyze").onclick = async () => {
  $("analyze").disabled = true; $("analyze").textContent = isVideo(photo) ? "Reading your video…" : "Reading your photo…";
  const fd = new FormData(); fd.append("business", $("biz").value);
  if(isVideo(photo)){
    try{ fd.append("photo", await videoSheet(photo), "frames.jpg"); fd.append("frames", "4"); }
    catch(e){ $("analyze").textContent = "Continue"; $("analyze").disabled = false; $("dropText").textContent = e.message; return; }
  } else fd.append("photo", await shrink(photo), "photo.jpg");
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
let tmap = null, tlayers = null, tFor = null, tTilesFailed = 0;
function destroyMap(){ if(tmap){ tmap.remove(); tmap = null; } tFor = null; _html.trackTop = _html.trackBottom = undefined; $("track").innerHTML = ""; }
function addTiles(m){
  // Standard OpenStreetMap tiles; app.css desaturates and lightens them so markers stand out.
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom:18, attribution:"© OpenStreetMap contributors"}).addTo(m);
}
// small, exact markers: the icon box matches the drawn size, so each one sits right on its spot
function mkIcon(cls){ return L.divIcon({className:"", iconSize:[16,16], iconAnchor:[8,8], html:`<div class="mk ${cls}"></div>`}); }
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
  const np = d.plan && d.plan.np_name;
  const done = d.status === "delivered";
  const segs = STEPS.map((_, i) => { const n = i + 1; return `<i class="${st.fail ? "" : n < st.step || (n === st.step && done) ? "on" : n === st.step ? "now" : ""}"></i>`; }).join("");
  let question = "";
  if(d.status === "awaiting_info"){
    question = `<div class="question" role="alert"><h2>Is this food free of ${esc(d.asked_about || "the allergens we asked about")}?</h2><p>Some shelters can't take certain allergens. If you're not sure, say so and we'll stay on the safe side.</p>
      <button class="btn primary" type="button" id="q-yes">Yes, that's everything</button><button class="btn" type="button" id="q-no">Not sure</button></div>`;
  }
  setIn("trackTop", `<div class="trk-title"><h1>${esc(st.head)}</h1><span class="id">#${esc(d.id)}</span></div>${st.sub ? `<p class="trk-sub">${esc(st.sub)}</p>` : ""}
    <div class="seg" aria-hidden="true">${segs}</div><div class="seg-lbl"><span>Received</span><span>${esc(st.fail ? "Not delivered" : st.step > 1 && st.step < STEPS.length ? STEPS[st.step - 1] : "")}</span><span>Delivered</span></div>${question}`);
  if(question){ $("q-yes").onclick = () => answer(d, true); $("q-no").onclick = () => answer(d, false); }

  const rec = done && S.records.find(r => r.donation === d.id);
  const arrive = done ? (rec || {}).delivered : d.plan && d.plan.arrive_hhmm;
  let driver = "";
  if(d.plan && !st.fail){
    const name = d.plan.driver_name || "";
    const kind = /paid|courier/i.test(name) ? "Courier" : /van/i.test(name) ? "Shelter's own van" : "Volunteer driver";
    const leg = done ? {t:`Delivered to ${np}`, s:`at ${clock(arrive)}`} : d.picked ? {t:`On the way to ${np}`, s:"Your food is in the car"} : d.status === "en_route" ? {t:"Coming to pick it up", s:`Then on to ${np}`} : {t:`Waiting for ${np} to confirm`, s:"The driver leaves once they say yes"};
    driver = `<div class="sheet"><div class="drv"><span class="avatar" aria-hidden="true">${esc(firstName(name).charAt(0))}</span><div class="who"><b>${esc(firstName(name))}</b><small>${kind}</small></div>
      ${arrive ? `<div class="eta"><b>${esc(clock(arrive))}</b><small>${done ? "delivered" : "arrives"}</small></div>` : ""}</div>
      <div class="leg"><span class="ic" aria-hidden="true">${TRUCK}</span><div><b>${esc(leg.t)}</b><small>${esc(leg.s)}</small></div></div></div>`;
  }
  const order = `<div class="sheet order"><h2>Your donation</h2>
    <div class="row"><span>${esc(itemsText(d.food.items))}</span><span>×${d.food.servings}</span></div>
    <div class="row"><span>From</span><span>${esc(d.business_name)}</span></div>
    ${d.food.allergens.length ? `<div class="row"><span>Allergens</span><span>${esc(d.food.allergens.join(", "))}</span></div>` : ""}
    ${np ? `<div class="dash"></div><div class="row"><span>Shelter</span><span>${esc(np)}</span></div>` : ""}</div>`;
  const items = whyItems(d);
  const why = items.length ? `<div class="sheet why"><h2>Updates</h2>
    <ol class="feed">${items.map((x, i) => `<li class="${seenWhy.has(d.id + x.k) ? "" : "new"}"><span class="dotx ${x.cls || ""}" aria-hidden="true">${esc(x.mark)}</span><div><b>${esc(x.title)}</b>${x.detail ? `<p>${esc(x.detail)}</p>` : ""}${x.time && (i === 0 || items[i-1].time !== x.time) ? `<time>${esc(clock(x.time))}</time>` : ""}</div></li>`).join("")}</ol></div>` : "";
  items.forEach(x => seenWhy.add(d.id + x.k));
  const after = done ? `<a class="btn primary xl" href="#/receipt/${esc(d.id)}">View your receipt</a>`
    : st.fail ? `<a class="btn primary xl" href="#/schedule">Schedule another pickup</a>` : "";
  setIn("trackBottom", `${driver}${order}${why}${after}`);
  drawTrackMap(d);
}

// ---- "Updates": what happened for this pickup, in plain words (the agent debate stays on /ops) ----
const seenWhy = new Set();
const TRUCK = `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h11v9H3zM14 10h4l3 3v3h-7z"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/></svg>`;
function npOf(planId){ if(!planId) return null; const n = S.nonprofits.find(x => x.id === planId.split("|")[0]); return n ? n.name : null; }
function firstSentence(t){ const m = String(t || "").replace(/^R\d+ · /, "").match(/^.*?[.!?](\s|$)/); return (m ? m[0] : String(t || "")).trim(); }
function whyItems(d){
  const out = [];
  const net = (S.network || []).filter(m => m.donation === d.id);
  const feed = (S.feed || []).filter(f => f.donation === d.id);
  const ann = net.find(m => m.kind === "announce");
  if(ann){ const k = (ann.text.match(/(\d+) shelters? can safely/) || [])[1];
    out.push({k:"ann", mark:"1", title:"Shared with shelters nearby", detail: k ? `${k} of them can safely take this food right now.` : "We checked which shelters can safely take it.", time:ann.time}); }
  const replies = net.filter(m => ["accept","counter","decline"].includes(m.kind) && m.from !== "coordinators");
  if(replies.length){ const c = kind => replies.filter(m => m.kind === kind).length;
    const parts = [c("accept") && `${c("accept")} said yes`, c("counter") && `${c("counter")} offered to take part of it`, c("decline") && `${c("decline")} said no`].filter(Boolean);
    out.push({k:"rep", mark:"2", title:"Shelters answered", detail: parts.join(", ") + ".", time:replies[0].time}); }
  const bids = net.filter(m => m.kind === "bid");
  if(bids.length) out.push({k:"bid", mark:"3", title:`${bids.length} drivers offered a ride`, detail:"Volunteers, couriers and shelter vans sent their time and price.", time:bids[0].time});
  const res = feed.filter(f => f.type === "result").pop();
  if(res && d.plan) out.push({k:"res", mark:"✓", cls:"go", title:`Matched with ${d.plan.np_name}`, detail:`The best fit right now for this food. Arrives about ${clock(d.plan.arrive_hhmm)}.`, time:res.time});
  feed.filter(f => f.type === "contact").forEach((f, i) => out.push({k:"c" + i, mark:"☎", title:f.text.split(".")[0] + ".", detail:"", time:f.time}));
  if(d.picked) out.push({k:"pick", mark:"→", cls:"go", title:"Picked up", detail:`On the way to ${d.plan ? d.plan.np_name : "the shelter"}.`});
  const del = feed.find(f => f.type === "delivered" || /delivered to/.test(f.text));
  if(d.status === "delivered") out.push({k:"del", mark:"✓", cls:"go", title:"Delivered", detail:"Your donation record is ready.", time: del && del.time});
  return out;
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
  // once delivered, the driver has moved on to other trips: show where they dropped this food off
  const drvAt = d.status === "delivered" && d.dest ? [d.dest.lat, d.dest.lng] : drv && [drv.lat, drv.lng];
  put("drv", showDrv ? drvAt : null, "m-drv", drv ? firstName(drv.name) : "");
  if(tlayers.line){ tlayers.line.remove(); delete tlayers.line; }
  if(d.plan && d.dest){
    const pts = showDrv && d.status === "en_route" ? (d.picked ? [[drv.lat,drv.lng],[d.dest.lat,d.dest.lng]] : [[drv.lat,drv.lng],[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]]) : [[d.origin.lat,d.origin.lng],[d.dest.lat,d.dest.lng]];
    tlayers.line = L.polyline(pts, {color:"#2563eb", weight:3, opacity:.85, lineCap:"round", lineJoin:"round"}).addTo(tmap);
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

// "Closing up": straight to the camera, the way a register's end-of-day button goes straight to the count.
// Only on touch devices; on a laptop the picker is a file browser, so just open the photo tab
const closingBtn = document.getElementById("closing-up");
const touchDevice = matchMedia("(pointer: coarse)").matches;
if(closingBtn) closingBtn.onclick = () => { location.hash = "#/schedule"; showTab("photo"); if(touchDevice) $("file").click(); };

// ---------- your menu: tap + on what's left; allergens come from the recipes ----------
let menuItems = [], menuFor = null, qty = {}, extras = [];   // extras: one-time leftovers that aren't on the menu
const KIND = {"hot prepared":"Hot", "cold prepared":"Cold", packaged:"Packaged", produce:"Produce"};
function showTab(which){
  ["menu","say","photo"].forEach(t => { $("tab-" + t).setAttribute("aria-selected", String(t === which)); $("sch-" + t).hidden = t !== which; });
}
$("tab-menu").onclick = () => showTab("menu");
$("tab-say").onclick = () => showTab("say");
$("tab-photo").onclick = () => showTab("photo");
async function loadMenu(){
  const biz = $("biz").value; if(!biz) return;
  try{ menuItems = (await (await fetch("/api/menu/" + encodeURIComponent(biz))).json()).items || []; }catch(e){ menuItems = []; }
  if(menuFor !== biz){ menuFor = biz; showTab(menuItems.length ? "menu" : "photo"); }
  drawMenu();
}
function qtyButtons(name, attr, n){
  return `<div class="qty"><button type="button" aria-label="One fewer ${esc(name)}" ${attr} data-k="-1" ${n ? "" : "disabled"}>−</button>
      <output aria-live="polite">${n}</output><button type="button" aria-label="One more ${esc(name)}" ${attr} data-k="1">+</button></div>`;
}
const KIND_OPTS = Object.entries({"hot prepared":"Hot, prepared", "cold prepared":"Cold, prepared", packaged:"Packaged", produce:"Produce"});
function extraRow(x, i){
  const serves = x.serves > 1 ? `Serves ${x.serves} each` : `1 serving each`;
  const status = x.confirmed ? `<span class="checked">Allergens checked by you</span>` : `<span class="off-menu">Not on your menu · check allergens</span>`;
  const row = `<li class="on"><div class="mi"><b>${esc(x.name)}</b><small>${serves} · ${x.allergens.length ? esc(x.allergens.join(", ")) : "no allergens picked"}</small>
      <span class="kind">${KIND[x.category] || ""}${x.cold ? ", keep cold" : ""} · ${status}</span>
      <button type="button" class="linkbtn x-open" data-x="${i}" aria-expanded="${!!x.open}">${x.open ? "Done" : "Check details"}</button></div>
      ${qtyButtons(x.name, `data-x="${i}"`, x.qty)}</li>`;
  if(!x.open) return row;
  return row + `<li class="x-edit" data-x="${i}">
      ${!x.sure && !x.confirmed ? `<p class="notice warn">We couldn't tell its allergens for sure. Add the ingredients or tap every allergen it contains.</p>` : ""}
      <label>What is it?<input data-f="name" value="${esc(x.name)}" autocomplete="off"></label>
      <div class="grid2"><label>Servings each<input data-f="serves" type="number" min="1" inputmode="numeric" value="${x.serves}"></label>
      <label>Type of food<select data-f="category">${KIND_OPTS.map(([v, l]) => `<option value="${v}"${v === x.category ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <label>Ingredients (separate with commas)<input data-f="ingredients" value="${esc(x.ingredients.join(", "))}" autocomplete="off" placeholder="for example: pasta, ricotta, spinach"></label>
      <span class="lbl">Allergens it contains</span><div class="chips" role="group" aria-label="Allergens in ${esc(x.name)}">${chipsHTML(x.allergens)}</div>
      <label class="check"><input type="checkbox" data-f="confirmed" ${x.confirmed ? "checked" : ""}><span>I've checked: these are all its allergens</span></label>
      <label class="check"><input type="checkbox" data-f="save" ${x.save ? "checked" : ""} ${x.confirmed ? "" : "disabled"}><span>Save to my menu for next time<small>Leave this off for a one-time leftover.</small></span></label>
    </li>`;
}
function drawMenu(){
  const once = extras.map(extraRow).join("");
  $("menuList").innerHTML = once + menuItems.map(m => {
    const n = qty[m.id] || 0;
    const serves = m.serves > 1 ? `Serves ${m.serves} per ${esc(m.unit)}` : `1 serving each`;
    return `<li class="${n ? "on" : ""}"><div class="mi"><b>${esc(m.name)}</b><small>${serves}${m.allergens.length ? " · " + esc(m.allergens.join(", ")) : ""}</small>
      <span class="kind">${KIND[m.category] || ""}${m.cold ? ", keep cold" : ""}${m.added ? " · added by you" : ""}</span></div>
      ${qtyButtons(m.name, `data-id="${esc(m.id)}"`, n)}</li>`;
  }).join("") || (once ? "" : `<li class="none">Your menu is empty. Add what you have below, or take a photo.</li>`);
  drawTotal();
}
function drawTotal(){
  const picked = menuItems.filter(m => qty[m.id] > 0);
  const count = picked.length + extras.length;
  const servings = picked.reduce((t, m) => t + qty[m.id] * m.serves, 0) + extras.reduce((t, x) => t + x.qty * x.serves, 0);
  const unchecked = extras.filter(x => !x.confirmed).length;
  $("menuTotal").hidden = !count || !$("addForm").hidden;   // don't cover the add form
  $("mtCount").textContent = count === 1 ? "1 item" : `${count} items`;
  $("mtServ").textContent = `About ${servings} servings` + (unchecked ? ` · allergens not checked for ${unchecked}` : "");
}
function addExtra(e, open){
  extras.push({name:e.name, qty:e.qty || 1, serves:e.serves || 1, category:e.category || "hot prepared", cold:!!e.cold,
    ingredients:e.ingredients || [], allergens:(e.allergens || []).map(algNorm), sure:!!e.sure, confirmed:false, save:false, open});
}
$("menuList").onclick = e => {
  const ed = e.target.closest(".x-edit"), x = ed && extras[+ed.dataset.x];
  const chip = e.target.closest("button[data-a]");
  if(chip && x){
    const a = chip.dataset.a; x.allergens = x.allergens.includes(a) ? x.allergens.filter(v => v !== a) : [...x.allergens, a];
    drawMenu(); return;
  }
  const o = e.target.closest(".x-open");
  if(o){ const y = extras[+o.dataset.x]; y.open = !y.open; drawMenu(); return; }
  const b = e.target.closest("button[data-k]"); if(!b) return;
  if(b.dataset.x !== undefined){   // a one-time item: down to zero takes it off the pickup
    const x = extras[+b.dataset.x]; x.qty = Math.max(0, x.qty + (+b.dataset.k));
    if(!x.qty) extras.splice(+b.dataset.x, 1);
  } else qty[b.dataset.id] = Math.max(0, (qty[b.dataset.id] || 0) + (+b.dataset.k));
  drawMenu();
};
$("menuList").addEventListener("input", e => {   // typing in a one-time item's details: no redraw, so focus stays
  const ed = e.target.closest(".x-edit"), f = e.target.dataset.f; if(!ed || !f || e.target.type === "checkbox") return;
  const x = extras[+ed.dataset.x];
  if(f === "serves") x.serves = Math.max(1, Math.min(200, +e.target.value || 1));
  else if(f === "ingredients"){
    x.ingredients = splitList(e.target.value);
    const more = allergensIn(e.target.value).filter(a => !x.allergens.includes(a));
    if(more.length){ x.allergens = [...x.allergens, ...more]; ed.querySelector(".chips").innerHTML = chipsHTML(x.allergens); }
  }
  else if(f === "category"){ x.category = e.target.value; x.cold = x.category === "cold prepared"; }
  else x[f] = e.target.value.slice(0, 60);
  drawTotal();
});
$("menuList").addEventListener("change", e => {
  const ed = e.target.closest(".x-edit"), f = e.target.dataset.f; if(!ed || !f) return;
  const x = extras[+ed.dataset.x];
  if(e.target.type === "checkbox"){ x[f] = e.target.checked; if(f === "confirmed" && !x.confirmed) x.save = false; }
  if(!x.name.trim()) x.name = "Food";
  drawMenu();
});
$("addToggle").onclick = () => { const f = $("addForm"); f.hidden = !f.hidden; $("addToggle").setAttribute("aria-expanded", String(!f.hidden)); drawMenu(); if(!f.hidden) $("newName").focus(); };
$("addSave").onclick = async () => {
  $("addErr").hidden = true;
  const text = $("newName").value.trim();
  if(!text){ $("addErr").textContent = "Say what it is."; $("addErr").hidden = false; return; }
  $("addSave").disabled = true; $("addSave").textContent = "Filling in the details…";
  let j = null;
  try{ j = await post("/api/menu/" + encodeURIComponent($("biz").value) + "/describe", {text}); }catch(e){}
  $("addSave").disabled = false; $("addSave").textContent = "Add to this pickup";
  if(j && (j.lines.length || j.extras.length)){
    j.lines.forEach(l => qty[l.id] = (qty[l.id] || 0) + l.qty);   // it was on the menu after all
    j.extras.forEach(e => addExtra(e, true));
  } else addExtra({name:text.slice(0, 60)}, true);   // no estimate: the person fills it in
  $("newName").value = ""; $("addForm").hidden = true; $("addToggle").setAttribute("aria-expanded","false");
  drawMenu();
};
$("menuConfirm").onclick = async () => {
  const lines = Object.entries(qty).filter(([, n]) => n > 0).map(([id, n]) => ({id, qty:n}));
  if(!lines.length && !extras.length) return;
  $("menuConfirm").disabled = true; $("menuConfirm").textContent = "Scheduling…"; $("menuErr").hidden = true;
  try{
    const r = await post("/api/donate/menu", {business:$("biz").value, lines, extras});
    store.set("uplink_biz", $("biz").value); store.set("uplink_last", r.ids[0]); try{ sessionStorage.setItem("uplink_new", r.ids[0]); }catch(e){}
    qty = {}; extras = []; drawMenu();
    location.hash = "#/track/" + r.ids[0];
    refresh();
  }catch(e){ $("menuErr").textContent = "We couldn't schedule this. Check your connection and try again."; $("menuErr").hidden = false; }
  $("menuConfirm").disabled = false; $("menuConfirm").textContent = "Schedule pickup";
};

// ---------- say it: record -> ElevenLabs Scribe -> Claude matches it to the menu -> filled-in menu ----------
let sayRec = null;
function sayState(label, status, on){ $("sayLabel").textContent = label; $("sayStatus").textContent = status || ""; $("sayBtn").classList.toggle("rec", !!on); }
async function sendSaid(form){
  form.append("business", $("biz").value);
  sayState("Matching to your menu…", "", false); $("sayBtn").disabled = true;
  let r, j;
  try{ r = await fetch("/api/voice/donation", {method:"POST", body:form}); j = await r.json(); }
  catch(e){ j = {error:"Couldn't reach Uplink. Check the connection and try again."}; }
  $("sayBtn").disabled = false;
  if(!r || !r.ok){ sayState("Tap to talk", j.error || "Try again.", false); return; }
  if(!j.lines.length && !j.extras.length){ sayState("Tap to talk", `Heard "${j.heard}", but nothing on your menu matched. Try naming the items, or tap them on the menu.`, false); return; }
  j.lines.forEach(l => qty[l.id] = (qty[l.id] || 0) + l.qty);
  j.extras.forEach(e => addExtra(e, !e.sure));   // not on the menu: on this pickup only; details open when unsure
  const extra = j.extras.length ? ` Not on your menu, added for this pickup only: ${j.extras.map(e => `${e.name} ×${e.qty}`).join(", ")}. Please check ${j.extras.length > 1 ? "their" : "its"} ingredients and allergens.` : "";
  $("sayNotice").textContent = `Heard: "${j.heard}". We filled in ${j.lines.length === 1 ? "1 item" : j.lines.length + " items"} from your menu. Check the amounts, then schedule.${extra}`;
  $("sayNotice").hidden = false;
  sayState("Tap to talk", "", false);
  showTab("menu"); drawMenu(); window.scrollTo(0, 0);
}
$("sayBtn").onclick = async () => {
  if(sayRec && sayRec.state === "recording"){ sayRec.stop(); return; }
  const eleven = S && S.mode && S.mode.voice === "elevenlabs";
  if(!eleven){   // no ElevenLabs key on the server: the browser's own speech recognition, if it has one
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SR){ sayState("Tap to talk", "Voice needs an ElevenLabs key on the server, or Chrome. You can tap items on the menu instead.", false); return; }
    const sr = new SR(); sr.lang = "en-US"; sayState("Listening… tap to stop", "", true);
    sr.onresult = e => { const f = new FormData(); f.append("text", e.results[0][0].transcript); sendSaid(f); };
    sr.onerror = () => sayState("Tap to talk", "Didn't catch that. Try again.", false);
    sr.onend = () => { if($("sayBtn").classList.contains("rec")) sayState("Tap to talk", "", false); };
    sr.start(); return;
  }
  let stream;
  try{ stream = await navigator.mediaDevices.getUserMedia({audio:true}); }
  catch(e){ sayState("Tap to talk", "Microphone blocked. Allow it in the browser (works on localhost or https).", false); return; }
  const chunks = [];
  sayRec = new MediaRecorder(stream);
  sayRec.ondataavailable = e => chunks.push(e.data);
  sayRec.onstop = () => {
    stream.getTracks().forEach(t => t.stop());
    const type = sayRec.mimeType || "audio/webm";
    const f = new FormData(); f.append("audio", new Blob(chunks, {type}), type.includes("mp4") ? "say.mp4" : "say.webm");
    sendSaid(f);
  };
  sayRec.start(); sayState("Listening… tap when done", "Recording stops by itself after 15 seconds.", true);
  setTimeout(() => { if(sayRec && sayRec.state === "recording") sayRec.stop(); }, 15000);
};

