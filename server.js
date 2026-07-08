const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'milan2026';

const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const RSVP_DIR = path.join(DATA_DIR, 'confirmari');
const INVITATIONS_FILE = path.join(DATA_DIR, 'invitatii.json');
const TEMPLATE_FILE = path.join(__dirname, 'templates', 'invitatie.html');
const CONFIRMARI_TEMPLATE_FILE = path.join(__dirname, 'templates', 'confirmari.html');

if (!fs.existsSync(RSVP_DIR)) fs.mkdirSync(RSVP_DIR, { recursive: true });
if (!fs.existsSync(INVITATIONS_FILE)) fs.writeFileSync(INVITATIONS_FILE, '[]');

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
  '.woff2': 'font/woff2'
};

const RO_ZILE = ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă'];
const RO_LUNI = ['Ianuarie', 'Februarie', 'Martie', 'Aprilie', 'Mai', 'Iunie',
  'Iulie', 'August', 'Septembrie', 'Octombrie', 'Noiembrie', 'Decembrie'];

// slug-uri care nu pot fi folosite de invitații (căi rezervate)
const RESERVED_SLUGS = ['admin', 'api', 'templates', 'data', 'public'];
const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,79}$/;

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
function findInvitation(slug) { return loadInvitations().find((i) => i.slug === slug); }

function rsvpFile(slug) { return path.join(RSVP_DIR, slug + '.json'); }
function readRsvps(slug) { return readJson(rsvpFile(slug), []); }
function writeRsvps(slug, rsvps) { fs.writeFileSync(rsvpFile(slug), JSON.stringify(rsvps, null, 2)); }

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
  return template.replace(/{{(\w+)}}/g, (_, key) => escapeHtml(vars[key] ?? ''));
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
    parolaAdmin: s(data.parolaAdmin, 60) // opțional — acces la /slug/admin pentru familie
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

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 100_000) {
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

  // --- API confirmări (parola master sau parola proprie a invitației) ---

  // GET /api/rsvps/:slug — confirmările unei invitații
  if (req.method === 'GET' && parts[0] === 'api' && parts[1] === 'rsvps' && parts.length === 3) {
    const inv = findInvitation(parts[2]);
    if (!inv) return sendJson(res, 404, { error: 'Invitația nu există' });
    if (!canManageRsvps(req, inv)) return sendJson(res, 401, { error: 'Parolă incorectă' });
    return sendJson(res, 200, { rsvps: readRsvps(parts[2]) });
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
      list.splice(idx, 1);
      saveInvitations(list);
      try { fs.unlinkSync(rsvpFile(parts[3])); } catch {}
      return sendJson(res, 200, { ok: true });
    }

    return sendJson(res, 404, { error: 'Ruta nu există' });
  }

  // --- pagini ---
  if (req.method === 'GET' || req.method === 'HEAD') {
    // rădăcina și /admin → dashboard-ul de configurare
    if (url.pathname === '/' || url.pathname === '/admin') {
      return fs.readFile(path.join(PUBLIC_DIR, 'admin.html'), (err, content) => {
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

    // /:slug → invitația randată din template
    if (parts.length === 1 && !parts[0].includes('.')) {
      const inv = findInvitation(parts[0]);
      if (inv) return sendHtml(res, 200, renderInvitation(inv));
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
