# Atelierul de brodat 🧵

Transformă polaroide în fișiere de broderie Brother (`.pes`): umpleri tatami,
desen în linie, text „scris de mână" cusut, editor de regiuni, radieră și creion.

## Local

```bash
cd prototype
python3 server.py        # http://localhost:8765
```

Necesită `opencv-python-headless`, `numpy`, `Pillow`, `pyembroidery`
(`pip install -r prototype/requirements.txt`).

## Pe Railway (serviciul din spatele momente-dragi.ro/brodat)

Serviciul se construiește din `Dockerfile` și ascultă pe `::` (IPv6, rețeaua
privată Railway), portul `8765`. Site-ul principal (momente-dragi) face proxy
către el prin variabila `BRODAT_URL`, ex.:

```
BRODAT_URL=http://brodat.railway.internal:8765
```

Rezultatele se scriu în `prototype/out/web/` (disc efemer — se pierd la
redeploy; descarcă fișierele `.pes` imediat după generare).
