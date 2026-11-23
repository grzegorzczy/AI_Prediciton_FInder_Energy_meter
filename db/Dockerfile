# Kontener `migrate`: jednorazowy runner migracji i ról (etap 2, k2). Python 3.12, obraz przypięty digestem.
# Skrypt i migracje są wbudowane w obraz, a prawa odczytu ustawiane przy budowie: wynik nie zależy od
# umask ani uprawnień plików w klonie na hoście (git pull pod umask 077 daje pliki 600).
# Po `git pull` nowe migracje stosuje `docker compose up -d --build`.
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home --uid 10001 migrate
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY migrate.py .
COPY migrations /migrations
RUN chmod -R a+rX /app /migrations
USER migrate
CMD ["python", "/app/migrate.py"]
