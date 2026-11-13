# Protokół współpracy: Claude Code ↔ architekt ↔ Grzegorz

Claude Code i czat projektu w claude.ai („architekt”) nie widzą swoich rozmów.
Komunikują się przez pliki w `docs/handoff/` w tym repozytorium. Grzegorz decyduje
i daje sygnał, że coś czeka na drugą stronę.

## Role

| Kto | Robi | Nie robi |
| --- | --- | --- |
| Grzegorz | Decyduje, daje „ok”, wykonuje testy na sprzęcie, wgrywa program do PLC | – |
| Architekt (czat projektu) | Przegląda plany i raporty, podejmuje z Grzegorzem decyzje, prowadzi Ubuntu i PLC, pisze dokumenty projektu | Nie pisze kodu usług |
| Claude Code | Planuje i implementuje kroki w repo, testuje, commituje, uruchamia agenta reviewer | Nie zaczyna kolejnego kroku bez „ok”; nie zmienia architektury ani `docs/modbus-map.md` |

## Jednostki pracy

- **Etap** – z `docs/plan.md` (0–7), ma kryterium „gotowe, gdy”.
- **Krok** – najmniejsza część etapu, która kończy się czymś sprawdzalnym
  (przechodzące testy, commit, polecenie do wykonania na sprzęcie).
  Lista kroków etapu powstaje w kroku 0 etapu (plan etapu).

## Cykl jednego kroku

1. **Plan** – Claude Code zapisuje `docs/handoff/eN-kM-plan.md` i kończy wiadomością:
   `Plan eN-kM gotowy do przeglądu.` Niczego nie implementuje.
2. **Przegląd planu** – Grzegorz pisze w czacie projektu „przejrzyj eN-kM-plan”.
   Architekt czyta plik i zapisuje obok `docs/handoff/eN-kM-review.md`.
3. **Decyzja** – Grzegorz pisze Claude Code: „przeczytaj eN-kM-review, ok”
   (albo z poprawkami). Claude Code stosuje uwagi; przy sporze pyta Grzegorza.
4. **Wykonanie** – Claude Code realizuje tylko ten krok, uruchamia testy, robi commit.
5. **Raport** – Claude Code zapisuje `docs/handoff/eN-kM-report.md` i kończy:
   `Raport eN-kM gotowy.` Zatrzymuje się.
6. **Przegląd raportu** – architekt zapisuje `docs/handoff/eN-kM-report-review.md`
   z werdyktem. Grzegorz wykonuje checklistę na sprzęcie, jeśli jest.
7. Dopiero po „ok” Grzegorza zaczyna się krok `kM+1`.

Drobne kroki (np. zmiana jednego pliku konfiguracyjnego) mogą łączyć plan i wykonanie,
jeśli Grzegorz tak zdecyduje w danym kroku.

## Nazwy plików

`e2-k0-plan.md` = etap 2, krok 0 (plan etapu). `e2-k3-report.md` = raport kroku 3.
Pliki handoff są commitowane – to historia decyzji.

## Szablon: plan (Claude Code)

```markdown
# eN-kM plan: <nazwa kroku>
Status: DO PRZEGLĄDU
## Cel kroku
## Co powstaje / zmienia się (pliki)
## Decyzje do podjęcia (każda z propozycją i uzasadnieniem)
## Ryzyka i założenia (co zakładam bez potwierdzenia)
## Jak sprawdzę, że działa (testy, polecenia)
## Poza zakresem
```

## Szablon: raport (Claude Code)

```markdown
# eN-kM raport: <nazwa kroku>
Status: DO PRZEGLĄDU
## Co zrobiono (pliki, commit)
## Wyniki testów (polecenie + wynik)
## Odstępstwa od planu i dlaczego
## Zmierzone zasoby (RAM, dysk) – jeśli dotyczy
## Checklista dla Grzegorza (polecenia na sprzęcie, oczekiwany wynik)
## Otwarte kwestie
```

## Szablon: review (architekt)

```markdown
# eN-kM review
Werdykt: OK | OK Z UWAGAMI | DO POPRAWY
## Uwagi (od najważniejszej; każda: co, dlaczego, propozycja)
## Decyzje (podjęte z Grzegorzem / do podjęcia)
## Zgodność z CLAUDE.md i zasadami twardymi
```

## Zasady

- Jedna strona nie nadpisuje plików drugiej; odpowiedź to nowy plik.
- Spór między review a Claude Code rozstrzyga Grzegorz.
- Ustalenie, które ma przetrwać etap, trafia też do `docs/decisions.md`
  (architekt zapisuje je dodatkowo jako dokument projektu).
