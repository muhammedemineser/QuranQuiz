# Quran Quiz – Django App

> Legacy backend — Branch: `legacy-django`
> Statische Playground-Version: Branch `main`

## Setup

```bash
pip install django
python manage.py migrate
python manage.py runserver
```

quran.db schema

```sql
CREATE TABLE chapters (
    chapter_number INTEGER PRIMARY KEY,
    chapter_name   TEXT
);

CREATE TABLE verses (
    verse_index    INTEGER PRIMARY KEY,
    surah_number   INTEGER,
    verse_number   INTEGER,
    text_ar        TEXT,
    text_en        TEXT
);
```

## Structure

```
quran_quiz/
├── manage.py
├── quran.db
├── db.sqlite3        ← Django app DB (users, progress)
├── quiz/
│   ├── db_config.py  ← all table/column names
│   ├── quran_db.py   ← all raw SQL queries + F1 distractor logic
│   ├── models.py     ← SurahProgress
│   ├── views.py
│   ├── urls.py
│   └── templates/quiz/
│       ├── base.html
│       ├── auth.html
│       ├── mushaf.html
│       └── progress.html
```

## Features

- **Mushaf view**: Verses blurred/locked until unlocked via quiz
- **Quiz**: Multiple choice, 4 options — distractors ranked by F1 word overlap
- **Wrong answer**: Other options remain for retry; correct answer highlighted
- **Progress**: Per-user, per-surah — stored in `SurahProgress` model
- **Progress page**: Progress bars per surah + reset per-surah or all
- **Auth**: Django built-in User + login/register pages

## Optional: Precompute Distractors

```bash
python3 build_distractor_cache.py
```

## Unterschiede: Static vs Django

| | Static (main) | Django (legacy-django) |
|---|---|---|
| Deployment | GitHub Pages | eigener Server |
| Auth | clientseitiger Mock | serverseitige Session |
| State | localStorage | DB (`SurahProgress`) |
| API | json-server | Django Views |
| Sicherheit | nicht produktionsreif | strukturiert, aber ohne Härteconfig |
