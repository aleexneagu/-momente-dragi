# Atelierul de brodat — motorul Python (polaroid -> .pes)
FROM python:3.12-slim

# opencv-python-headless are nevoie de libglib (libgthread)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY prototype/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prototype/ .

# Railway: rețeaua privată e IPv6, deci ascultăm dual-stack pe ::
ENV HOST=:: \
    PORT=8765

CMD ["python", "server.py"]
