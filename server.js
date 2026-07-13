const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'milan2026';

// notificări pe email la mesaje noi de contact (opțional — active doar dacă ambele sunt setate)
const RESEND_API_KEY = process.env.RESEND_API_KEY || '';
const NOTIFY_EMAIL = process.env.NOTIFY_EMAIL || '';
const NOTIFY_FROM = process.env.NOTIFY_FROM || 'onboarding@resend.dev';

const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const RSVP_DIR = path.join(DATA_DIR, 'confirmari');
const UPLOADS_DIR = path.join(DATA_DIR, 'uploads');
const INVITATIONS_FILE = path.join(DATA_DIR, 'invitatii.json');
const MESSAGES_FILE = path.join(DATA_DIR, 'mesaje.json');
const ORDERS_FILE = path.join(DATA_DIR, 'comenzi.json');
const VIEWS_FILE = path.join(DATA_DIR, 'views.json');
const TEMPLATE_FILE = path.join(__dirname, 'templates', 'invitatie.html');
const CONFIRMARI_TEMPLATE_FILE = path.join(__dirname, 'templates', 'confirmari.html');

if (!fs.existsSync(RSVP_DIR)) fs.mkdirSync(RSVP_DIR, { recursive: true });
if (!fs.existsSync(UPLOADS_DIR)) fs.mkdirSync(UPLOADS_DIR, { recursive: true });
if (!fs.existsSync(INVITATIONS_FILE)) {
  // volum nou și gol → pornește cu invitațiile din repo, dacă există
  const seed = path.join(__dirname, 'data', 'invitatii.json');
  if (seed !== INVITATIONS_FILE && fs.existsSync(seed)) fs.copyFileSync(seed, INVITATIONS_FILE);
  else fs.writeFileSync(INVITATIONS_FILE, '[]');
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.mp3': 'audio/mpeg'
};

const RO_ZILE = ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă'];
const RO_LUNI = ['Ianuarie', 'Februarie', 'Martie', 'Aprilie', 'Mai', 'Iunie',
  'Iulie', 'August', 'Septembrie', 'Octombrie', 'Noiembrie', 'Decembrie'];

// slug-uri care nu pot fi folosite de invitații (căi rezervate)
const RESERVED_SLUGS = ['admin', 'api', 'templates', 'data', 'public', 'demo', 'uploads'];

// pachetele comerciale — decid ce funcții primește invitația
const PACHETE = ['simplu', 'complet', 'premium'];
const MAX_FOTOGRAFII = 6;
const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,79}$/;

// invitație demonstrativă cu date fictive — arătată vizitatorilor de pe landing la /demo
const DEMO_INVITATION = {
  slug: 'demo',
  nume: 'Sofia Maria',
  parinti: 'Andrei & Ioana',
  nasi: 'Mihai & Elena',
  data: '2026-10-17',
  biserica: { nume: 'Biserica Sfânta Maria', adresa: 'Strada Exemplu 10, București', ora: '15:00' },
  petrecere: { nume: 'Salon Panoramic', adresa: 'Strada Exemplu 22, București', ora: '19:00' },
  pachet: 'premium',
  introText: 'Micuța noastră face primul pas într-o aventură plină de iubire și binecuvântare, iar noi ne-am bucura enorm să fiți alături de noi la Sfântul Botez.',
  mesajSafari: 'Pregătește-ți zâmbetul și spiritul de aventură! Leul, girafa, elefantul, zebra și toate animăluțele din safari abia așteaptă să sărbătorim împreună o zi plină de voie bună și amintiri frumoase. Vă așteptăm cu drag!',
  footerText: 'Cu drag, familia Sofiei 🦁 (invitație demonstrativă)'
};

// ---------- stocare ----------

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function loadInvitations() { return readJson(INVITATIONS_FILE, []); }
function saveInvitations(list) { fs.writeFileSync(INVITATIONS_FILE, JSON.stringify(list, null, 2)); }
function findInvitation(slug) {
  if (slug === DEMO_INVITATION.slug) return DEMO_INVITATION;
  return loadInvitations().find((i) => i.slug === slug);
}

function readMessages() { return readJson(MESSAGES_FILE, []); }
function writeMessages(list) { fs.writeFileSync(MESSAGES_FILE, JSON.stringify(list, null, 2)); }

