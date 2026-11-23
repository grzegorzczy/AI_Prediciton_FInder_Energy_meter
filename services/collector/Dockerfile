# Collector (etap 2, k3): Modbus TCP (tylko odczyt, FC04) -> MQTT. Python 3.12, obraz przypięty digestem.
# Kod kopiowany z prawami odczytu ustawionymi przy budowie (wynik nie zależy od umask na hoście).
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
RUN useradd --system --no-create-home --uid 10002 collector
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src /app/src
RUN chmod -R a+rX /app
USER collector
CMD ["python", "-m", "collector.main"]
