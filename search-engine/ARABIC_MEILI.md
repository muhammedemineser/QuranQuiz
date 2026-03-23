# Arabic Meilisearch Pipeline

Dieses Setup nutzt eine lokal laufende Meilisearch-Instanz fuer schnelle lexikalische Suche und erweitert den Index vorab mit arabisch-spezifischer Vorverarbeitung:

- Tokenisierung via `camel_word_tokenize`
- Normalisierung analog zur bestehenden `normalize`-Logik aus `ranking.py`
- Morphologische Analyse via `camel_morphology analyze` auf roh tokenisierten arabischen Tokens
- zusaetzliche Felder fuer Lemma, Stem, Edge-N-Grams und Character-N-Grams
- dynamische Stop-Woerter aus dem Referenzkorpus
- Re-Ranking, das exakte Matches staerker gewichtet
- persistenter Run-Cache fuer vorbereitete Datensaetze und unveraenderte Referenz-Indizes

## Lokale Instanz starten

```bash
docker run -it --rm -p 7700:7700 getmeili/meilisearch
```

Optional mit Master-Key:

```bash
docker run -it --rm -p 7700:7700 -e MEILI_MASTER_KEY=masterKey getmeili/meilisearch
```

## Dry Run

```bash
python3 search-engine/arabic_db_search.py \
  --cand Data/Hadith/Bukhari.db \
  --cand-table hadiths \
  --cand-col Arabic_Matn \
  --cand-id-col Hadith_number \
  --ref Data/Hadith/Muslim.db \
  --ref-table hadiths \
  --ref-col Arabic_Matn \
  --ref-id-col Hadith_number \
  --cand-limit 5 \
  --ref-limit 20 \
  --dry-run
```

## DB gegen DB

```bash
python3 search-engine/arabic_db_search.py \
  --cand Data/Hadith/Bukhari.db \
  --cand-table hadiths \
  --cand-col Arabic_Matn \
  --cand-id-col Hadith_number \
  --ref Data/Hadith/Muslim.db \
  --ref-table hadiths \
  --ref-col Arabic_Matn \
  --ref-id-col Hadith_number \
  --ref Data/Hadith/AbuDaud.db \
  --ref-table hadiths \
  --ref-col Arabic_Matn \
  --ref-id-col Hadith_number \
  --config search-engine/arabic_search_config.example.json \
  --output search-engine/arabic_matches.json
```

## Ergebnisformat

Die Ausgabe ist ein eingeruecktes JSON-Objekt mit:

- `run`: Lauf-Metadaten und Cache-Hits
- `indexes`: Informationen zu den aufgebauten oder wiederverwendeten Referenz-Indizes
- `results`: die eigentlichen Kandidaten mit ihren Treffern

Innerhalb von `results` enthaelt jeder Eintrag:

- `candidate`: Candidate-Metadaten
- `matches`: pro Referenz-DB die Top-Treffer
- in `matches[*].hits` die aggregierten Scores aus Exact-, Lemma-, Stem- und N-Gram-Suchen

## Cache

Unter `search-engine/.cache/arabic-meili` werden jetzt drei Ebenen wiederverwendet:

- Tokenisierung pro Text
- Morphologie pro Token
- vorbereitete Candidate-/Reference-Datensaetze pro Run-Signatur
- Referenz-Index-Metadaten pro Datensatz- und Config-Signatur

Wenn sich Referenzdaten und Konfiguration nicht geaendert haben, wird beim naechsten Lauf das Reindexing uebersprungen. In den Debug-Ausgaben erscheinen dazu `candidate_prepare_cache_hit`, `reference_prepare_cache_hits` und beim Indexieren `cache_hit`.

## Hinweise zur Relevanz

- `rankingRules` priorisieren `exactness` frueh, damit exakte arabische Uebereinstimmungen bevorzugt werden.
- `searchableAttributes` setzen `exact_text` und `normalized_text` vor morphologischen Hilfsfeldern.
- Stop-Woerter werden pro Referenzkorpus dynamisch aus Dokumentfrequenzen abgeleitet.
- Morphologie bleibt extern; Meilisearch speichert nur vorberechnete Felder.
- CAMeL-Morphologie laeuft bewusst auf `raw_tokens`; die aggressive Normalisierung wird erst fuer Suchfelder wie `normalized_text`, `edge_ngrams` und `char_ngrams` verwendet.
- Wenn spaeter semantische Suche gebraucht wird, kann oberhalb dieser Pipeline ein Embedding-Reranker ergaenzt werden.
