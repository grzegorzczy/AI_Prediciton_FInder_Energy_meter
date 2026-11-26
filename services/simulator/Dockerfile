# Symulator (etap 3, k3): wirtualne liczniki i pompa -> MQTT (QoS 0, linia symulatora). Python 3.12, obraz jak collector.
# PYTHONTZPATH pusty: zoneinfo bierze bazę stref wyłącznie z przypiętego pakietu tzdata (K2R-U1), nie z systemu.
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src PYTHONTZPATH=""
RUN useradd --system --no-create-home --uid 10003 simulator \
    && mkdir -p /var/lib/simulator && chown simulator /var/lib/simulator
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src /app/src
RUN chmod -R a+rX /app
USER simulator
CMD ["python", "-m", "simulator.main"]
