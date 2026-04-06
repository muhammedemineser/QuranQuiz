# QuranQuiz

## GitHub Pages
Die statische Playground-Version ist hier erreichbar:

- `https://<github-username>.github.io/QuranQuiz/`

Wenn dein Repo anders heißt, ist das Muster:

- `https://<github-username>.github.io/<repo-name>/`

## Project Root
Im Root liegt die statische, deploybare App (GitHub Pages tauglich):

- `index.html` UI-Entry
- `styles.css` Styling inkl. Security-Warnungen
- `app.mjs` Hauptlogik (Login, Surah-Rendering, Quiz, Progress)
- `quizLogic.mjs` Kernalgorithmus (Question/Answer/Progress)
- `userSync.mjs` MockAPI-User-Sync inkl. POST-Seeding
- `data/quran-data.json` statischer Quran-Datensatz für Frontend
- `tests/*.mjs` Node-Tests für Kernlogik und User-Seeding
- `django-project/` ursprüngliches Django-Backend + Originaldaten

## Sicherheitshinweis
**Dringend:** Diese App ist ein Playground mit MockAPI und LocalStorage.

- Keine sichere Datenablage
- Keine verschlüsselten Secrets
- Keine produktionsreife Authentifizierung
- Alle Eingaben als potenziell öffentlich/unsicher behandeln

**Bitte niemals sensible Daten eingeben**, insbesondere keine:

- echten Passwörter
- persönlichen Daten
- produktiven Accounts
- Tokens, API-Keys, vertraulichen Inhalte

Nur Mock-Namen und Mock-Passwörter verwenden.

## Frontend (Static Playground)
### Start lokal
```bash
cd /home/muhammed-emin-eser/desk/projects/QuranQuiz
python3 -m http.server 8080
```
Dann `http://localhost:8080` öffnen.

### MockAPI-Flow
- Endpoint: `https://69d3a8f6336103955f8f653b.mockapi.io/quranquiz/users`
- App ruft `GET /users` auf
- Falls leer: App sendet Seed-User per `POST /users`
- Danach erneutes `GET /users`
- Ergebnis wird in `localStorage` gecacht

## Backend (Django) mit HASM-Bezug
Der Ordner `django-project/` enthält das ursprüngliche Backend. Für die Beschreibung nutze ich HASM als Architektur-Linse:

- `H = HTTP/Handlers`
- `A = Authentication`
- `S = State`
- `M = Model`

### H: HTTP/Handlers
Dateien:

- `django-project/quiz/urls.py`
- `django-project/quiz/views.py`

Zentrale Routen:

- `/` Mushaf-Ansicht
- `/login/`, `/register/`, `/logout/`
- `/progress/`
- `/api/question/` nächste Frage
- `/api/answer/` Antwort prüfen + Unlock
- `/api/reset/` Fortschritt resetten

### A: Authentication
Django-Auth wird serverseitig genutzt:

- `UserCreationForm` (Register)
- `AuthenticationForm` (Login)
- `login_required` schützt Mushaf/Progress/API

Das ist der zentrale Unterschied zur statischen Version:

- Django: serverseitige Session/Auth
- Static Playground: clientseitiger Mock-Login (nicht sicher)

### S: State
Lernfortschritt wird pro User und Surah gespeichert:

- Model: `SurahProgress(user, surah_number, unlocked_up_to)`
- Unlock-Regel: Bei korrekter Antwort wird `unlocked_up_to` erhöht
- Progress-Ansicht berechnet pro Surah den prozentualen Stand

### M: Model + Datenzugriff
Persistenzquellen im Django-Projekt:

- `db.sqlite3` für Django-App-Daten (User + Progress)
- `quran.db` für Quran-Inhalt

Datenzugriff:

- `quiz/quran_db.py` liest Kapitel/Verse aus `quran.db`
- `quiz/models.py` enthält `SurahProgress`
- `quiz/db_config.py` kapselt Tabellen-/Spaltennamen

### Distractor/Quiz-Logik im Backend
- `quiz/quran_db.py` nutzt precomputed Distractor-Cache (`quiz/.cache/distractor_cache.json`), falls vorhanden
- `build_distractor_cache.py` kann Cache vorab erzeugen
- API liefert Frageoptionen und validiert Antworten serverseitig

## Unterschiede: Static vs Django
- Static App ist deploybar auf GitHub Pages, aber nicht sicherheitskritisch nutzbar
- Django-App ist strukturierter für echte Backend-Flows (Auth, persistenter State, serverseitige APIs)
- Für Produktion wäre ein echtes Security-Setup nötig (HTTPS-Policies, Secret-Handling, harte Auth, Input-Härtung, Monitoring)
