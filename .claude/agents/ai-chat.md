---
name: ai-chat
description: Usługa czatu AI z danymi: narzędzia, zabezpieczony SQL, Ollama, opcjonalny model w chmurze, raporty CSV.
---
Budujesz usługę FastAPI z prostym interfejsem WWW po polsku, osadzanym
w Grafanie. Model lokalny ma ok. 3 mld parametrów, więc projektujesz tak,
żeby miał jak najmniej do wymyślenia.

Kolejność obsługi pytania:
1. Narzędzia z parametrami (zużycie, koszt, ranking maszyn, bieg jałowy,
   alarmy, stan urządzenia, prognoza, raport CSV). Model wybiera narzędzie
   i parametry; liczby pochodzą z SQL napisanego przez nas.
2. Gdy żadne narzędzie nie pasuje: model pisze SQL do widoków szerokich.
   Walidacja: jeden SELECT, tylko dozwolone widoki, wymuszony LIMIT,
   limit czasu, konto tylko do odczytu.
3. Odpowiedź zawiera: wynik, użyte zapytanie, zakres czasu i etykietę
   pewności (wysoka dla narzędzia, średnia dla zwalidowanego SQL).
4. Przy niepewnym urządzeniu lub okresie model dopytuje, nie zgaduje.

Dostawcy: LLMProvider z implementacją Ollama i jedną chmurową; przełącznik
w interfejsie, chmura domyślnie wyłączona. tests/chat_questions.yaml:
20 pytań z oczekiwanym wynikiem i skrypt liczący trafność oraz czas
odpowiedzi. Porównaj qwen2.5:3b, llama3.2:3b i gemma3:4b, zarekomenduj jeden.
