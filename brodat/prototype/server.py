#!/usr/bin/env python3
"""
Aplicatia web polaroid -> broderie (Etapa 1).

Porneste cu:  python3 prototype/server.py
apoi deschide http://localhost:8765 in browser.

Flux: upload -> detectie decupaj (ajustabil cu mouse-ul) -> generare in
paralel a celor 3 stiluri -> comparatie + descarcare .pes/.dst.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_OUT = ROOT / "out" / "web"
PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")  # pe Railway: HOST="::" (rețeaua privată e IPv6)
STYLES = [("mix", "Mix — gravură"), ("poster", "Poster — culori"),
          ("color", "Color — culori + linii"), ("sketch", "Sketch — linii"),
          ("linie", "Linie — contur minimal"), ("silueta", "Siluetă — ștampilă"),
          ("hasura", "Hașură — gravură minimală"),
          ("amprenta", "Amprentă — contururi concentrice"),
          ("val", "Val — linii curgătoare"), ("duoton", "Duoton — pop-art"),
          ("cruce", "Cruciulițe — goblen"), ("cristal", "Cristal — fațete")]
FILL_STYLES = ("mix", "poster", "color")   # stiluri cu umpleri (editabile)

PAGE = """<!doctype html>
<html lang="ro"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polaroid → Broderie</title>
<style>
  :root { --bg:#f4f1ea; --card:#fffdf8; --ink:#2b2926; --acc:#8c2f39; }
  * { box-sizing:border-box; margin:0; }
  body { font:15px/1.45 Georgia, serif; background:var(--bg); color:var(--ink);
         height:100vh; overflow:hidden; display:flex; flex-direction:column;
         padding:12px 18px; }
  .hdr { display:flex; align-items:baseline; gap:14px; margin-bottom:10px; }
  h1 { font-size:1.25rem; }
  .sub { color:#6b675f; font-size:.85rem; }
  .wrap { flex:1; min-height:0; display:grid;
          grid-template-columns:280px 1fr; gap:14px; }
  @media (max-width:900px){
    body { height:auto; overflow:auto; }
    .wrap { grid-template-columns:1fr; }
  }
  .card { background:var(--card); border:1px solid #e4ded2; border-radius:10px;
          padding:12px; min-height:0; }
  .card.left { overflow-y:auto; }
  .card.right { display:flex; flex-direction:column; }
  #drop { border:2px dashed #c9c1b0; border-radius:8px; padding:10px;
          text-align:center; cursor:pointer; transition:.15s; font-size:.85rem; }
  #drop.on, #drop:hover { border-color:var(--acc); background:#faf5ef; }
  #cropbox { display:none; margin-top:8px; }
  #cropcv { max-height:32vh; max-width:100%; display:block; margin:0 auto;
            border-radius:6px; cursor:crosshair; touch-action:none;
            box-shadow:0 2px 8px rgba(0,0,0,.15); }
  .mini { font-size:.78rem; color:#6b675f; }
  .btnrow { display:flex; gap:6px; margin-top:5px; }
  .btn2 { flex:1; padding:4px; font:inherit; font-size:.78rem; cursor:pointer;
          background:#efe9dc; border:1px solid #d8d0bf; border-radius:6px; }
  label { display:block; margin:8px 0 2px; font-size:.82rem; color:#6b675f; }
  select, input[type=range], input[type=text] { width:100%; font:inherit; }
  select, input[type=text] { font-size:.85rem; }
  input[type=text] { padding:6px; border:1px solid #d8d0bf; border-radius:6px;
                     background:#fffdf8; }
  .val { float:right; font-variant-numeric:tabular-nums; }
  button#go { width:100%; margin-top:10px; padding:9px; font:inherit;
              background:var(--acc); color:#fff; border:0; border-radius:8px;
              cursor:pointer; }
  button#go:disabled { opacity:.5; cursor:wait; }
  #results { flex:1; min-height:0; display:grid; gap:10px;
             grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); }
  @media (max-width:900px){
    #results { grid-template-columns:1fr 1fr; }
  }
  .res { background:#faf7f0; border:1px solid #e4ded2; border-radius:8px;
         padding:8px; display:flex; flex-direction:column; min-height:0; }
  .res h3 { font-size:.85rem; margin-bottom:6px; }
  .res img { width:100%; flex:1; min-height:0; object-fit:contain;
             border-radius:6px; }
  .res .meta { font-size:.72rem; color:#6b675f; margin-top:4px; }
  .dl { display:inline-block; margin:5px 4px 0 0; padding:4px 8px;
        background:var(--ink); color:#fff; border-radius:6px;
        text-decoration:none; font-size:.72rem; }
  details { margin-top:4px; } summary { cursor:pointer; font-size:.75rem;
        color:#6b675f; }
  pre { font:10px/1.4 monospace; white-space:pre-wrap; background:#f2eee3;
        border-radius:6px; padding:6px; margin-top:4px; max-height:110px;
        overflow:auto; }
  #hint { color:#6b675f; text-align:center; padding:60px 10px; }
  .res img { cursor:zoom-in; }
  #lightbox { display:none; position:fixed; inset:0; z-index:50;
              background:rgba(20,18,15,.88); cursor:zoom-out;
              align-items:center; justify-content:center; padding:24px; }
  #lightbox.on { display:flex; }
  #lightbox img { max-width:96vw; max-height:88vh; border-radius:8px;
                  box-shadow:0 8px 40px rgba(0,0,0,.6); background:#fffdf8; }
  #lbTitle { position:fixed; top:14px; left:0; right:0; text-align:center;
             color:#f4f1ea; font-size:1rem; pointer-events:none; }
  .spin { display:none; text-align:center; padding:40px; }
  .spin.on { display:block; }
  .res h3 { display:flex; justify-content:space-between; align-items:center; }
  .mini2 { border:1px solid #d8d0bf; background:#efe9dc; border-radius:5px;
           cursor:pointer; font-size:.8rem; padding:2px 7px; }
  #tprev { font-family:'Ink Free','Segoe Script','Comic Sans MS',cursive;
           font-size:1.1rem; min-height:1.2em; color:#3b3833; margin-top:2px; }
  #editor, #eraser { display:none; position:fixed; inset:0; z-index:60;
            padding:20px; background:rgba(20,18,15,.8); align-items:center;
            justify-content:center; }
  #editor.on, #eraser.on { display:flex; }
  #edbox, #erbox { background:var(--card); border-radius:10px; padding:16px;
           max-width:660px; width:100%; max-height:96vh; overflow:auto; }
  #edcv, #ercv { width:100%; max-height:66vh; object-fit:contain;
          border-radius:6px; cursor:crosshair; touch-action:none;
          image-rendering:pixelated; }
  #edpal { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; }
  .swatch { width:30px; height:30px; border-radius:6px; padding:0;
            border:2px solid #d8d0bf; cursor:pointer; }
  .swatch.sel { border-color:var(--acc); box-shadow:0 0 0 2px var(--acc); }
  .swatch.gol { background:repeating-linear-gradient(45deg, #fff, #fff 4px,
                #e8e2d5 4px, #e8e2d5 8px); font-size:.8rem; }
  .btn2.sel { border-color:var(--acc); box-shadow:inset 0 0 0 1px var(--acc); }
</style></head><body>
<div class="hdr"><h1>Polaroid → Broderie 🪡</h1>
<span class="sub">Încarcă un polaroid, ajustează decupajul, compară stilurile și descarcă .pes.</span></div>
<div class="wrap">
  <div class="card left">
    <div id="drop">📷 Trage poza aici sau apasă<br><small>jpg / png</small></div>
    <input id="file" type="file" accept="image/*" hidden>
    <div id="cropbox">
      <label style="margin-top:10px">Decupaj — trage de colțuri sau de mijloc</label>
      <canvas id="cropcv"></canvas>
      <div class="btnrow">
        <button class="btn2" id="cropAuto">↺ Auto</button>
        <button class="btn2" id="cropInner">Doar poza</button>
        <button class="btn2" id="cropFull">Toată imaginea</button>
      </div>
    </div>
    <label>Mărime <span class="val" id="sizeV">95 mm</span></label>
    <input id="size" type="range" min="50" max="95" value="95">
    <label>Număr de culori <span class="val" id="colorsV">10</span></label>
    <input id="colors" type="range" min="4" max="10" value="10">
    <label>Claritate <span class="val" id="clarityV">normală</span></label>
    <input id="clarity" type="range" min="0.5" max="2.5" step="0.25" value="1">
    <label>Ramă polaroid cusută</label>
    <select id="frame">
      <option value="lines" selected>Doar contur (linii)</option>
      <option value="full">Plină, cusută cu negru</option>
      <option value="none">Fără ramă</option>
    </select>
    <label>Text pe banda de jos (opțional, scris de mână)</label>
    <input id="text" type="text" maxlength="40" placeholder="ex: vara la mare, 2025">
    <div id="tprev"></div>
    <button id="go" disabled>Generează toate stilurile</button>
  </div>
  <div class="card right">
    <div id="hint">Stilurile apar aici, unul lângă altul.</div>
    <div class="spin" id="spin">⏳ Se cos digital stilurile…</div>
    <div id="results"></div>
  </div>
</div>
<div id="lightbox"><div id="lbTitle"></div><img id="lbImg" alt=""></div>
<div id="editor"><div id="edbox">
  <h3 style="margin-bottom:6px">Editor de regiuni ✏️</h3>
  <p class="mini">Alege o culoare și pictează peste zone ca să le unești sau
  să le corectezi; ✕ = material gol (nu se coase). Se aplică pe stilurile cu
  umpleri (mix, poster, color).</p>
  <canvas id="edcv"></canvas>
  <div id="edpal"></div>
  <div class="btnrow" style="align-items:center">
    <label class="mini" style="margin:0; flex:1">Pensulă
      <input id="edbrush" type="range" min="3" max="40" value="12"></label>
    <label class="mini" style="margin:0; flex:1">Poză ↔ hartă
      <input id="edalpha" type="range" min="10" max="100" value="60"></label>
    <button class="btn2" id="edundo">↶ Undo</button>
    <button class="btn2" id="edclose">Închide</button>
    <button class="btn2" id="edapply"
            style="background:var(--acc); color:#fff">Aplică ✓</button>
  </div>
</div></div>
<div id="eraser"><div id="erbox">
  <h3 style="margin-bottom:6px">Editor de linii 🧽✏️</h3>
  <p class="mini">Radiera șterge liniile pe loc (umplerile nu sunt afectate);
  creionul desenează linii noi, cusute cu fir închis. Se aplică pe mix,
  sketch și color.</p>
  <canvas id="ercv"></canvas>
  <div class="btnrow" style="align-items:center">
    <button class="btn2 sel" id="erToolE">🧽 Șterge</button>
    <button class="btn2" id="erToolD">✏️ Desenează</button>
    <label class="mini" style="margin:0; flex:1">Grosime
      <input id="erbrush" type="range" min="4" max="40" value="14"></label>
    <button class="btn2" id="erundo">↶ Undo</button>
    <button class="btn2" id="erclose">Închide</button>
    <button class="btn2" id="erapply"
            style="background:var(--acc); color:#fff">Aplică ✓</button>
  </div>
</div></div>
<script>
const $ = id => document.getElementById(id);
let job = null, imgEl = null, rect = null, autoRect = null, innerRect = null,
    iw = 0, ih = 0;
$('size').oninput = e => $('sizeV').textContent = e.target.value + ' mm';
$('colors').oninput = e => $('colorsV').textContent = e.target.value;
$('clarity').oninput = e => { const v = +e.target.value;
  $('clarityV').textContent = v < 0.9 ? 'subtilă' : v <= 1.1 ? 'normală'
                              : v <= 1.75 ? 'puternică' : 'maximă'; };
$('drop').onclick = () => $('file').click();
$('drop').ondragover = e => { e.preventDefault(); $('drop').classList.add('on'); };
$('drop').ondragleave = () => $('drop').classList.remove('on');
$('drop').ondrop = e => { e.preventDefault(); $('drop').classList.remove('on');
                          load(e.dataTransfer.files[0]); };
$('file').onchange = e => load(e.target.files[0]);

function load(f){
  if(!f) return;
  const r = new FileReader();
  r.onload = async () => {
    $('drop').innerHTML = '📷 ' + f.name + '<br><small>apasă pentru altă poză</small>';
    const res = await fetch('api/crop', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ image: r.result })});
    const d = await res.json();
    if(!d.ok){ alert('Eroare: ' + d.error); return; }
    job = d.job; iw = d.iw; ih = d.ih;
    autoRect = {...d.card};              // polaroidul intreg, cu marginile lui
    innerRect = {...d.photo};            // doar fotografia dinauntru
    rect = {...autoRect};                // implicit: polaroidul intreg
    imgEl = new Image();
    imgEl.onload = () => { $('cropbox').style.display = 'block';
                           drawCrop(); $('go').disabled = false; };
    imgEl.src = r.result;
  };
  r.readAsDataURL(f);
}