function readOrders() { return readJson(ORDERS_FILE, []); }
function writeOrders(list) { fs.writeFileSync(ORDERS_FILE, JSON.stringify(list, null, 2)); }

function readViews() { return readJson(VIEWS_FILE, {}); }
function countView(slug) {
  const views = readViews();
  views[slug] = (views[slug] || 0) + 1;
  try { fs.writeFileSync(VIEWS_FILE, JSON.stringify(views, null, 2)); } catch {}
}

// pachetul decide funcțiile: galeria foto de la „complet", statisticile de la „premium"
function pachetOf(inv) { return PACHETE.includes(inv.pachet) ? inv.pachet : 'simplu'; }
function areGalerie(inv) { return pachetOf(inv) !== 'simplu'; }
function areStatistici(inv) { return pachetOf(inv) === 'premium'; }

function rsvpFile(slug) { return path.join(RSVP_DIR, slug + '.json'); }
function readRsvps(slug) { return readJson(rsvpFile(slug), []); }
function writeRsvps(slug, rsvps) { fs.writeFileSync(rsvpFile(slug), JSON.stringify(rsvps, null, 2)); }

// ---------- comenzi ----------

const TIPURI_EVENIMENT = ['botez', 'nunta', 'aniversare', 'altul'];
const TIP_LABEL = { botez: 'Botez', nunta: 'Nuntă', aniversare: 'Aniversare', altul: 'Alt eveniment' };

function sanitizeOrder(data) {
  const s = (v, max) => String(v || '').trim().slice(0, max);
  const order = {
    pachet: PACHETE.includes(data.pachet) ? data.pachet : 'simplu',
    tipEveniment: TIPURI_EVENIMENT.includes(data.tipEveniment) ? data.tipEveniment : '',
    sarbatorit: s(data.sarbatorit, 120),   // copilul / mirii / sărbătoritul
    parinti: s(data.parinti, 120),
    nasi: s(data.nasi, 120),
    data: s(data.data, 10),
    biserica: s(data.biserica, 250),
    petrecere: s(data.petrecere, 250),
    contactNume: s(data.contactNume, 120),
    contact: s(data.contact, 160),
    mesaj: s(data.mesaj, 1000)
  };
  if (!order.tipEveniment) return { error: 'Alege tipul evenimentului.' };
  if (!order.contactNume || !order.contact) return { error: 'Completează numele tău și telefonul sau e-mailul.' };
  if (order.data && (!/^\d{4}-\d{2}-\d{2}$/.test(order.data) || isNaN(new Date(order.data).getTime()))) {
    return { error: 'Data evenimentului este invalidă.' };
  }
  return { order };
}

// ---------- notificări email ----------

// fire-and-forget: nu blochează răspunsul către vizitator, iar o eroare de email
// nu afectează salvarea mesajului
function sendNotification(subject, html) {
  if (!RESEND_API_KEY || !NOTIFY_EMAIL || typeof fetch !== 'function') return;
  fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + RESEND_API_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ from: NOTIFY_FROM, to: [NOTIFY_EMAIL], subject, html })
  }).then(async (r) => {
    if (!r.ok) console.error('Notificare email eșuată:', r.status, await r.text().catch(() => ''));
  }).catch((err) => {
    console.error('Notificare email eșuată:', err.message);
  });
}

function notifyNewContactMessage(msg) {
  sendNotification('Mesaj nou de la ' + msg.name, `
    <div style="font-family:sans-serif;max-width:520px">
      <h2 style="margin:0 0 12px">Mesaj nou pe momente-dragi.ro</h2>
      <p><strong>Nume:</strong> ${escapeHtml(msg.name)}</p>
      <p><strong>Contact:</strong> ${escapeHtml(msg.contact)}</p>
      <p style="white-space:pre-wrap;background:#f6f6f6;border-radius:8px;padding:12px">${escapeHtml(msg.message)}</p>
      <p style="color:#888;font-size:13px">Poți răspunde și din secțiunea Mesaje a dashboardului de admin.</p>
    </div>`);
}

