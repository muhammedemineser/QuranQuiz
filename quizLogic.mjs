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

export function buildQuestionOptions(verses, correctVerse, size = 4) {
  const distractors = verses.filter((verse) => verse.verse_index !== correctVerse.verse_index);
  const shuffledDistractors = shuffleInPlace(distractors).slice(0, Math.max(0, size - 1));
  return shuffleInPlace([correctVerse, ...shuffledDistractors]);
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
