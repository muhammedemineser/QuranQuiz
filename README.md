# Quran Quiz – Django App

## Setup

```bash
pip install django
python manage.py migrate
python manage.py createsuperuser  # optional
python manage.py runserver
```

## Required: quran.db

Place your `quran.db` in the project root (next to `manage.py`).

Expected schema (configurable in `quiz/db_config.py`):

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
├── quran.db          ← your DB goes here
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