function notifyNewOrder(order) {
  const row = (label, val) => val
    ? `<tr><td style="padding:4px 12px 4px 0;color:#888;white-space:nowrap">${label}</td><td style="padding:4px 0"><strong>${escapeHtml(val)}</strong></td></tr>`
    : '';
  sendNotification(`Comandă nouă: ${TIP_LABEL[order.tipEveniment]} — pachet ${order.pachet}`, `
    <div style="font-family:sans-serif;max-width:560px">
      <h2 style="margin:0 0 12px">🎉 Comandă nouă pe momente-dragi.ro</h2>
      <table style="border-collapse:collapse;font-size:15px">
        ${row('Pachet', order.pachet)}
        ${row('Eveniment', TIP_LABEL[order.tipEveniment])}
        ${row('Sărbătorit', order.sarbatorit)}
        ${row('Părinții', order.parinti)}
        ${row('Nașii', order.nasi)}
        ${row('Data', order.data)}
        ${row('Biserica', order.biserica)}
        ${row('Petrecerea', order.petrecere)}
        ${row('Nume contact', order.contactNume)}
        ${row('Contact', order.contact)}
      </table>
      ${order.mesaj ? `<p style="white-space:pre-wrap;background:#f6f6f6;border-radius:8px;padding:12px">${escapeHtml(order.mesaj)}</p>` : ''}
      <p style="color:#888;font-size:13px">Din dashboard → Comenzi poți crea invitația direct din această comandă.</p>
    </div>`);
}

// ---------- randare invitație ----------

function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function mapsUrl(nume, adresa) {
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(nume + ', ' + adresa);
}

function renderInvitation(inv) {
  const template = fs.readFileSync(TEMPLATE_FILE, 'utf8');
  const d = new Date(inv.data + 'T' + (inv.biserica.ora || '12:00') + ':00');
  const vars = {
    slug: inv.slug,
    nume: inv.nume,
    introText: inv.introText,
    parinti: inv.parinti,
    nasi: inv.nasi,
    ziSaptamana: RO_ZILE[d.getDay()],
    zi: String(d.getDate()),
    lunaAn: RO_LUNI[d.getMonth()] + ' · ' + d.getFullYear(),
    dataLunga: d.getDate() + ' ' + RO_LUNI[d.getMonth()] + ' ' + d.getFullYear(),
    dataISO: inv.data + 'T' + (inv.biserica.ora || '12:00') + ':00',
    bisericaNume: inv.biserica.nume,
    bisericaAdresa: inv.biserica.adresa,
    bisericaOra: inv.biserica.ora,
    bisericaMaps: mapsUrl(inv.biserica.nume, inv.biserica.adresa),
    petrecereNume: inv.petrecere.nume,
    petrecereAdresa: inv.petrecere.adresa,
    petrecereOra: inv.petrecere.ora,
    petrecereMaps: mapsUrl(inv.petrecere.nume, inv.petrecere.adresa),
    mesajSafari: inv.mesajSafari,
    footerText: inv.footerText
  };
  // blocuri opționale de HTML (nescăpate) — {{{cheie}}} se înlocuiește înaintea {{cheie}}
  const raw = {
    galerieBlock: areGalerie(inv) ? galerieHtml(inv) : '',
    muzicaBlock: pachetOf(inv) === 'premium' && inv.melodie ? muzicaHtml(inv) : ''
  };
  return template
    .replace(/{{{(\w+)}}}/g, (_, key) => raw[key] ?? '')
    .replace(/{{(\w+)}}/g, (_, key) => escapeHtml(vars[key] ?? ''));
}

// buton plutitor de redare a melodiei — doar pentru pachetul Premium
function muzicaHtml(inv) {
  return `
    <audio id="muzica" src="/uploads/${escapeHtml(inv.melodie)}" loop preload="none"></audio>
    <button id="muzica-btn" type="button" aria-label="Pornește melodia" style="position:fixed;left:16px;bottom:16px;z-index:50;width:52px;height:52px;border-radius:999px;border:1px solid var(--line);background:linear-gradient(180deg,#fffdf7,#f3ead6);color:var(--ink);font-size:22px;cursor:pointer;box-shadow:0 10px 24px -10px rgba(90,70,40,.5);">🎵</button>
    <script>
      (function () {
        const audio = document.getElementById('muzica');
        const btn = document.getElementById('muzica-btn');
        btn.addEventListener('click', () => {
          if (audio.paused) { audio.play().catch(() => {}); btn.textContent = '⏸'; }
          else { audio.pause(); btn.textContent = '🎵'; }
        });
      })();
    </script>`;
}

