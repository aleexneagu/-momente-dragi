# Invitații de botez 🦁 (tema Safari)

Platformă de invitații cu formular de confirmare (RSVP) și dashboard de administrare.
Fiecare invitație primește propriul link, de forma `/botez-milan-alexandru`.

## Cum pornești site-ul

```bash
node server.js
```

Apoi deschide în browser:

- **Dashboard admin:** http://localhost:3000/ — parola implicită: `milan2026`
- **O invitație:** http://localhost:3000/botez-milan-alexandru
- **Confirmările unei invitații (pagina familiei):** http://localhost:3000/botez-milan-alexandru/admin

Nu trebuie instalat nimic (`npm install` nu e necesar) — folosește doar Node.js.

## Cum creezi o invitație nouă

1. Intră pe `/admin` și autentifică-te.
2. Apasă **➕ Invitație nouă** și completează: numele copilului, părinții, nașii,
   data, biserica și petrecerea (nume, adresă, oră), textele.
3. Linkul (slug-ul) se generează automat din nume (ex. `botez-milan-alexandru`)
   și poate fi ajustat înainte de salvare; după salvare rămâne fix.
4. Din listă poți **copia linkul**, **edita** invitația sau **vedea confirmările** ei.

## Pagina familiei (`/slug/admin`)

Fiecare invitație are o pagină proprie de confirmări, ex.
`/botez-milan-alexandru/admin`, pe care o poți trimite părinților copilului.
Ei văd doar confirmările invitației lor — nu pot crea, edita sau șterge invitații.

Accesul se face cu **parola pentru familie**, pe care o setezi (opțional) în
formularul de creare/editare al invitației. Parola ta master funcționează și acolo.
Dacă nu setezi o parolă de familie, doar tu poți intra pe pagină.

## Unde se salvează datele

- Invitațiile: `data/invitatii.json`
- Confirmările: câte un fișier per invitație în `data/confirmari/<slug>.json`

Fă-le backup din când în când.

## Șablonul invitației

Designul paginii de invitație e în `templates/invitatie.html` — serverul înlocuiește
placeholder-ele `{{...}}` cu datele fiecărei invitații. Modifici o singură dată, se
aplică tuturor invitațiilor.

## Schimbarea parolei de admin

Pornește serverul cu variabila de mediu `ADMIN_PASSWORD`:

```bash
ADMIN_PASSWORD=parola-mea node server.js
```

## Publicare pe internet

Ca invitații să poată confirma de pe telefonul lor, site-ul trebuie găzduit online.
Variante simple: [Render](https://render.com), [Railway](https://railway.app),
[Fly.io](https://fly.io) — toate pot rula direct `node server.js`. Apoi leagă un
domeniu propriu (ex. `my-invitation.com`) din setările platformei, iar linkurile
devin `my-invitation.com/botez-milan-alexandru`.

**Atenție:** `data/` trebuie să fie pe un disc persistent (Render/Railway oferă
„persistent volume"), altfel confirmările se pierd la fiecare redeploy.
