function shuffleInPlace(items) {
  const arr = [...items];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export function getNextLockedVerse(verses, unlockedUpTo) {
  for (const verse of verses) {
    if (verse.verse_index > unlockedUpTo) {
      return verse;
    }
  }
  return null;
}

/**
 * Builds answer options for a quiz question.
 *
 * @param {object} correctVerse - The verse to unlock next.
 * @param {object} allVersesByIndex - Flat map of verse_index → verse (all surahs).
 * @param {object} distractorCache - Map of verse_index (string) → number[] from the precomputed cache.
 * @param {number} size - Total number of options including the correct one.
 */
export function buildQuestionOptions(correctVerse, allVersesByIndex, distractorCache, size = 4) {
  const cachedIndices = distractorCache[String(correctVerse.verse_index)] ?? [];

  const distractors = [];
  for (const idx of cachedIndices) {
    if (distractors.length >= size - 1) break;
    const verse = allVersesByIndex[idx];
    if (verse && verse.verse_index !== correctVerse.verse_index) {
      distractors.push(verse);
    }
  }

  if (distractors.length < size - 1) {
    const needed = size - 1 - distractors.length;
    const usedIndices = new Set([correctVerse.verse_index, ...distractors.map((v) => v.verse_index)]);
    const fallbacks = shuffleInPlace(
      Object.values(allVersesByIndex).filter((v) => !usedIndices.has(v.verse_index)),
    ).slice(0, needed);
    distractors.push(...fallbacks);
  }

  return shuffleInPlace([correctVerse, ...distractors]);
}

export function applyCorrectAnswer(currentUnlockedUpTo, chosenIndex, correctIndex) {
  if (chosenIndex !== correctIndex) {
    return currentUnlockedUpTo;
  }
  if (correctIndex > currentUnlockedUpTo) {
    return correctIndex;
  }
  return currentUnlockedUpTo;
}

export function computeSurahProgress(verses, unlockedUpTo) {
  const total = verses.length;
  const unlocked = verses.filter((verse) => verse.verse_index <= unlockedUpTo).length;
  const pct = total === 0 ? 0 : Math.round((unlocked / total) * 100);
  return { total, unlocked, pct };
}
