# QuranQuiz

**Hifz training through Mutashābihāt recognition.**

The hardest part of memorizing the Quran (*Hifz*) is *Mutashābihāt* — verses so similar they collapse into each other in memory. QuranQuiz targets exactly this:

- Given a verse, pick the correct *next verse* from 4 options
- Wrong options are not random — they are the *most similar verses* in the entire Quran (Mutashābihāt), ranked by a word-level similarity algorithm
- Wrong answer → immediate feedback, loop until correct
- Progress tracked per surah — mastered verses unlock in the Mushaf view

**Live demo:** [mu-mino.github.io/QuranQuiz](https://mu-mino.github.io/QuranQuiz/)

---

## Project Structure

| File | Description |
|---|---|
| `index.html` | UI entry point |
| `styles.css` | Styling |
| `app.mjs` | Main logic (login, surah rendering, quiz, progress) |
| `quizLogic.mjs` | Core algorithm (question / answer / progress) |
| `userSync.mjs` | User sync helpers |
| `user.json` | User data for json-server |
| `data/quran-data.json` | Static Quran dataset |
| `tests/*.mjs` | Node tests for core logic and user sync |
| `django-project/` | Original Django backend + source data (→ branch `legacy-django`) |

---

## Getting Started

```bash
# Terminal 1 — json-server (port 3000)
npx json-server user.json

# Terminal 2 — static dev server
npx serve .
```

Then open `http://localhost:3000` (or the port shown by the dev server).

---

## User Flow

- Endpoint: `http://localhost:3000/users`
- App fetches `GET /users` on load
- Result is cached in `localStorage`
- Log in with any username from `user.json`

---

## Legacy Backend

The original Django version is available in the [`legacy-django`](../../tree/legacy-django) branch, including setup instructions, architecture, matching logic from Auto-Classify-Hadith Repo HASM Branch, routes, auth, state model, and distractor logic.

> **Note:** This branch (static app) is deployable on GitHub Pages — no real auth, no persistent state.