// secțiunea de galerie foto — doar pentru pachetele Complet și Premium
function galerieHtml(inv) {
  const poze = Array.isArray(inv.fotografii) ? inv.fotografii : [];
  if (!poze.length) return '';
  const imgs = poze.map((f) =>
    `<a href="/uploads/${escapeHtml(f)}" target="_blank" rel="noopener"><img src="/uploads/${escapeHtml(f)}" loading="lazy" alt="Fotografie din galerie"></a>`
  ).join('');
  return `
    <section class="section" aria-label="Galerie foto">
      <p class="section-label">Galeria noastră</p>
      <style>
        .galerie { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
        .galerie a { display: block; border-radius: 14px; overflow: hidden; border: 1px solid var(--line); }
        .galerie img { display: block; width: 100%; height: 140px; object-fit: cover; transition: transform .25s; }
        .galerie a:hover img { transform: scale(1.04); }
      </style>
      <div class="galerie">${imgs}</div>
    </section>`;
}

function renderConfirmari(inv) {
  const template = fs.readFileSync(CONFIRMARI_TEMPLATE_FILE, 'utf8');
  const vars = { slug: inv.slug, nume: inv.nume };
  return template.replace(/{{(\w+)}}/g, (_, key) => escapeHtml(vars[key] ?? ''));
}

// ---------- validare ----------

function sanitizeInvitation(data) {
  const s = (v, max) => String(v || '').trim().slice(0, max);
  const loc = (l) => ({
    nume: s(l && l.nume, 120),
    adresa: s(l && l.adresa, 200),
    ora: s(l && l.ora, 5)
  });
  const inv = {
    slug: s(data.slug, 80).toLowerCase(),
    nume: s(data.nume, 120),
    parinti: s(data.parinti, 120),
    nasi: s(data.nasi, 120),
    data: s(data.data, 10),
    biserica: loc(data.biserica),
    petrecere: loc(data.petrecere),
    introText: s(data.introText, 1000),
    mesajSafari: s(data.mesajSafari, 1000),
    footerText: s(data.footerText, 200),
    parolaAdmin: s(data.parolaAdmin, 60), // opțional — acces la /slug/admin pentru familie
    pachet: PACHETE.includes(data.pachet) ? data.pachet : 'simplu'
  };

  if (!SLUG_RE.test(inv.slug)) return { error: 'Slug invalid — folosește doar litere mici, cifre și cratime.' };
  if (RESERVED_SLUGS.includes(inv.slug)) return { error: 'Acest slug este rezervat.' };
  if (!inv.nume) return { error: 'Numele copilului este obligatoriu.' };
  if (!inv.parinti || !inv.nasi) return { error: 'Părinții și nașii sunt obligatorii.' };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inv.data) || isNaN(new Date(inv.data).getTime())) {
    return { error: 'Data este invalidă.' };
  }
  for (const [eticheta, l] of [['biserică', inv.biserica], ['petrecere', inv.petrecere]]) {
    if (!l.nume || !l.adresa) return { error: `Completează numele și adresa pentru ${eticheta}.` };
    if (!/^\d{2}:\d{2}$/.test(l.ora)) return { error: `Ora pentru ${eticheta} este invalidă (format HH:MM).` };
  }
  return { inv };
}

// ---------- helpers http ----------

function sendJson(res, status, obj) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(obj));
}