const cv = $('cropcv');
function drawCrop(){
  const W = 320, S = W / iw, H = Math.round(ih * S);
  cv.width = W; cv.height = H;
  const c = cv.getContext('2d');
  c.drawImage(imgEl, 0, 0, W, H);
  c.fillStyle = 'rgba(20,18,15,.55)';
  c.fillRect(0, 0, W, H);
  c.drawImage(imgEl, rect.x, rect.y, rect.w, rect.h,
              rect.x*S, rect.y*S, rect.w*S, rect.h*S);
  c.strokeStyle = '#fff'; c.lineWidth = 1.5;
  c.strokeRect(rect.x*S, rect.y*S, rect.w*S, rect.h*S);
  c.fillStyle = '#8c2f39';
  for(const [hx,hy] of corners())
    c.fillRect(hx*S-5, hy*S-5, 10, 10);
}
const corners = () => [[rect.x,rect.y],[rect.x+rect.w,rect.y],
                       [rect.x,rect.y+rect.h],[rect.x+rect.w,rect.y+rect.h]];
let drag = null;
cv.onpointerdown = e => {
  const S = cv.width / iw, p = pos(e);
  const cs = corners();
  for(let i = 0; i < 4; i++)
    if(Math.hypot((cs[i][0]-p.x)*S, (cs[i][1]-p.y)*S) < 14){ drag = {corner:i}; }
  if(!drag && p.x > rect.x && p.x < rect.x+rect.w &&
     p.y > rect.y && p.y < rect.y+rect.h)
    drag = {move:true, dx:p.x-rect.x, dy:p.y-rect.y};
  if(drag) cv.setPointerCapture(e.pointerId);
};
cv.onpointermove = e => {
  if(!drag) return;
  const p = pos(e), min = Math.min(iw, ih) * .08;
  let {x, y, w, h} = rect;
  if(drag.move){
    x = clamp(p.x-drag.dx, 0, iw-w); y = clamp(p.y-drag.dy, 0, ih-h);
  } else {
    let x1 = x+w, y1 = y+h;
    if(drag.corner===0){ x = clamp(p.x,0,x1-min); y = clamp(p.y,0,y1-min); }
    if(drag.corner===1){ x1 = clamp(p.x,x+min,iw); y = clamp(p.y,0,y1-min); }
    if(drag.corner===2){ x = clamp(p.x,0,x1-min); y1 = clamp(p.y,y+min,ih); }
    if(drag.corner===3){ x1 = clamp(p.x,x+min,iw); y1 = clamp(p.y,y+min,ih); }
    w = x1-x; h = y1-y;
  }
  rect = {x:Math.round(x), y:Math.round(y), w:Math.round(w), h:Math.round(h)};
  drawCrop();
};
cv.onpointerup = () => drag = null;
const pos = e => { const b = cv.getBoundingClientRect();
  return { x:(e.clientX-b.left)/b.width*iw, y:(e.clientY-b.top)/b.height*ih }; };
