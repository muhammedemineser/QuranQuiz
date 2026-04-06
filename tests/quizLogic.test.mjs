import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getNextLockedVerse,
  buildQuestionOptions,
  applyCorrectAnswer,
  computeSurahProgress,
} from '../quizLogic.mjs';

const sampleVerses = [
  { verse_index: 100, verse_number: 1, text_ar: 'A1' },
  { verse_index: 101, verse_number: 2, text_ar: 'A2' },
  { verse_index: 102, verse_number: 3, text_ar: 'A3' },
  { verse_index: 103, verse_number: 4, text_ar: 'A4' },
];

test('getNextLockedVerse returns first locked verse', () => {
  const next = getNextLockedVerse(sampleVerses, 100);
  assert.equal(next.verse_index, 101);
});

test('getNextLockedVerse returns null when surah is complete', () => {
  const next = getNextLockedVerse(sampleVerses, 999);
  assert.equal(next, null);
});

test('buildQuestionOptions includes correct verse and requested size', () => {
  const correct = sampleVerses[2];
  const options = buildQuestionOptions(sampleVerses, correct, 4);

  assert.equal(options.length, 4);
  assert.equal(options.filter((v) => v.verse_index === correct.verse_index).length, 1);
});

test('applyCorrectAnswer only updates for matching correct index', () => {
  assert.equal(applyCorrectAnswer(100, 101, 101), 101);
  assert.equal(applyCorrectAnswer(100, 102, 101), 100);
});

test('computeSurahProgress returns rounded percentage and unlocked counters', () => {
  const progress = computeSurahProgress(sampleVerses, 101);
  assert.deepEqual(progress, { total: 4, unlocked: 2, pct: 50 });
});