function sendHtml(res, status, html) {
  res.writeHead(status, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(html);
}

function isMaster(req) {
  return req.headers['x-admin-password'] === ADMIN_PASSWORD;
}

// parola master sau parola proprie a invitației (pentru pagina familiei)
function canManageRsvps(req, inv) {
  if (isMaster(req)) return true;
  return !!(inv && inv.parolaAdmin && req.headers['x-admin-password'] === inv.parolaAdmin);
}

function readBody(req, maxSize = 100_000) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > maxSize) {
        reject(new Error('body too large'));
        req.destroy();
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

const NOT_FOUND_PAGE = `<!DOCTYPE html><html lang="ro"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Invitația nu există</title>
<style>body{font-family:Georgia,serif;background:#f8f3e8;color:#5a4a3a;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center}
h1{font-size:56px;margin:0 0 8px}</style></head>
<body><div><h1>🦁</h1><p>Ne pare rău, invitația căutată nu există.</p></div></body></html>`;

// ---------- server ----------

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);

  // --- API public: salvează o confirmare pentru o invitație ---
  // POST /api/rsvp/:slug
  if (req.method === 'POST' && parts[0] === 'api' && parts[1] === 'rsvp' && parts.length === 3) {
    const slug = parts[2];
    if (!findInvitation(slug)) return sendJson(res, 404, { error: 'Invitația nu există' });
    try {
      const data = JSON.parse(await readBody(req));
      const name = String(data.name || '').trim().slice(0, 120);
      const persons = Math.min(20, Math.max(1, parseInt(data.persons, 10) || 1));
      if (!name) return sendJson(res, 400, { error: 'Te rog introdu-ți numele!' });
      const rsvps = readRsvps(slug);
      rsvps.push({
        id: crypto.randomUUID(),
        name,
        persons,
        church: !!data.church,
        party: !!data.party,
        message: String(data.message || '').trim().slice(0, 500),
        createdAt: new Date().toISOString()
      });
      writeRsvps(slug, rsvps);
      return sendJson(res, 200, { ok: true });
    } catch {
      return sendJson(res, 400, { error: 'A apărut o eroare. Te rog încearcă din nou.' });
    }
  }

  // --- API public: mesaj de contact de pe landing ---
  // POST /api/contact
  if (req.method === 'POST' && parts[0] === 'api' && parts[1] === 'contact' && parts.length === 2) {
    try {
      const data = JSON.parse(await readBody(req));
      const name = String(data.name || '').trim().slice(0, 120);
      const contact = String(data.contact || '').trim().slice(0, 160);
      const message = String(data.message || '').trim().slice(0, 1000);
      if (!name || !contact || !message) {
        return sendJson(res, 400, { error: 'Completează numele, datele de contact și mesajul.' });
      }
      const messages = readMessages();
      const msg = { id: crypto.randomUUID(), name, contact, message, createdAt: new Date().toISOString() };
      messages.push(msg);
      writeMessages(messages);
      notifyNewContactMessage(msg);
      return sendJson(res, 200, { ok: true });
    } catch {
      return sendJson(res, 400, { error: 'A apărut o eroare. Încearcă din nou.' });
    }
  }

  // --- API public: comandă de pachet de pe landing ---
  // POST /api/comanda
  if (req.method === 'POST' && parts[0] === 'api' && parts[1] === 'comanda' && parts.length === 2) {
    try {
      const { order, error } = sanitizeOrder(JSON.parse(await readBody(req)));
      if (error) return sendJson(res, 400, { error });
      order.id = crypto.randomUUID();
      order.createdAt = new Date().toISOString();
      const orders = readOrders();
      orders.push(order);
      writeOrders(orders);
      notifyNewOrder(order);
      return sendJson(res, 200, { ok: true });
    } catch {
      return sendJson(res, 400, { error: 'A apărut o eroare. Încearcă din nou.' });
    }
  }

  // --- API confirmări (parola master sau parola proprie a invitației) ---

  // GET /api/rsvps/:slug — confirmările unei invitații
  if (req.method === 'GET' && parts[0] === 'api' && parts[1] === 'rsvps' && parts.length === 3) {
    const inv = findInvitation(parts[2]);
    if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
    if (!canManageRsvps(req, inv)) return sendJson(res, 401, { error: 'Parolă incorectă' });
    return sendJson(res, 200, {
      rsvps: readRsvps(parts[2]),
      pachet: pachetOf(inv),
      views: areStatistici(inv) ? (readViews()[inv.slug] || 0) : null
    });
  }

  // DELETE /api/rsvp/:slug/:id — șterge o confirmare
  if (req.method === 'DELETE' && parts[0] === 'api' && parts[1] === 'rsvp' && parts.length === 4) {
    const inv = findInvitation(parts[2]);
    if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
    if (!canManageRsvps(req, inv)) return sendJson(res, 401, { error: 'Parolă incorectă' });
    const rsvps = readRsvps(parts[2]);
    const idx = rsvps.findIndex((r) => r.id === parts[3]);
    if (idx === -1) return sendJson(res, 404, { error: 'Confirmarea nu a fost găsită' });
    rsvps.splice(idx, 1);
    writeRsvps(parts[2], rsvps);
    return sendJson(res, 200, { ok: true });
  }

  // --- API admin platformă (doar parola master) ---
  if (parts[0] === 'api' && parts[1] === 'admin') {
    if (!isMaster(req)) return sendJson(res, 401, { error: 'Parolă incorectă' });

    // GET /api/admin/invitations — lista invitațiilor + nr. confirmări
    if (req.method === 'GET' && parts[1] === 'admin' && parts[2] === 'invitations' && parts.length === 3) {
      const list = loadInvitations().map((inv) => ({ ...inv, rsvpCount: readRsvps(inv.slug).length }));
      return sendJson(res, 200, { invitations: list });
    }

    // POST /api/admin/invitations — creează o invitație
    if (req.method === 'POST' && parts[1] === 'admin' && parts[2] === 'invitations' && parts.length === 3) {
      try {
        const { inv, error } = sanitizeInvitation(JSON.parse(await readBody(req)));
        if (error) return sendJson(res, 400, { error });
        const list = loadInvitations();
        if (list.some((i) => i.slug === inv.slug)) {
          return sendJson(res, 409, { error: 'Există deja o invitație cu acest slug.' });
        }
        inv.createdAt = new Date().toISOString();
        inv.fotografii = [];
        list.push(inv);
        saveInvitations(list);
        return sendJson(res, 200, { ok: true, invitation: inv });
      } catch {
        return sendJson(res, 400, { error: 'Date invalide' });
      }
    }

    // PUT /api/admin/invitations/:slug — actualizează (slug-ul rămâne fix)
    if (req.method === 'PUT' && parts[1] === 'admin' && parts[2] === 'invitations' && parts.length === 4) {
      try {
        const list = loadInvitations();
        const idx = list.findIndex((i) => i.slug === parts[3]);
        if (idx === -1) return sendJson(res, 404, { error: 'Invitația nu există' });
        const body = JSON.parse(await readBody(req));
        body.slug = parts[3];
        const { inv, error } = sanitizeInvitation(body);
        if (error) return sendJson(res, 400, { error });
        inv.createdAt = list[idx].createdAt;
        inv.fotografii = list[idx].fotografii || []; // pozele și melodia se gestionează prin endpoint-urile lor
        if (list[idx].melodie) inv.melodie = list[idx].melodie;
        list[idx] = inv;
        saveInvitations(list);
        return sendJson(res, 200, { ok: true, invitation: inv });
      } catch {
        return sendJson(res, 400, { error: 'Date invalide' });
      }
    }

    // DELETE /api/admin/invitations/:slug — șterge invitația și confirmările ei
    if (req.method === 'DELETE' && parts[1] === 'admin' && parts[2] === 'invitations' && parts.length === 4) {
      const list = loadInvitations();
      const idx = list.findIndex((i) => i.slug === parts[3]);
      if (idx === -1) return sendJson(res, 404, { error: 'Invitația nu există' });
      for (const f of list[idx].fotografii || []) {
        try { fs.unlinkSync(path.join(UPLOADS_DIR, f)); } catch {}
      }
      if (list[idx].melodie) { try { fs.unlinkSync(path.join(UPLOADS_DIR, list[idx].melodie)); } catch {} }
      list.splice(idx, 1);
      saveInvitations(list);
      try { fs.unlinkSync(rsvpFile(parts[3])); } catch {}
      return sendJson(res, 200, { ok: true });
    }

    // POST /api/admin/invitations/:slug/photos — adaugă fotografii (JSON cu data-URL-uri)
    if (req.method === 'POST' && parts[2] === 'invitations' && parts[4] === 'photos' && parts.length === 5) {
      try {
        const list = loadInvitations();
        const inv = list.find((i) => i.slug === parts[3]);
        if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
        if (!areGalerie(inv)) return sendJson(res, 400, { error: 'Galeria foto e disponibilă doar la pachetele Complet și Premium.' });
        const data = JSON.parse(await readBody(req, 15_000_000));
        const images = Array.isArray(data.images) ? data.images : [];
        if (!images.length) return sendJson(res, 400, { error: 'Nicio imagine primită.' });
        inv.fotografii = inv.fotografii || [];
        if (inv.fotografii.length + images.length > MAX_FOTOGRAFII) {
          return sendJson(res, 400, { error: `Maxim ${MAX_FOTOGRAFII} fotografii per invitație.` });
        }
        const EXT = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp' };
        for (const img of images) {
          const m = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/.exec(String(img));
          if (!m) return sendJson(res, 400, { error: 'Format de imagine neacceptat (doar JPG, PNG, WebP).' });
          const buf = Buffer.from(m[2], 'base64');
          if (buf.length > 4_000_000) return sendJson(res, 400, { error: 'O fotografie depășește 4 MB.' });
          const file = inv.slug + '-' + crypto.randomUUID().slice(0, 8) + EXT[m[1]];
          fs.writeFileSync(path.join(UPLOADS_DIR, file), buf);
          inv.fotografii.push(file);
        }
        saveInvitations(list);
        return sendJson(res, 200, { ok: true, fotografii: inv.fotografii });
      } catch {
        return sendJson(res, 400, { error: 'Imaginile nu au putut fi încărcate (prea mari?).' });
      }
    }

    // POST /api/admin/invitations/:slug/melodie — încarcă melodia (MP3, doar Premium)
    if (req.method === 'POST' && parts[2] === 'invitations' && parts[4] === 'melodie' && parts.length === 5) {
      try {
        const list = loadInvitations();
        const inv = list.find((i) => i.slug === parts[3]);
        if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
        if (pachetOf(inv) !== 'premium') return sendJson(res, 400, { error: 'Melodia e disponibilă doar la pachetul Premium.' });
        const data = JSON.parse(await readBody(req, 15_000_000));
        const m = /^data:audio\/(?:mpeg|mp3);base64,([A-Za-z0-9+/=]+)$/.exec(String(data.audio || ''));
        if (!m) return sendJson(res, 400, { error: 'Format neacceptat — alege un fișier MP3.' });
        const buf = Buffer.from(m[1], 'base64');
        if (buf.length > 8_000_000) return sendJson(res, 400, { error: 'Melodia depășește 8 MB.' });
        if (inv.melodie) { try { fs.unlinkSync(path.join(UPLOADS_DIR, inv.melodie)); } catch {} }
        inv.melodie = inv.slug + '-muzica-' + crypto.randomUUID().slice(0, 8) + '.mp3';
        fs.writeFileSync(path.join(UPLOADS_DIR, inv.melodie), buf);
        saveInvitations(list);
        return sendJson(res, 200, { ok: true, melodie: inv.melodie });
      } catch {
        return sendJson(res, 400, { error: 'Melodia nu a putut fi încărcată (prea mare?).' });
      }
    }

    // DELETE /api/admin/invitations/:slug/melodie — șterge melodia
    if (req.method === 'DELETE' && parts[2] === 'invitations' && parts[4] === 'melodie' && parts.length === 5) {
      const list = loadInvitations();
      const inv = list.find((i) => i.slug === parts[3]);
      if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
      if (inv.melodie) { try { fs.unlinkSync(path.join(UPLOADS_DIR, inv.melodie)); } catch {} }
      delete inv.melodie;
      saveInvitations(list);
      return sendJson(res, 200, { ok: true });
    }

    // DELETE /api/admin/invitations/:slug/photos/:file — șterge o fotografie
    if (req.method === 'DELETE' && parts[2] === 'invitations' && parts[4] === 'photos' && parts.length === 6) {
      const list = loadInvitations();
      const inv = list.find((i) => i.slug === parts[3]);
      if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
      const idx = (inv.fotografii || []).indexOf(parts[5]);
      if (idx === -1) return sendJson(res, 404, { error: 'Fotografia nu a fost găsită' });
      inv.fotografii.splice(idx, 1);
      saveInvitations(list);
      try { fs.unlinkSync(path.join(UPLOADS_DIR, parts[5])); } catch {}
      return sendJson(res, 200, { ok: true, fotografii: inv.fotografii });
    }

    // GET /api/admin/messages — mesajele de contact
    if (req.method === 'GET' && parts[2] === 'messages' && parts.length === 3) {
      return sendJson(res, 200, { messages: readMessages() });
    }

    // GET /api/admin/orders — comenzile de pachete
    if (req.method === 'GET' && parts[2] === 'orders' && parts.length === 3) {
      return sendJson(res, 200, { orders: readOrders() });
    }

    // DELETE /api/admin/orders/:id — șterge o comandă
    if (req.method === 'DELETE' && parts[2] === 'orders' && parts.length === 4) {
      const orders = readOrders();
      const idx = orders.findIndex((o) => o.id === parts[3]);
      if (idx === -1) return sendJson(res, 404, { error: 'Comanda nu a fost găsită' });
      orders.splice(idx, 1);
      writeOrders(orders);
      return sendJson(res, 200, { ok: true });
    }

    // DELETE /api/admin/messages/:id — șterge un mesaj
    if (req.method === 'DELETE' && parts[2] === 'messages' && parts.length === 4) {
      const messages = readMessages();
      const idx = messages.findIndex((m) => m.id === parts[3]);
      if (idx === -1) return sendJson(res, 404, { error: 'Mesajul nu a fost găsit' });
      messages.splice(idx, 1);
      writeMessages(messages);
      return sendJson(res, 200, { ok: true });
    }

    return sendJson(res, 404, { error: 'Ruta nu există' });
  }

  // --- pagini ---
  if (req.method === 'GET' || req.method === 'HEAD') {
    // rădăcina → pagina de prezentare; /admin → dashboard-ul de configurare
    if (url.pathname === '/' || url.pathname === '/admin') {
      const file = url.pathname === '/' ? 'landing.html' : 'admin.html';
      return fs.readFile(path.join(PUBLIC_DIR, file), (err, content) => {
        if (err) return sendHtml(res, 500, '<h1>Eroare</h1>');
        res.writeHead(200, { 'Content-Type': MIME['.html'] });
        res.end(content);
      });
    }

    // /:slug/admin → confirmările invitației (pagina familiei)
    if (parts.length === 2 && parts[1] === 'admin') {
      const inv = findInvitation(parts[0]);
      if (inv) return sendHtml(res, 200, renderConfirmari(inv));
      return sendHtml(res, 404, NOT_FOUND_PAGE);
    }

    // /uploads/:file → fotografiile din galerie (de pe volumul de date)
    if (parts.length === 2 && parts[0] === 'uploads') {
      const file = path.basename(parts[1]); // fără traversare de directoare
      return fs.readFile(path.join(UPLOADS_DIR, file), (err, content) => {
        if (err) return sendHtml(res, 404, NOT_FOUND_PAGE);
        res.writeHead(200, {
          'Content-Type': MIME[path.extname(file)] || 'application/octet-stream',
          'Cache-Control': 'public, max-age=86400'
        });
        res.end(content);
      });
    }

    // /:slug → invitația randată din template
    if (parts.length === 1 && !parts[0].includes('.')) {
      const inv = findInvitation(parts[0]);
      if (inv) {
        if (req.method === 'GET' && inv.slug !== DEMO_INVITATION.slug) countView(inv.slug);
        return sendHtml(res, 200, renderInvitation(inv));
      }
      return sendHtml(res, 404, NOT_FOUND_PAGE);
    }

    // fișiere statice (imagini etc.)
    const resolved = path.join(PUBLIC_DIR, path.normalize(url.pathname));
    if (!resolved.startsWith(PUBLIC_DIR)) {
      res.writeHead(403);
      return res.end();
    }
    return fs.readFile(resolved, (err, content) => {
      if (err) return sendHtml(res, 404, NOT_FOUND_PAGE);
      res.writeHead(200, { 'Content-Type': MIME[path.extname(resolved)] || 'application/octet-stream' });
      res.end(content);
    });
  }

  res.writeHead(405);
  res.end();
});

server.listen(PORT, () => {
  console.log(`Dashboard: http://localhost:${PORT}/ (parola: ${ADMIN_PASSWORD})`);
  for (const inv of loadInvitations()) {
    console.log(`Invitație: http://localhost:${PORT}/${inv.slug} — ${inv.nume} (confirmări: /${inv.slug}/admin)`);
  }
});