const clamp = (v,a,b) => Math.max(a, Math.min(b, v));
$('cropAuto').onclick = () => { rect = {...autoRect}; drawCrop(); };
$('cropInner').onclick = () => { rect = {...innerRect}; drawCrop(); };
$('cropFull').onclick = () => { rect = {x:0,y:0,w:iw,h:ih}; drawCrop(); };

const FILL_STYLES = ['mix','poster','color'];
$('go').onclick = () => generate(null);

async function generate(styles, labels, erase, added){
  $('go').disabled = true; $('spin').classList.add('on');
  $('hint').style.display = 'none';
  if(!styles) $('results').innerHTML = '';
  saveSettings();
  try {
    const body = { job, rect, photo:innerRect, size:+$('size').value,
      colors:+$('colors').value, clarity:+$('clarity').value,
      frame:$('frame').value, text:$('text').value.trim() };
    if(styles) body.styles = styles;
    if(labels) body.labels = labels;
    if(erase) body.erase = erase;
    if(added) body.added = added;
    const res = await fetch('api/digitize', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    const d = await res.json();
    if(!d.ok) throw new Error(d.error);
    for(const r of d.results) renderCard(r);
  } catch(err){ alert('Eroare: ' + err.message); }
  $('spin').classList.remove('on'); $('go').disabled = false;
}

function renderCard(r){
  let el = document.getElementById('res-' + r.style);
  if(!el){
    el = document.createElement('div');
    el.className = 'res'; el.id = 'res-' + r.style;
    $('results').appendChild(el);
  }
  const edit = FILL_STYLES.includes(r.style)
    ? `<button class="mini2" data-edit="1" title="Editează regiunile">✏️</button>` : '';
  const erz = r.style !== 'poster'
    ? `<button class="mini2" data-erase="${r.style}" title="Radieră de linii">🧽</button>` : '';
  el.innerHTML = `<h3><span>${r.title}</span><span>
      <button class="mini2" data-regen="${r.style}" title="Regenerează doar acest stil">↻</button>
      ${edit}${erz}</span></h3>
    <img src="${r.preview}">
    <div class="meta">${r.meta}</div>
    ${r.files.map(f=>`<a class="dl" href="${f.url}" download>⬇ ${f.name}</a>`).join('')}
    <details><summary>fire & detalii</summary><pre>${r.stats}</pre></details>`;
}

$('results').onclick = e => {
  const rb = e.target.closest('[data-regen]');
  if(rb){ generate([rb.dataset.regen]); return; }
  if(e.target.closest('[data-edit]')){ openEditor(); return; }
  const er_ = e.target.closest('[data-erase]');
  if(er_){ openEraser(er_.dataset.erase); return; }
  const img = e.target.closest('.res img');
  if(!img) return;
  $('lbImg').src = img.src;
  $('lbTitle').textContent = img.closest('.res').querySelector('h3').innerText;
  $('lightbox').classList.add('on');
};

// ---- editor de regiuni -------------------------------------------------
const FABRIC = [246,243,236];
let ed = { ids:null, w:0, h:0, colors:[], threads:[], sel:0, undo:[] };
const colOf = id => id === 255 ? FABRIC : (ed.colors[id] || FABRIC);

async function openEditor(){
  const res = await fetch('api/labels/' + job);
  if(!res.ok){ alert('Generează întâi stilurile.'); return; }
  const d = await res.json();
  ed.colors = d.colors; ed.threads = d.threads; ed.undo = []; ed.sel = 0;
  ed.photo = null;
  if(d.photo){
    const ph = new Image();
    ph.onload = () => { ed.photo = ph; edComposite(); };
    ph.src = d.photo;
  }
  const im = new Image();
  im.onload = () => {
    ed.w = im.width; ed.h = im.height;
    const c = document.createElement('canvas');
    c.width = ed.w; c.height = ed.h;
    const cx = c.getContext('2d', { willReadFrequently:true });
    cx.drawImage(im, 0, 0);
    const data = cx.getImageData(0, 0, ed.w, ed.h).data;
    ed.ids = new Uint8Array(ed.w * ed.h);
    for(let i = 0; i < ed.ids.length; i++) ed.ids[i] = data[i*4];
    buildPalette(); edPaintAll();
    $('editor').classList.add('on');
  };
  im.src = d.labels;
}
function buildPalette(){
  const pal = $('edpal'); pal.innerHTML = '';
  ed.colors.forEach((c, i) => {
    const t = ed.threads[i] || {};
    const b = document.createElement('button');
    b.className = 'swatch' + (i === ed.sel ? ' sel' : '');
    b.style.background = `rgb(${c[0]},${c[1]},${c[2]})`;
    b.title = '#' + (t.code||'') + ' ' + (t.desc||'');
    b.onclick = () => { ed.sel = i; buildPalette(); };
    pal.appendChild(b);
  });
  const g = document.createElement('button');
  g.className = 'swatch gol' + (ed.sel === 255 ? ' sel' : '');
  g.textContent = '✕'; g.title = 'Material gol (nu se coase)';
  g.onclick = () => { ed.sel = 255; buildPalette(); };
  pal.appendChild(g);
}
const edLayer = document.createElement('canvas');
function edRenderLayer(){
  edLayer.width = ed.w; edLayer.height = ed.h;
  const cx = edLayer.getContext('2d');
  const img = cx.createImageData(ed.w, ed.h);
  for(let i = 0; i < ed.ids.length; i++){
    const col = colOf(ed.ids[i]);
    img.data[i*4] = col[0]; img.data[i*4+1] = col[1];
    img.data[i*4+2] = col[2]; img.data[i*4+3] = 255;
  }
  cx.putImageData(img, 0, 0);
}
function edComposite(){
  const c = $('edcv');
  if(c.width !== ed.w){ c.width = ed.w; c.height = ed.h; }
  const cx = c.getContext('2d');
  if(ed.photo) cx.drawImage(ed.photo, 0, 0, ed.w, ed.h);
  else { cx.fillStyle = '#fff'; cx.fillRect(0, 0, ed.w, ed.h); }
  cx.globalAlpha = (+$('edalpha').value) / 100;
  cx.drawImage(edLayer, 0, 0);
  cx.globalAlpha = 1;
}
function edPaintAll(){ edRenderLayer(); edComposite(); }
$('edalpha').oninput = edComposite;
let edDown = false, edLast = null;
const edPos = e => { const b = $('edcv').getBoundingClientRect();
  return { x:(e.clientX-b.left)/b.width*ed.w, y:(e.clientY-b.top)/b.height*ed.h }; };
$('edcv').onpointerdown = e => { ed.undo.push(ed.ids.slice());
  if(ed.undo.length > 20) ed.undo.shift();
  edDown = true; edLast = null;
  $('edcv').setPointerCapture(e.pointerId); edStroke(edPos(e)); };
$('edcv').onpointermove = e => { if(edDown) edStroke(edPos(e)); };
$('edcv').onpointerup = () => edDown = false;
function edStroke(p){
  const r = +$('edbrush').value, pts = [];
  if(edLast){
    const d = Math.hypot(p.x-edLast.x, p.y-edLast.y),
          n = Math.ceil(d/(r/2)) || 1;
    for(let i = 1; i <= n; i++)
      pts.push({ x:edLast.x+(p.x-edLast.x)*i/n, y:edLast.y+(p.y-edLast.y)*i/n });
  } else pts.push(p);
  const cx = edLayer.getContext('2d'), col = colOf(ed.sel);
  cx.fillStyle = `rgb(${col[0]},${col[1]},${col[2]})`;
  for(const q of pts){
    for(let y = Math.max(0, Math.round(q.y-r));
        y <= Math.min(ed.h-1, Math.round(q.y+r)); y++)
      for(let x = Math.max(0, Math.round(q.x-r));
          x <= Math.min(ed.w-1, Math.round(q.x+r)); x++)
        if((x-q.x)**2 + (y-q.y)**2 <= r*r) ed.ids[y*ed.w+x] = ed.sel;
    cx.beginPath(); cx.arc(q.x, q.y, r, 0, 7); cx.fill();
  }
  edComposite();
  edLast = p;
}
$('edundo').onclick = () => { const u = ed.undo.pop();
  if(u){ ed.ids = u; edPaintAll(); } };
$('edclose').onclick = () => $('editor').classList.remove('on');
$('edapply').onclick = async () => {
  const c = document.createElement('canvas');
  c.width = ed.w; c.height = ed.h;
  const cx = c.getContext('2d');
  const img = cx.createImageData(ed.w, ed.h);
  for(let i = 0; i < ed.ids.length; i++){
    img.data[i*4] = img.data[i*4+1] = img.data[i*4+2] = ed.ids[i];
    img.data[i*4+3] = 255;
  }
  cx.putImageData(img, 0, 0);
  $('editor').classList.remove('on');
  await generate(FILL_STYLES, c.toDataURL('image/png'));
};

// ---- editor de linii (live): radiera + creion ---------------------------
let er = { mask:null, w:0, h:0, undo:[], bg:null, lines:[], added:[],
           tool:'erase' };
const linesCv = document.createElement('canvas');
async function openEraser(style){
  const res = await fetch(`api/lines/${job}/${style}`);
  if(!res.ok){ alert('Generează întâi stilul.'); return; }
  const d = await res.json();
  const bg = new Image();
  bg.onload = () => {
    er.bg = bg; er.w = bg.naturalWidth; er.h = bg.naturalHeight;
    er.mask = new Uint8Array(er.w * er.h); er.undo = [];
    er.lines = d.lines; er.added = []; setTool('erase');
    linesCv.width = er.w; linesCv.height = er.h;
    drawLines(); erComposite();
    $('eraser').classList.add('on');
  };
  bg.src = d.fills;
}
function setTool(t){
  er.tool = t;
  $('erToolE').classList.toggle('sel', t === 'erase');
  $('erToolD').classList.toggle('sel', t === 'draw');
}
$('erToolE').onclick = () => setTool('erase');
$('erToolD').onclick = () => setTool('draw');
function drawLines(){
  const cx = linesCv.getContext('2d');
  cx.clearRect(0, 0, er.w, er.h);
  cx.lineWidth = 4; cx.lineCap = 'round'; cx.lineJoin = 'round';
  for(const L of er.lines){
    cx.strokeStyle = L.hex;
    cx.beginPath();
    for(const path of L.paths){
      let pen = false;
      for(const pt of path){
        const ix = Math.min(er.w-1, Math.max(0, pt[0]|0)),
              iy = Math.min(er.h-1, Math.max(0, pt[1]|0));
        if(er.mask[iy*er.w + ix]){ pen = false; continue; }
        if(!pen){ cx.moveTo(pt[0], pt[1]); pen = true; }
        else cx.lineTo(pt[0], pt[1]);
      }
    }
    cx.stroke();
  }
  cx.strokeStyle = '#16161a';
  cx.beginPath();
  for(const s of er.added){
    let pen = false;
    for(const pt of s){
      const ix = Math.min(er.w-1, Math.max(0, pt[0]|0)),
            iy = Math.min(er.h-1, Math.max(0, pt[1]|0));
      if(er.mask[iy*er.w + ix]){ pen = false; continue; }
      if(!pen){ cx.moveTo(pt[0], pt[1]); pen = true; }
      else cx.lineTo(pt[0], pt[1]);
    }
  }
  cx.stroke();
}
function erComposite(){
  const c = $('ercv');
  if(c.width !== er.w){ c.width = er.w; c.height = er.h; }
  const cx = c.getContext('2d');
  cx.drawImage(er.bg, 0, 0);
  cx.drawImage(linesCv, 0, 0);
}
let erDown = false, erLast = null, erTick = false;
function erRefresh(){
  if(erTick) return;
  erTick = true;
  requestAnimationFrame(() => { drawLines(); erComposite(); erTick = false; });
}
const erPos = e => { const b = $('ercv').getBoundingClientRect();
  return { x:(e.clientX-b.left)/b.width*er.w, y:(e.clientY-b.top)/b.height*er.h }; };
$('ercv').onpointerdown = e => {
  er.undo.push({ mask: er.mask.slice(), n: er.added.length });
  if(er.undo.length > 20) er.undo.shift();
  erDown = true; erLast = null;
  if(er.tool === 'draw') er.added.push([]);
  $('ercv').setPointerCapture(e.pointerId); erStroke(erPos(e)); };
$('ercv').onpointermove = e => { if(erDown) erStroke(erPos(e)); };
$('ercv').onpointerup = () => {
  erDown = false;
  if(er.tool === 'draw' && er.added.length
     && er.added[er.added.length-1].length < 2) er.added.pop();
};
function erStroke(p){
  if(er.tool === 'draw'){
    const s = er.added[er.added.length-1];
    const last = s[s.length-1];
    if(last && Math.hypot(p.x-last[0], p.y-last[1]) < 2) return;
    s.push([Math.round(p.x*10)/10, Math.round(p.y*10)/10]);
    if(last){
      const cx = linesCv.getContext('2d');
      cx.strokeStyle = '#16161a'; cx.lineWidth = 4; cx.lineCap = 'round';
      cx.beginPath(); cx.moveTo(last[0], last[1]);
      cx.lineTo(p.x, p.y); cx.stroke();
      erComposite();
    }
    erLast = p;
    return;
  }
  const r = +$('erbrush').value, pts = [];
  if(erLast){
    const d = Math.hypot(p.x-erLast.x, p.y-erLast.y),
          n = Math.ceil(d/(r/2)) || 1;
    for(let i = 1; i <= n; i++)
      pts.push({ x:erLast.x+(p.x-erLast.x)*i/n, y:erLast.y+(p.y-erLast.y)*i/n });
  } else pts.push(p);
  for(const q of pts){
    for(let y = Math.max(0, Math.round(q.y-r));
        y <= Math.min(er.h-1, Math.round(q.y+r)); y++)
      for(let x = Math.max(0, Math.round(q.x-r));
          x <= Math.min(er.w-1, Math.round(q.x+r)); x++)
        if((x-q.x)**2 + (y-q.y)**2 <= r*r) er.mask[y*er.w+x] = 1;
  }
  erRefresh();
  erLast = p;
}
$('erundo').onclick = () => { const u = er.undo.pop();
  if(u){ er.mask = u.mask; er.added.length = u.n;
         drawLines(); erComposite(); } };
$('erclose').onclick = () => $('eraser').classList.remove('on');
$('erapply').onclick = async () => {
  const c = document.createElement('canvas');
  c.width = er.w; c.height = er.h;
  const cx = c.getContext('2d');
  const img = cx.createImageData(er.w, er.h);
  for(let i = 0; i < er.mask.length; i++){
    const v = er.mask[i] ? 255 : 0;
    img.data[i*4] = img.data[i*4+1] = img.data[i*4+2] = v;
    img.data[i*4+3] = 255;
  }
  cx.putImageData(img, 0, 0);
  $('eraser').classList.remove('on');
  await generate(['mix','sketch','color'], null, c.toDataURL('image/png'),
                 er.added.filter(s => s.length >= 2));
};

// ---- setari memorate + preview text ------------------------------------
function saveSettings(){
  try { localStorage.setItem('brodat', JSON.stringify({
    size:$('size').value, colors:$('colors').value, clarity:$('clarity').value,
    frame:$('frame').value, text:$('text').value })); } catch(e){}
}
$('text').oninput = e => $('tprev').textContent = e.target.value;
try {
  const s = JSON.parse(localStorage.getItem('brodat') || '{}');
  for(const k of ['size','colors','clarity','frame','text'])
    if(s[k] != null) $(k).value = s[k];
  $('size').dispatchEvent(new Event('input'));
  $('colors').dispatchEvent(new Event('input'));
  $('clarity').dispatchEvent(new Event('input'));
  $('text').dispatchEvent(new Event('input'));
} catch(e){}
$('lightbox').onclick = () => $('lightbox').classList.remove('on');
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') $('lightbox').classList.remove('on');
});
</script></body></html>"""


def run_style(job_dir, style, req):
    prefix = job_dir / style
    cmd = [sys.executable, str(ROOT / "digitize.py"), str(job_dir / "input.img"),
           "-o", str(prefix), "--style", style,
           "--size", str(req.get("size", 95)),
           "--colors", str(req.get("colors", 7)),
           "--clarity", str(req.get("clarity", 1.0)),
           "--frame", req.get("frame", "lines"), "--labels-out"]
    if req.get("_labels_file"):
        cmd += ["--labels-in", req["_labels_file"]]
    if req.get("_erase_file"):
        cmd += ["--erase-mask", req["_erase_file"]]
    if req.get("_added_file"):
        cmd += ["--add-lines", req["_added_file"]]
    if req.get("text"):
        cmd += ["--text", req["text"]]
    r = req.get("rect")
    if r:
        cmd += ["--crop-rect", f"{r['x']},{r['y']},{r['w']},{r['h']}"]
    p = req.get("photo")
    if p:
        cmd += ["--photo-rect", f"{p['x']},{p['y']},{p['w']},{p['h']}"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError(f"{style}: {p.stderr.strip()[-300:]}")
    preview = base64.b64encode((job_dir / f"{style}_preview.png").read_bytes())
    title = dict(STYLES)[style]
    meta = p.stdout.strip().splitlines()[-1].split("->")[0].strip()
    return {"style": style, "title": title, "meta": meta,
            "preview": "data:image/png;base64," + preview.decode(),
            "stats": p.stdout.strip() + "\n\n"
                     + (job_dir / f"{style}_fire.txt").read_text(),
            "files": [{"name": f"{style}.{e}", "url": f"files/{job_dir.name}/{style}.{e}"}
                      for e in ("pes", "dst")]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if self.path.startswith("/api/lines/"):
            parts = self.path.strip("/").split("/")
            if len(parts) == 4:
                job_dir = (WEB_OUT / parts[2]).resolve()
                style = parts[3]
                lj = job_dir / f"{style}_lines.json"
                fp = job_dir / f"{style}_fills.png"
                if (job_dir.is_relative_to(WEB_OUT) and lj.is_file()
                        and fp.is_file()):
                    d = {"lines": json.loads(lj.read_text()),
                         "fills": "data:image/png;base64,"
                                  + base64.b64encode(fp.read_bytes()).decode()}
                    return self._send(200, json.dumps(d).encode())
            return self._send(404, b'{"error":"fara linii"}')
        if self.path.startswith("/api/labels/"):
            job_dir = (WEB_OUT / self.path.rsplit("/", 1)[1]).resolve()
            if job_dir.is_dir() and job_dir.is_relative_to(WEB_OUT):
                lp = next((p for p in
                           [job_dir / "edited_labels.png"]
                           + [job_dir / f"{s}_labels.png" for s in FILL_STYLES]
                           if p.is_file()), None)
                cj = next((job_dir / f"{s}_centers.json" for s in FILL_STYLES
                           if (job_dir / f"{s}_centers.json").is_file()), None)
                if lp and cj:
                    d = json.loads(cj.read_text())
                    d["labels"] = "data:image/png;base64," \
                        + base64.b64encode(lp.read_bytes()).decode()
                    ep = next((job_dir / f"{s}_enhanced.png"
                               for s in FILL_STYLES
                               if (job_dir / f"{s}_enhanced.png").is_file()),
                              None)
                    if ep:               # poza, ca fundal sub harta de regiuni
                        d["photo"] = "data:image/png;base64," \
                            + base64.b64encode(ep.read_bytes()).decode()
                    return self._send(200, json.dumps(d).encode())
            return self._send(404, b'{"error":"fara regiuni"}')
        if self.path.startswith("/files/"):
            p = (WEB_OUT / self.path[len("/files/"):]).resolve()
            if p.is_file() and p.is_relative_to(WEB_OUT):
                return self._send(200, p.read_bytes(),
                                  "application/octet-stream",
                                  {"Content-Disposition":
                                   f'attachment; filename="{p.name}"'})
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/crop":
                job = uuid.uuid4().hex[:10]
                job_dir = WEB_OUT / job
                job_dir.mkdir(parents=True)
                (job_dir / "input.img").write_bytes(
                    base64.b64decode(req["image"].split(",", 1)[1]))
                p = subprocess.run(
                    [sys.executable, str(ROOT / "digitize.py"),
                     str(job_dir / "input.img"), "--detect-crop"],
                    capture_output=True, text=True, timeout=60)
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.strip()[-300:])
                d = json.loads(p.stdout)
                d.update(ok=True, job=job)
                return self._send(200, json.dumps(d).encode())

            if self.path == "/api/digitize":
                job_dir = (WEB_OUT / req["job"]).resolve()
                if not (job_dir.is_relative_to(WEB_OUT)
                        and (job_dir / "input.img").is_file()):
                    raise RuntimeError("sesiune expirata — reincarca poza")
                allowed = [s for s, _ in STYLES]
                styles = [s for s in (req.get("styles") or allowed)
                          if s in allowed]
                lf = job_dir / "edited_labels.png"
                ef = job_dir / "erase_mask.png"
                af = job_dir / "added_lines.json"
                if req.get("labels"):    # harta de regiuni editata in browser
                    lf.write_bytes(base64.b64decode(
                        req["labels"].split(",", 1)[1]))
                if req.get("erase"):     # masca de radiera pentru linii
                    ef.write_bytes(base64.b64decode(
                        req["erase"].split(",", 1)[1]))
                if req.get("added") is not None:   # linii desenate cu creionul
                    old = json.loads(af.read_text()) if af.is_file() else []
                    af.write_text(json.dumps(old + req["added"]))
                if req.get("styles"):    # regenerare partiala: edits raman
                    if lf.is_file():
                        req["_labels_file"] = str(lf)
                    if ef.is_file():
                        req["_erase_file"] = str(ef)
                    if af.is_file():
                        req["_added_file"] = str(af)
                else:                    # generare completa: pornim curat
                    lf.unlink(missing_ok=True)
                    ef.unlink(missing_ok=True)
                    af.unlink(missing_ok=True)
                with ThreadPoolExecutor(4) as ex:
                    results = list(ex.map(
                        lambda s: run_style(job_dir, s, req), styles))
                return self._send(200, json.dumps(
                    {"ok": True, "results": results}).encode())

            self._send(404, b'{"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())

    def log_message(self, fmt, *args):
        print(f"[web] {args[0] if args else ''}")


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


if __name__ == "__main__":
    WEB_OUT.mkdir(parents=True, exist_ok=True)
    print(f"Aplicatia ruleaza: http://localhost:{PORT}  (Ctrl+C pentru oprire)", flush=True)
    cls = DualStackServer if ":" in HOST else ThreadingHTTPServer
    cls((HOST, PORT), Handler).serve_forever()
